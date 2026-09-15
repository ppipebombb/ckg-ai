"""
Build backend/app/data/asik_sekolah_form_mapping.json from one or more
asik_sekolah scraper output JSONs.

The map is a committed CATALOG of every Pelayanan-oleh-Nakes question per form
per klaster — the canonical answer to "what questions exist in
ckg-pelayanan-sekolah" without re-scraping. Because the scraper runs with
include_blank_forms=True, even unsubmitted forms contribute their full question
schema, so one student per klaster is enough to capture that klaster's forms.

Keyed by the form's FRM code (pemeriksaan_code). For each form it accumulates the
layanan name, the set of klaster it appears in, and the union of question labels
(first-seen order preserved).

Usage:
  python build_form_map.py OUT.json INPUT1.json [INPUT2.json ...]
"""

import json
import sys
from pathlib import Path


def _iter_students(doc: dict):
    for school in doc.get("schools") or []:
        for cls in school.get("classes") or []:
            for bucket in (cls.get("tabs") or {}).values():
                for student in bucket or []:
                    yield student


def build(inputs: list[Path]) -> dict:
    forms: dict[str, dict] = {}
    n_students = 0
    for path in inputs:
        doc = json.loads(Path(path).read_text())
        for student in _iter_students(doc):
            n_students += 1
            klaster = (student.get("klaster_name") or "").strip() or "?"
            for f in student.get("pelayanan_nakes") or []:
                code = (f.get("pemeriksaan_code") or "").strip()
                if not code:
                    # fall back to layanan name when the scrape predates the
                    # pemeriksaan_code enhancement
                    code = (f.get("layanan") or "UNKNOWN").strip()
                slot = forms.setdefault(
                    code,
                    {
                        "layanan": f.get("layanan") or "",
                        "layanan_code": f.get("layanan_code"),
                        "klaster": [],
                        "questions": [],
                    },
                )
                if not slot["layanan"] and f.get("layanan"):
                    slot["layanan"] = f["layanan"]
                if klaster not in slot["klaster"]:
                    slot["klaster"].append(klaster)
                for q in (f.get("form_data") or {}):
                    if q.startswith("_"):
                        continue
                    if q not in slot["questions"]:
                        slot["questions"].append(q)
    # stable ordering by form code
    ordered = {k: forms[k] for k in sorted(forms)}
    return {
        "version": 1,
        "source": "/ckg-pelayanan-sekolah",
        "scrape_students": n_students,
        "total_forms": len(ordered),
        "forms": ordered,
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    out = Path(sys.argv[1])
    inputs = [Path(p) for p in sys.argv[2:]]
    doc = build(inputs)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(f"wrote {doc['total_forms']} forms from {doc['scrape_students']} students → {out}")


if __name__ == "__main__":
    main()
