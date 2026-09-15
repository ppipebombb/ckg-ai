"""Loader for the frontend-dashboard explainer chatbot's knowledge packs.

The chatbot's ENTIRE knowledge is the markdown under ``settings.CHATBOT_DIR``
(the repo ``chatbot/`` folder, baked into the image by the Dockerfile's
``COPY chatbot /app/chatbot``): ``system.md`` guardrails, ``manifest.json``
page→packs mapping, and ``knowledge/*.md`` packs.

By construction the only thing this module can ever put into an LLM prompt is
our own versioned markdown — no patient data is read here.

Files are cached in-process keyed by path with an mtime check: steady state does
no disk IO, but a bind-mounted edit (ops hot-patch between releases) is picked up
on its next read without a restart.
"""
import json
import os

from app.config import settings

# Unknown page keys fall back to this pack set (manifest must define it).
_FALLBACK_PAGE = "common"

# path -> (mtime, text). Module-level so the cache survives across requests.
_text_cache: dict[str, tuple[float, str]] = {}


class ChatbotKnowledgeUnavailable(RuntimeError):
    """A required knowledge file is missing on disk — a deploy bug (the
    Dockerfile COPY didn't ship the folder, or a manifest entry points at a file
    that doesn't exist). The route turns this into a 503 so it fails loud rather
    than answering from an empty knowledge base."""


def _read_text(path: str) -> str:
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        raise ChatbotKnowledgeUnavailable(f"missing chatbot file: {path}") from exc
    cached = _text_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    _text_cache[path] = (mtime, text)
    return text


def _manifest_pages() -> dict[str, list[str]]:
    raw = _read_text(os.path.join(settings.CHATBOT_DIR, "manifest.json"))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatbotKnowledgeUnavailable("manifest.json is not valid JSON") from exc
    pages = data.get("pages")
    if not isinstance(pages, dict):
        raise ChatbotKnowledgeUnavailable("manifest.json has no 'pages' object")
    return pages


def _packs_for(page: str) -> list[str]:
    pages = _manifest_pages()
    # Unknown page → fall back to the 'common' pack set.
    names = pages.get(page) or pages.get(_FALLBACK_PAGE)
    if not names:
        raise ChatbotKnowledgeUnavailable(
            f"manifest has no packs for page '{page}' or fallback '{_FALLBACK_PAGE}'"
        )
    return names


def build_system_prompt(page: str) -> str:
    """Compose the chatbot system message: ``system.md`` guardrails followed by
    the knowledge packs the manifest maps to ``page`` (unknown page → 'common').

    Raises :class:`ChatbotKnowledgeUnavailable` if ``system.md``, the manifest,
    or any manifest-listed pack file is missing — i.e. fail loud on a broken
    deploy instead of silently answering with no knowledge.
    """
    system = _read_text(os.path.join(settings.CHATBOT_DIR, "system.md"))
    pack_texts = [
        _read_text(os.path.join(settings.CHATBOT_DIR, "knowledge", name))
        for name in _packs_for(page)
    ]
    return system + "\n\n# BASIS PENGETAHUAN\n" + "\n\n".join(pack_texts)
