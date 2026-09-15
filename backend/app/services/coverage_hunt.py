"""ASIK coverage hunt list: which ASIK questions still have no EPUS source.

Joins three static, in-repo sources — no DB, no network, no Settings import:

1. ``backend/app/data/asik_form_mapping.json`` — the canonical ASIK target
   (119 forms / 565 questions, per question: label + status_2026).
2. ``EPUS_BREADCRUMBS`` in ``epus_to_asik.py`` — the question labels the
   converter already maps, keyed by the form name it emits them under.
3. ``backend/app/data/coverage_ledger.json`` — HUMAN-edited documented
   sourceless / no-target / lead entries (the loop agent never writes it).

Per-question bucket, first match wins:

- ``deleted``           status_2026 == "Dihapus" — not a live question, skipped.
- ``mapped``            label present in this form's breadcrumb labels.
- ``documented_sourceless`` / ``not_live`` / ``asik_label_drift``
                        first matching ledger entry with that status.
- ``open``              everything else — the hunt list. A ledger entry with
                        status ``lead`` annotates an open question but never
                        removes it.

Consumers: ``loop-agent/run.sh`` (emits ``loop-agent/.hunt_list.md`` before the
agent session) and the dashboard fleet-progress endpoint (``build()``).

CLI:  cd backend && .venv/bin/python -m app.services.coverage_hunt --out <file>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

from app.services.epus_to_asik import EPUS_BREADCRUMBS

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MAPPING_PATH = _DATA_DIR / "asik_form_mapping.json"
LEDGER_PATH = _DATA_DIR / "coverage_ledger.json"

_DELETED = "Dihapus"


def _norm(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def _load_ledger() -> dict:
    data = json.loads(LEDGER_PATH.read_text())
    entries = []
    for e in data.get("entries", []):
        entries.append({
            "id": e.get("id", ""),
            "status": e.get("status", ""),
            "form_equals": {_norm(x) for x in e.get("form_name_equals", [])},
            "form_contains": [_norm(x) for x in e.get("form_name_contains", [])],
            "label_contains": [_norm(x) for x in e.get("question_label_contains", [])],
            "evidence": e.get("evidence", ""),
            "as_of": e.get("as_of", ""),
        })
    return {"updated": data.get("updated", ""), "entries": entries}


def _entry_matches(entry: dict, form_name: str, label: str) -> bool:
    if entry["form_equals"] and form_name not in entry["form_equals"]:
        return False
    if entry["form_contains"] and not any(t in form_name for t in entry["form_contains"]):
        return False
    if entry["label_contains"] and not any(t in label for t in entry["label_contains"]):
        return False
    return bool(entry["form_equals"] or entry["form_contains"] or entry["label_contains"])


def _breadcrumb_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for form_key, fmap in EPUS_BREADCRUMBS.items():
        labels = index.setdefault(_norm(form_key), set())
        labels.update(_norm(lbl) for lbl in fmap)
    return index


_BREADCRUMBS_BY_FORM = _breadcrumb_index()


def _form_breadcrumb_labels(paket_name: str, audit_title: str) -> set[str]:
    labels: set[str] = set()
    for key in (paket_name, audit_title):
        labels |= _BREADCRUMBS_BY_FORM.get(key, set())
    return labels


def build() -> dict:
    ledger = _load_ledger()
    forms = json.loads(MAPPING_PATH.read_text())["forms"]

    totals = {
        "mapped": 0, "documented_sourceless": 0, "not_live": 0,
        "asik_label_drift": 0, "deleted": 0, "open": 0,
    }
    open_by_form: list[dict] = []
    lead_hits: dict[str, dict] = {}

    for f in forms:
        paket = (f.get("paket_name") or "").strip()
        audit_title = (f.get("audit_form_title") or "").strip()
        form_name = _norm(paket or audit_title)
        crumb_labels = _form_breadcrumb_labels(_norm(paket), _norm(audit_title))

        open_questions: list[dict] = []
        for q in f.get("questions") or []:
            label = (q.get("label") or "").strip()
            if not label:
                continue
            if q.get("status_2026") == _DELETED:
                totals["deleted"] += 1
                continue
            norm_label = _norm(label)
            item = {
                "form": paket or audit_title,
                "frm_code": f.get("frm_code"),
                "label": label,
            }
            if norm_label in crumb_labels:
                totals["mapped"] += 1
                continue
            hit = next(
                (e for e in ledger["entries"] if _entry_matches(e, form_name, norm_label)),
                None,
            )
            if hit is None:
                totals["open"] += 1
                open_questions.append(item)
            elif hit["status"] == "lead":
                totals["open"] += 1
                open_questions.append(item)
                lead_hits.setdefault(hit["id"], {
                    "entry": hit, "forms": set(), "count": 0,
                })
                lead_hits[hit["id"]]["forms"].add(paket or audit_title)
                lead_hits[hit["id"]]["count"] += 1
            elif hit["status"] == "sourceless":
                totals["documented_sourceless"] += 1
            elif hit["status"] == "no_target":
                totals["not_live"] += 1
            elif hit["status"] == "asik_label_drift":
                totals["asik_label_drift"] += 1

        if open_questions:
            open_by_form.append({
                "form": paket or audit_title,
                "frm_code": f.get("frm_code"),
                "questions": open_questions,
            })

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "ledger_updated": ledger["updated"],
        "total_questions": sum(totals.values()),
        "totals": totals,
        "open_by_form": open_by_form,
        "leads": [
            {
                "id": v["entry"]["id"],
                "evidence": v["entry"]["evidence"],
                "as_of": v["entry"]["as_of"],
                "forms": sorted(v["forms"]),
                "open_questions": v["count"],
            }
            for v in sorted(lead_hits.values(), key=lambda x: x["entry"]["id"])
        ],
    }


def render_markdown(result: dict) -> str:
    t = result["totals"]
    lines = [
        "# ASIK coverage hunt list",
        "",
        f"Generated {result['generated_at']} from asik_form_mapping.json + "
        f"EPUS_BREADCRUMBS + coverage_ledger.json (ledger updated {result['ledger_updated']}).",
        "",
        f"{result['total_questions']} canonical questions | "
        f"{t['mapped']} mapped (source known) | {t['open']} OPEN — hunt these | "
        f"{t['documented_sourceless']} documented sourceless (skip) | "
        f"{t['not_live']} not live in ASIK (skip) | "
        f"{t['asik_label_drift']} ASIK-side label drift (skip, developer fixes) | "
        f"{t['deleted']} deleted from the 2026 form (skipped).",
        "",
        "Your coverage job this run: while you are live in the portal, look for an",
        "EPUS question — in a tab you already capture or a NEW tab/question — that",
        "answers one OPEN question below. Found one: map it additively in",
        "epus_to_asik.py, keep it on the hunt-list form it answers, and record it in",
        "coverage_findings. If a form family below has nothing on this portal, record",
        "ONE absent entry for the FORM (not per question) listing the tabs you checked.",
        "Questions NOT below but on no list: map them too and flag them off_list.",
        "",
        "## OPEN questions",
        "",
    ]
    for form in result["open_by_form"]:
        lines.append(f"### {form['form']}  ({form['frm_code']}, {len(form['questions'])} open)")
        lines.extend(f"- {q['label']}" for q in form["questions"])
        lines.append("")
    if result["leads"]:
        lines += ["## Known leads — open questions with a documented where-to-look", ""]
        for lead in result["leads"]:
            lines.append(f"- {lead['id']} ({lead['open_questions']} open questions, "
                         f"forms: {'; '.join(lead['forms'])})")
            lines.append(f"  {lead['evidence']} [as of {lead['as_of']}]")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit the ASIK coverage hunt list")
    ap.add_argument("--out", type=Path, default=None, help="write markdown here (default: stdout)")
    args = ap.parse_args()
    result = build()
    text = render_markdown(result)
    if args.out:
        args.out.write_text(text)
    else:
        sys.stdout.write(text)
    t = result["totals"]
    print(
        f"coverage: {result['total_questions']} questions | mapped {t['mapped']} | "
        f"open {t['open']} | sourceless {t['documented_sourceless']} | "
        f"not_live {t['not_live']} | label_drift {t['asik_label_drift']} | "
        f"deleted {t['deleted']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
