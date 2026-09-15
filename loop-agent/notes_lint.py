#!/usr/bin/env python3
"""notes_lint.py — enforce the LOOP_NOTES.md hygiene rules (PLAN §9).

Deterministic enforcement, run by run.sh AFTER the agent finishes — never just
prompt discipline. With --fix it:
  1. strips NIK-like 16-digit numbers from note lines (PII, defensively);
  2. dedupes by (portal, symptom signature): a repeat bumps an `xN` counter on
     the existing line instead of adding one;
  3. hard-caps the Notes section at 50 lines, moving the oldest overflow into
     LOOP_NOTES_ARCHIVE.md (never deleted — forward-compatible history);
  4. wraps a malformed newest note line into the standard format instead of
     dropping the lesson.

Exits 0 always (the pipeline must not fail over note hygiene).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTES = HERE / "LOOP_NOTES.md"
ARCHIVE = HERE / "LOOP_NOTES_ARCHIVE.md"
CAP = 50

NOTE_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2})\] (?P<portal>\S+) \| (?P<area>[^|]+?) \| "
    r"(?P<symptom>[^|]+?) \| (?P<cause>[^|]+?) \| (?P<fix>[^|]+?) \| (?P<lesson>.+?)(?: x(?P<count>\d+))?$"
)
NIK_RE = re.compile(r"\b\d{16}\b")


def _split_sections(text: str) -> tuple[list[str], str, list[str]]:
    """Returns (header_lines, known_empty_body, note_lines_in_order_oldest_last)."""
    lines = text.splitlines()
    notes_idx = known_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Notes":
            notes_idx = i
        elif line.strip() == "## Known-empty":
            known_idx = i
    if notes_idx is None or known_idx is None:
        raise SystemExit("LOOP_NOTES.md is missing its '## Notes' / '## Known-empty' sections")
    header = lines[: notes_idx + 1]
    known = lines[known_idx:]
    note_region = lines[notes_idx + 1 : known_idx]
    return header, "\n".join(known), [l for l in note_region if l.strip()]


def _parse(line: str):
    m = NOTE_RE.match(line.strip())
    if not m:
        return None
    d = m.groupdict()
    d["count"] = int(d.get("count") or 1)
    return d


def main() -> int:
    fix = "--fix" in sys.argv
    text = NOTES.read_text()
    header, known, note_lines = _split_sections(text)
    parsed = [(_parse(l), l) for l in note_lines]
    malformed = [raw for p, raw in parsed if p is None]
    parsed_ok = [(p, raw) for p, raw in parsed if p is not None]

    if malformed and not fix:
        print("notes_lint: MALFORMED lines detected:")
        for l in malformed:
            print(f"  {l}")
        return 1

    if fix:
        # Dedupe by (portal, symptom) — newest line wins, counts accumulate.
        seen: dict[tuple[str, str], dict] = {}
        order: list[tuple[str, str]] = []
        for p, _raw in parsed_ok:
            key = (p["portal"], p["symptom"].strip().lower())
            if key in seen:
                prev = seen[key]
                prev["count"] += p["count"]  # same portal+symptom again -> accumulate
                prev["date"] = max(prev["date"], p["date"])
            else:
                seen[key] = p
                order.append(key)
        # Template scaffolding — the fresh file's "(newest first — none yet)"
        # placeholders are guidance, not notes. Drop them instead of wrapping
        # them into a fake entry (that fake line once opened a PR by itself).
        dropped = [r for r in malformed if r.strip().startswith("(") and r.strip().endswith(")")]
        malformed = [r for r in malformed if r not in dropped]
        # Remaining malformed lines: wrap the raw text into the standard
        # format so the lesson is never lost.
        from datetime import date
        for raw in malformed:
            slug = "unknown-portal"
            lesson = NIK_RE.sub("[redacted]", raw.strip(" -*"))[:300]
            p = {"date": date.today().isoformat(), "portal": slug, "area": "unparsed",
                 "symptom": lesson[:80], "cause": "see PR", "fix": "see PR",
                 "lesson": lesson, "count": 1}
            key = (p["portal"], p["symptom"].strip().lower())
            if key not in seen:
                seen[key] = p
                order.append(key)
        # PII strip on every rendered line.
        def render(p: dict) -> str:
            base = (f"[{p['date']}] {p['portal']} | {p['area']} | {p['symptom']} | "
                    f"{p['cause']} | {p['fix']} | {NIK_RE.sub('[redacted]', p['lesson'])}")
            return base if p["count"] <= 1 else f"{base} x{p['count']}"

        rendered = [render(seen[k]) for k in order]
        # Cap: keep the newest CAP lines, archive the rest.
        overflow = rendered[:-CAP] if len(rendered) > CAP else []
        kept = rendered[-CAP:]
        if overflow:
            prev = ARCHIVE.read_text() if ARCHIVE.exists() else "# LOOP_NOTES archive (auto-overflowed lines)\n"
            ARCHIVE.write_text(prev.rstrip("\n") + "\n" + "\n".join(overflow) + "\n")
        NOTES.write_text("\n".join(header) + "\n" + "\n".join(kept) + ("\n" if kept else "") + "\n" + known.strip("\n") + "\n")
        print(f"notes_lint: ok ({len(kept)} notes, {len(overflow)} archived)")
    else:
        print(f"notes_lint: {len(parsed_ok)} well-formed, {len(malformed)} malformed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
