#!/usr/bin/env python3
"""format_stream.py — make the OpenCode session stream human-readable.

run.sh pipes `opencode run --format json --print-logs` through this before the
output reaches the worker, so the dashboard log, the Redis ring, and the
loop_run_events table all carry readable lines instead of raw JSON firehose.

Classification per line:
  * opencode INFO bookkeeping (step_start/tracking/stream/...)  -> dropped
  * opencode WARN/ERROR + permission lines                      -> kept, ANSI-stripped
  * JSON event, tool_use   -> one line: `-> bash: <cmd>` / `-> read: <path>` / ...
  * JSON event, text       -> the agent's own prose, printed verbatim
  * anything else          -> passed through (runner echoes, errors, LOOP_RESULT)

LOOP_RESULT:{...} always passes through untouched — the worker parses it.
"""
import json
import re
import sys

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_INFO_NOISE = re.compile(r"timestamp=\S+ level=INFO ")
_TOOL_VERB = {"read": "read", "grep": "grep", "glob": "list", "list": "list",
              "webfetch": "fetch"}


def _brief_bash(cmd: str, limit: int = 200) -> str:
    one = " ~ ".join(l.strip() for l in cmd.strip().splitlines() if l.strip())
    return one[:limit] + ("…" if len(one) > limit else "")


def _tool_line(tool: str, state: dict) -> str:
    inp = state.get("input") or {}
    if tool == "bash":
        return f"-> bash: {_brief_bash(inp.get('command', ''))}"
    if tool in ("read", "edit", "write"):
        return f"-> {tool}: {inp.get('filePath', '')}"
    if tool in _TOOL_VERB:
        q = inp.get("pattern") or inp.get("query") or inp.get("url") or ""
        return f"-> {_TOOL_VERB[tool]}: {str(q)[:120]}"
    if tool == "task":
        return f"-> task: {inp.get('description', '')}"
    return f"-> {tool}"


def format_line(raw: str) -> str | None:
    line = _ANSI.sub("", raw.rstrip("\n"))
    if not line.strip():
        return None
    if line.startswith("LOOP_RESULT:"):
        return line
    # reviewer.py also prints human-readable [reviewer] lines; the machine
    # line is redundant in the log.
    if line.startswith("REVIEW_RESULT:"):
        return None

    # opencode internal logs: keep warnings/errors, drop INFO chatter.
    if _INFO_NOISE.search(line):
        if " level=INFO " in line:
            return None
        return line

    # permission asks in plain text ("! permission requested: ...") are worth seeing.
    if line.lstrip().startswith("! "):
        return line.strip()

    if line.startswith("{"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return line
        typ = d.get("type")
        part = d.get("part") or {}
        if typ == "tool_use" or part.get("type") == "tool":
            tool = part.get("tool", "?")
            state = part.get("state") or {}
            status = state.get("status")
            base = _tool_line(tool, state)
            if status == "error":
                err = str(state.get("error", ""))[:160]
                return f"{base}  [ERROR: {err}]"
            return base
        if typ == "text" or part.get("type") == "text":
            text = part.get("text") or d.get("text") or ""
            if text.strip():
                return text.strip()
            return None
        # step_start / step_finish / session bookkeeping / everything else: drop
        return None
    return line


def main() -> int:
    for raw in sys.stdin:
        out = format_line(raw)
        if out is not None:
            print(out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
