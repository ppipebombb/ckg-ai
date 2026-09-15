"""
CAPTCHA Solver Module
=====================
Solves image-based CAPTCHAs from the ASIK login page.

Solver types (set via config["captcha_solver"]["type"]):
  - "agent"  : hand the captcha to the orchestrating AGENT (Claude/Kimi/…). The
               scraper upscales + emits the image and blocks until the agent
               writes the answer to a file. Best for agent-driven research —
               uses the agent's own vision (usually stronger than a 27B OCR),
               no external endpoint. NOT for unattended cron (no agent present).
  - "llm"    : OpenAI-compatible Vision API (e.g. ocr.juxtalabs qwen). Requires
               api_key, model, base_url. Use for UNATTENDED runs.
  - "manual" : Terminal prompt (dev/standalone only; unusable in headless workers).

The solver has NO Playwright dependency — it operates on image files only,
making it independently testable and trivially swappable.
"""

import base64
import json
import time
from pathlib import Path

from PIL import Image
from rich.console import Console

console = Console()


def solve_captcha(image_path: Path, config: dict = None) -> str:
    """Given a CAPTCHA image file, return the text answer.

    Parameters
    ----------
    image_path : Path
        Absolute path to the saved CAPTCHA screenshot (PNG).
    config : dict, optional
        Full config dict. LLM solver reads api_key/model/base_url from
        ``config["captcha_solver"]``.

    Returns
    -------
    str
        The CAPTCHA text. Empty string signals failure — caller retries.
    """
    config = config or {}
    solver_cfg = config.get("captcha_solver", {})
    solver_type = solver_cfg.get("type", "manual")

    if solver_type == "agent":
        return _solve_agent(image_path, solver_cfg)
    if solver_type == "llm":
        return _solve_llm(image_path, solver_cfg)
    if solver_type == "manual":
        return _solve_manual(image_path)
    console.print(
        f"[yellow]Unknown captcha solver type '{solver_type}', falling back to manual[/yellow]"
    )
    return _solve_manual(image_path)


def _upscale_captcha(image_path: Path, factor: int = 4, out_path: Path = None) -> Path:
    """Return a path to a ``factor``× LANCZOS-upscaled copy of the captcha.

    The raw element screenshot is small + noisy; enlarging it markedly improves
    read accuracy for BOTH the agent handoff and the OCR vision model. Saves to
    ``out_path`` when given, else ``<stem>_4x.png`` beside the original. Falls
    back to the original path on any error.
    """
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)
        dst = out_path or (image_path.parent / f"{image_path.stem}_4x.png")
        img.save(dst)
        return dst
    except Exception:
        return image_path


def _solve_agent(image_path: Path, solver_cfg: dict) -> str:
    """Hand the captcha to the orchestrating agent and block for its answer.

    The raw captcha element shot is small + noisy, so we upscale 4x (LANCZOS)
    to a stable ``captcha_pending.png`` — that's the difference between a fuzzy
    and an exact agent read. We print a ``CAPTCHA_HANDOFF: <png>`` marker on
    stdout and poll for ``captcha_answer.txt`` (same dir). The agent, watching
    the scraper's output, reads the PNG with its own vision and writes the
    digits to that file.

    Config (optional): ``handoff_dir`` (default = image dir),
    ``handoff_timeout`` seconds (default 240). Returns "" on timeout → caller
    refreshes + retries (the 20-attempt loop in auth.py).
    """
    work_dir = Path(solver_cfg.get("handoff_dir") or image_path.parent)
    work_dir.mkdir(parents=True, exist_ok=True)
    pending = work_dir / "captcha_pending.png"
    answer_file = work_dir / "captcha_answer.txt"

    # Clear any stale answer FIRST — before publishing the image. The writer
    # (agent) waits for captcha_pending.png, so unlinking after we create it
    # would race-delete a fast answer.
    try:
        answer_file.unlink()
    except Exception:
        pass

    pending = _upscale_captcha(image_path, out_path=pending)

    # Reserved stdout marker — the agent (or backend log stream) watches for it.
    print(f"CAPTCHA_HANDOFF: {pending}", flush=True)
    console.print(
        f"  [bold cyan]>>> agent: read {pending.name}, write the digits to "
        f"{answer_file.name} <<<[/bold cyan]"
    )

    timeout = float(solver_cfg.get("handoff_timeout", 240))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if answer_file.exists():
            try:
                txt = answer_file.read_text(encoding="utf-8").strip()
            except Exception:
                txt = ""
            if txt:
                for f in (answer_file, pending):
                    try:
                        f.unlink()
                    except Exception:
                        pass
                return txt
        time.sleep(1)
    console.print("  [yellow]agent handoff timed out; refreshing captcha[/yellow]")
    return ""


def _solve_llm(image_path: Path, solver_cfg: dict) -> str:
    """Call an OpenAI-compatible Vision API to read the CAPTCHA.

    Emits a single ``LLM_USAGE: {json}`` line to stdout so the backend
    Celery worker can parse token usage and write it to llm_logs.
    Returns the stripped CAPTCHA text, or "" on any error.
    """
    import httpx

    api_key = solver_cfg["api_key"]
    base_url = solver_cfg["base_url"].rstrip("/")
    model = solver_cfg["model"]
    # OpenRouter provider routing pin (e.g. "z-ai") — hard-pin the upstream,
    # no fallback. Only send when the config sets one: other gateways 400 on
    # the unknown `provider` body field.
    route_order = (solver_cfg.get("route_order") or "").strip()

    # Upscale 4× first — same high-res treatment the agent path gets; the raw
    # element shot is too small/noisy for reliable OCR.
    llm_img = _upscale_captcha(image_path)
    with open(llm_img, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    payload = {
        "model": model,
        "max_completion_tokens": 1024,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Read the numbers shown in the image. "
                    "Reply with only those numbers. No quotes, no spaces, no other text. "
                    "If a digit is ambiguous, pick the most likely digit; "
                    "always return exactly 4 digits."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": "Read the numbers in this image and reply with only those numbers.",
                    },
                ],
            },
        ],
    }

    if route_order:
        payload["provider"] = {
            "order": [x.strip() for x in route_order.split(",") if x.strip()],
            "allow_fallbacks": False,
        }

    t0 = time.monotonic()
    success = False
    text = ""
    usage: dict = {}
    err = None

    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
        if r.status_code >= 400:
            # Capture status + provider error type/code (not the api_key, not full headers)
            err = f"HTTP {r.status_code}"
            try:
                body = r.json().get("error") or {}
                code = body.get("code") or body.get("type")
                if code:
                    err = f"HTTP {r.status_code} {code}"
            except Exception:
                pass
        else:
            data = r.json()
            usage = data.get("usage") or {}
            choices = data.get("choices") or []
            content = ""
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
            text = content.strip()
            if text:
                success = True
            else:
                err = "empty_choices"
    except Exception as exc:
        # Never include str(exc) — httpx exceptions can echo URL + auth headers
        err = type(exc).__name__

    latency_ms = int((time.monotonic() - t0) * 1000)

    details = (usage.get("completion_tokens_details") or {})
    marker = {
        "source": "asik_captcha",
        "model": model,
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "latency_ms": latency_ms,
        "success": success,
        "error": err,
    }
    # The "LLM_USAGE:" stdout prefix is reserved — the backend Celery worker
    # parses it out of the live log stream. Do not emit other lines starting
    # with this token from anywhere in the scraper.
    print(f"LLM_USAGE: {json.dumps(marker, separators=(',', ':'))}", flush=True)

    for f in (image_path, llm_img):
        try:
            f.unlink()
        except Exception:
            pass

    return text


def _display_image_in_terminal(image_path: Path, max_width: int = 80):
    """Render an image in the terminal using colored half-block characters."""
    img = Image.open(image_path).convert("RGB")
    width = min(img.width, max_width)
    aspect = img.height / img.width
    height = int(width * aspect)
    height += height % 2
    img = img.resize((width, height), Image.NEAREST)

    pixels = img.load()
    lines = []
    for y in range(0, height, 2):
        parts = []
        for x in range(width):
            tr, tg, tb = pixels[x, y]
            br, bg, bb = pixels[x, y + 1] if y + 1 < height else (0, 0, 0)
            parts.append(
                f"\033[48;2;{tr};{tg};{tb}m"
                f"\033[38;2;{br};{bg};{bb}m▄"
            )
        lines.append("".join(parts) + "\033[0m")

    print("\n".join(lines))


def _solve_manual(image_path: Path) -> str:
    """Prompt the operator to read the CAPTCHA image and type the answer."""
    console.print(f"\n[bold yellow]CAPTCHA:[/bold yellow]")
    _display_image_in_terminal(image_path)

    answer = console.input("[bold cyan]Enter CAPTCHA text: [/bold cyan]").strip()

    try:
        image_path.unlink()
    except Exception:
        pass

    return answer
