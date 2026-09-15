# Loop notes — the agent's working memory

READ THIS FIRST every run. This file is NOT a log — run history lives in the
dashboard (`loop_run_events`). Write here ONLY when you found and fixed a real
bug. `notes_lint.py` enforces the rules (dedupe, 50-line cap, format) — the rules
below are not optional.

Notes format (ONE line per finding, newest first, no pipe characters inside a field):

`[YYYY-MM-DD] <region> | <area: tab/module/parser> | <symptom signature: how to detect> | <root cause> | <file/fix location> | <one-line lesson for the next run>`

Rules:
- A clean run (covered / no_data / bad_login) writes NOTHING here.
- Same portal + same symptom again → the lint bumps an `xN` counter instead of
  adding a line.
- Hard cap 50 lines; the lint moves the oldest overflow to LOOP_NOTES_ARCHIVE.md.
- Never put patient names or NIKs here — the lint strips them.

## Notes
[2026-09-01] poso | tab parser in patient_scraper.py _FORM_PARSE_BATCH_JS | symptom: real answers null or whole sections absent in output (double-selected selects read the placeholder; thead-less Biopsikososial table gone; headerless-box Psikologi/Keluhan dropped; real Tindakan form blocked; unchecked radios/checkboxes recorded as answers, e.g. IVA Status Kawin "JANDA", MTBS "OPV-3/IPV", covid kontak_jk "Laki-laki" for female patients) | root cause: parser took FIRST option[selected] where the browser keeps the LAST marked one; thead-less label:value tables matched no pass; boxes with empty headers fell through to section=null; a content-blind "Tindakan" blocklist dropped the real form; choice controls leaking raw value attrs in mixed buckets and any implicit first-option fallback record browser defaults, not patient data | fix: last option[selected] wins (never implicit-first — reverted after it phantom-filled kontak_jk); new Pass 2.5 for thead-less question tables; (no heading) synthetic section; Tindakan unskip only on positive evidence (dokter_nama_bpjs/perawat_nama in the heading box); mixed-bucket radios/checkboxes contribute only when checked, with the option label | lesson: parser value semantics must mirror browser DOM (last marked selected; unchecked = no answer); a blocklist unskip needs positive content evidence or it fails open; judge phantom values against the live markup, not the rendered default

## Known-empty
(one line per portal: `[YYYY-MM-DD] <region> | <date range checked> | <why>`)
(none yet)
