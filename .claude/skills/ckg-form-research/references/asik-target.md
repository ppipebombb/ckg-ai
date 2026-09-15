# The ASIK target + the merge it feeds

What you're mapping *to*, and how the merge consumes the converter output.

## Target schema: `backend/app/data/asik_form_mapping.json`

The canonical list of ASIK forms + questions (the things to fill). Per form:
`frm_code`, `paket_name`, `layanan_name`, `audit_form_title`, `in_audit`, `questions[]`
(each with `label`, `live_kind`, `live_options`, `epus_source`, `covered_by_<source>`),
`demos_union` (which demographics see the form).

- **layanan vs paket:** `layanan_name` is the ASIK parent service; `paket_name` is the
  sub-card the UI groups inside it. The converter emits **paket-level** names; the merge
  regroups into pakets post-LLM via `app/data/paket_map.py`.
- **Adult slice only:** the converter targets adult+lansia. Pediatric/balita/anak/remaja
  forms are out of scope (filtered in `audit_coverage.py`).
- **`in_audit`** = the form was seen in a live DOM dump. `in_audit: False` forms are
  spec-only (from the Padanan Excel) and may not be live — verify before mapping
  (e.g. `Riwayat Hipertensi & Diabetes`, `Pemeriksaan Tekanan Darah` are spec-only;
  the live forms put those questions inside `Tekanan Darah` / `Gula Darah`).

### Rebuilding it

`backend/app/data/build_mapping.py` fuses three inputs → the json:
1. `Metadata Program Rutin.xlsx` sheet `Padanan Paket Odoo` (FRM/PPM codes + demographics),
2. `testing-epus-asik/asik_audit_*/` live SurveyJS DOM dumps (labels/options/kind),
3. `<source>_BREADCRUMBS` (the EPUS source path per field).

It's a manual run (needs the xlsx). For routine drift checks you don't rebuild — you run
`capture_target.py` against a fresh scraper dump and read the diff. Patch a single
renamed form in the json directly (as done for `SKILAS Malnutrisi` on 2026-05-29).

## How the merge consumes the converter (`backend/app/tasks/merge.py`)

The merge is **backend-deterministic**; the LLM is a thin conflict-annotator.

1. LLM gets `(converted, raw ASIK)` and emits items **only for both-filled fields** it
   must judge (small output — keeps it fast + cheap, gpt-oss-safe).
2. Backend post-processors own everything else, in order:
   - `_slugify_section_keys` — LLM emits form NAMES; backend slugifies.
   - `_complete_source_fields` — adds every one-sided/empty field from `converted ∪ ASIK`,
     overwrites raw values from source, **prunes anything not in source** (kills
     hallucination + orphan/mis-named sections).
   - `_rebuild_identitas` — identity built deterministically from source + `detail_data`.
   - `_normalize_status_flags` — status from values: one-sided/equal → not conflict;
     identity differ → "Makna Sama"; clinical differ → conflict. **EPUS/source wins.**
   - breadcrumb backfill, reasoning templates, conditional-child prune, paket grouping.

Net properties you can rely on:
- **Field presence + values + status are deterministic** (model-independent — all 3
  models produce byte-identical merges).
- **Zero hallucination** (the prune drops any value not in a source).
- **Source (EPUS) wins** every conflict; ASIK fills gaps.

So merge quality ≈ converter quality. Improving data = improving `<source>_to_asik.py`,
not the prompt/model. That's why this skill exists.

## After changing a converter

Backend changes need a **Celery worker restart** to take effect; existing merged
patients need a re-merge with `force_remerge` to pick up new logic.
