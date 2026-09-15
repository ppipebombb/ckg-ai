# Research Status — sources → ASIK

**Read this first.** Living index of what's mapped. Update it at the end of every
research run (skill step 6).

## Full research pass (canonical procedure — the run prompt points HERE)

**Stable prompt (copy-paste, never needs changing):**

> `/ckg-form-research` Run the full research pass exactly as documented in
> `RESEARCH_STATUS.md` → "Full research pass" section, in order. Report only
> genuinely-NEW findings per the rules there, and update `RESEARCH_STATUS.md`
> (incl. Regions) if anything changed.

**Steps — EDIT THESE when the skill is refined; the prompt above stays the same.**
(This is the concrete EPUS routine; `SKILL.md` has the general methodology + how to add a
new source.)

> **Execution is owned by `run_full_pass.py`, NOT by your judgment.** A prior run skipped the
> captcha-gated live-drift step and still reported a clean "no drift" — the offline scripts
> can't contradict a step that never ran. The runner now executes EVERY step in order,
> captures each one's output + exit code, and prints a COMPLETENESS MANIFEST + GATE verdict.
> **You do steps 1 and 4 only; the runner does 2–3.** Do NOT run the individual scripts
> piecemeal, and do NOT decide a step is unnecessary — that is exactly the seam the runner closes.

1. **Baseline.** Read this whole file first — Target, Regions, Sources, known gaps /
   ruled-out. Don't re-discover what's already recorded.
2. **Run the deterministic pass — one command, nothing to skip:**
   ```
   backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/run_full_pass.py --source epus --auto-asik
   ```
   It runs, unconditionally and in order: `audit_regions` → `verify_converter --all-regions
   --n 6 --models oss` → `audit_coverage` → `audit_uncovered` → **`audit_source_completeness`
   (live, SCRAPER-vs-site)** → **live ASIK drift**. `audit_source_completeness` is the check
   added 2026-06-05 after the jaksel tab miss: every other step audits the CONVERTER against
   the DB, so none could see that the SCRAPER itself was dropping live tabs on one region. It
   logs into each EPUS region (read-only, no captcha), runs the REAL production discovery, and
   force-probes for any module/section/read the scraper misses — exit 1 (MUST-FIX) on a real
   gap, 3 (TRIAGE) on a new section/loader to review. With
   `--auto-asik` the runner performs a REAL live scrape itself: enables the DB vision captcha
   key (`captcha_config.py apply` → the scraper auto-solves, no human/agent vision needed),
   scrapes ASIK **headless** for the latest date with completed (`Selesai`) screenings (walking
   back up to `--asik-lookback` days, default 3), and runs `capture_target` on that fresh dump.
   It prints the manifest, GATE, and a one-line **SUMMARY**, exiting: **0 = COMPLETE/no-regression
   · 1 = MUST-FIX regression · 2 = INCOMPLETE (a required step did not run).**
   - **Always pass `--auto-asik`** for the daily pass — that is what makes the live-drift check
     real. (Without it the runner falls back to the newest existing dump and flags staleness.)
   - If no vision captcha key is configured, or no recent date has completed screenings, the
     runner marks `live_asik_drift NOT_RUN` → GATE **INCOMPLETE**. That is the honest state —
     ASIK drift was not checked. Do not paper over it; surface it.
   - Manual alternative: produce a dump yourself and pass `--asik-dump <path>` instead.
3. **(runner-owned — do not re-run the checks piecemeal.)**
4. **Triage + report + persist.** Read the runner's manifest, then:
   - **Echo the `GATE:` line VERBATIM** at the top of your report. If GATE is **INCOMPLETE**,
     report the pass as INCOMPLETE and NEVER claim a result for a `NOT_RUN` step (e.g. do not
     write "no ASIK drift" when `live_asik_drift` did not run).
   - **MUST-FIX** (GATE exit 1) = `audit_regions` region FAIL or `verify_converter` regression
     → fix converter/schema, **restart the Celery worker + re-merge affected patients
     (`force_remerge`)**, then re-run the runner to GATE: COMPLETE.
   - **TRIAGE every `TRIAGE-REQUIRED` item the runner listed — in a TABLE, not a sentence.**
     A report that is only "GATE: COMPLETE" (or "no new findings") with no per-finding reasoning
     is **INVALID** — redo it. For EACH flagged item (every `audit_coverage` name/label drift,
     and each high-fill `audit_uncovered` row you reviewed), produce one row:

     | finding (step + the exact label/path) | NEW / KNOWN | evidence you actually checked (cite a file:line, a breadcrumb, or the baseline entry) | decision |

     Hard rules:
     - A **KNOWN** verdict MUST cite where it's already recorded. **If you cannot cite it, it is
       NEW** — investigate, don't default to KNOWN to make the run quiet.
     - **There is NO accepted-drift allowlist.** Every name/label drift `audit_coverage` flags is
       a BUG to FIX, never to "record as known." Fix it at the source: if the breadcrumb/label in
       `epus_to_asik.py` is wrong, correct it there; if the **mapping** drifted from live (e.g. a
       stray double space the Padanan Excel feeds into `asik_form_mapping.json`, while live ASIK
       uses a single space), confirm against a FRESH live dump and patch the mapping to match live.
       **NEVER silence a drift by editing THIS file to declare it "known"** — that hides the bug
       and corrupts the baseline (a weak model did exactly that on 2026-06-05: it labelled a NEW
       drift NEW, then "resolved" it by adding it to a known list here). Re-run until 0 drift.
     - `audit_uncovered`: walk the top rows (BOTH `fields` and `tables`); mark each
       already-mapped / not-a-target-because-X / NEW-gap.
   - For any **NEW** finding: FIX it (extend the converter / correct the label), note the
     **Celery worker restart + `force_remerge`** requirement, and **re-run the runner** until the
     GATE is COMPLETE with that finding resolved. Never report a NEW finding and leave it open.
   - Report ONLY genuinely-NEW findings (ignore anything already in "known gaps / ruled-out /
     Regions"). Update this file (incl. Regions) + `EPUS_TO_ASIK_VERIFICATION.md` **only if
     something changed**.
   - **End your report with:** the runner's `SUMMARY` block (verbatim) → the triage table above →
     a final line `changed: <files>` or `no changes — <why, referencing the table>`. Always
     include all three, even on a clean run — this is the at-a-glance record for daily monitoring.

## Target: ASIK CKG form

- Schema: `backend/app/data/asik_form_mapping.json` (115 forms). The committed
  converter target is **adult+lansia + a partial pediatric (under-18) battery**
  (shipped 2026-06-02). ~23% of EPUS patients are under-18; the fillable pediatric
  forms (growth / vitals / glucose / dental / TB-cough) are now emitted — see
  **Pediatric (under-18)** below. (An earlier "no kid data" claim was wrong —
  measured, not guessed, per `profile_source.py`.)
- Live schema last verified: **2026-06-03** (Pekayon Jaya, 4-patient `selesai`-tab full
  `include_blank_forms` + `pelayanan_nakes_only=false` dump; `capture_target` live forms=49).
  **0 new live forms; 0 new or changed questions in any EPUS-sourced clinical form** (every
  live Q is a subset of the committed mapping). The `capture_target` "new questions" in
  sourceless self-assessment/lansia forms were a **mapping-side double-space typo** — the Padanan
  Excel feeds stray double spaces into `asik_form_mapping.json` while live ASIK uses single spaces.
  These are BUGS to fix in the mapping, not "known drift." **Fixed 2026-06-05** (each verified
  single in a live dump): Kesehatan Jiwa ×2 + Mini-Cog "Mintalah…" (Kesehatan Jiwa coverage 2/6 → 4/6).
  **Still-to-fix** (same typo class, absent from the latest `selesai` dump — verify on a fuller
  scrape, do NOT allowlist): Talasemia ×2, Fungsi Ginjal (Kreatinin/Ureum), WBP, Skrining SHK/G6PD,
  Mini-Cog "Katakan…".
- Prior (2026-06-02): same result on a 6-patient dump.
- Prior (2026-05-29): one drift fixed — screening form renamed
  `Skrining Malnutrisi - Lansia` → **`SKILAS Malnutrisi`** (mapping json patched to live).
- Rebuild from Padanan Excel: `backend/app/data/build_mapping.py` (manual, needs the xlsx).

## Regions — EPUS is multi-instance (verify per region)

EPUS is not one portal but a **family of per-region instances** (`<region>.epuskesmas.id`),
each with its own login and *potentially its own data shape*. The converter
(`epus_to_asik.py`) was authored against **kotabekasi** (the smallest region). "Test all
EPUS" means every region **explicitly** — a region-blind random sample is dominated by the
busiest region and hides a smaller region's quirks.

**Regions in the DB (measured 2026-06-03, `audit_regions.py`):**

| Puskesmas | Region (`epus_url`) | EPUS rows | matched |
|---|---|---|---|
| Tebet | jaksel.epuskesmas.id | 86,878 | 3,147 |
| Kota Tangerang (Cipondoh) | kotatangerang.epuskesmas.id | 25,171 | 1,323 |
| Pekayon Jaya | kotabekasi.epuskesmas.id (← converter's home) | 18,936 | 2,046 |
| Kabupaten Poso (Tonusu) | poso.epuskesmas.id | 0 (see UA/WAF note) | 0 |

**⚠️ Poso (poso.epuskesmas.id) — WAF blocks the scraper User-Agent (found + fixed 2026-08-19).**
Poso EPUS scrapes returned `scraped=133, inserted=0, updated=0`, notes "skipped 133: missing NIK"
for EVERY record (ASIK for the same puskesmas inserted fine). Root cause: Poso's portal has a WAF
rule that **403s any request whose `User-Agent` contains the token `epus-v2/scraper`** — the exact
suffix that was on `patient_scraper._USER_AGENT`. The DataTables **list** is fetched through the
Playwright browser (real Chrome UA) so it returned 133 rows; the per-patient **deep-scrape**
(`/pelayanan/show/{id}`, `/anamnesa/create/{id}`, tab pages) uses `httpx` with `_USER_AGENT` → 403
on every fetch → `data_pasien` empty → backend `_extract_patients` drops all rows as "missing NIK"
(fast 29s "scrape" = fetches failing, no real deep-scrape). Verified live 2026-08-19: scraper UA
→ 403; clean Chrome UA / `Mozilla/5.0` / empty UA → 200 with `table_pasien` (NIK present). The
other 3 regions accept any UA, so they were never affected. **Fix:** dropped the `epus-v2/scraper`
token from `_USER_AGENT` (clean browser UA). `scrapers/**` change → needs a **worker image rebuild
+ re-scrape Poso** to take effect; no converter/merge change. Poso is a **multi-puskesmas account**
(login lands on `/home/selectpuskesmas`; POST `/home/selectpuskesmas` with `puskesmas[id]` selects
one, e.g. Tonusu `P7204030202PU003`) — but this is NOT required for scraping: the session has a
default active puskesmas and show pages return data without an explicit selection. No converter
audit was run for Poso yet (nothing was ever ingested); do a normal source pass after the re-scrape.

**Shape findings:**
- Top-level keys identical across all 3.
- ⚠️ **CORRECTION (2026-06-05): jaksel's Anamnesa tab bar UNDER-LISTS modules — the prior
  "all converter-critical tabs present in every region" claim was a sampling artifact.** Live
  test (6 jaksel patients, 04-06-2026): jaksel's new-build bar lists only ~15 of ~33 modules;
  `GET /{module}/create/{pid}` serves the other ~17 WITH DATA (covid19, tbparu, mata,
  konselinghiv, periksaiva/ims, pkpr, psikologi, kohort, mtbsv2, …). So the scraper's
  bar-only discovery silently dropped them for jaksel — **including the converter-consumed
  `Konseling HIV` / `TB Paru` / `PKPR` tabs, so jaksel's HIV/TB/PKPR conversions were EMPTY**
  whenever the patient had that diagnosis flag. **Scraper FIXED** (`patient_scraper.
  _merge_known_modules`): bar discovery is now UNIONED with a `_KNOWN_MODULES` safety net →
  all 3 regions scrape ~33–34 tabs; verified 0 error-stubs / 0 writes. **Converter unchanged**
  (it already reads these tabs) but jaksel coverage IMPROVES once patients are re-scraped.
  **Re-verify after the full rescrape**: `verify_converter --all-regions` + spot-check jaksel
  HIV/TB/PKPR fields now fill. (`scrapers/**` change → no worker restart; but the merge benefit
  needs the re-scrape, then `force_remerge` for affected jaksel patients.)
  **Guarded going forward by `audit_source_completeness.py` (new step 5 of `run_full_pass.py`)** —
  it logs into each region live and force-probes for any module/section/read the scraper misses.
  Verified GREEN 2026-06-05 (3/3 regions, 0 MUST-FIX / 0 TRIAGE) after the union fix.
- The exact set of region-varying tab names is **sample-dependent** (it tracks which
  optional-service tabs the sampled patients happen to carry): the 2026-06-03 re-run saw only
  `Alkes` + `Pemantauan Anestesi & Bedah` vary; an earlier sample saw 6 (`Alkes`, `Haji`,
  `Odontogram`, `PAL`, `Pemantauan Anestesi & Bedah`, `Tumbuh Kembang Anak`). With the
  known-module union the scraper no longer depends on this — every known module is fetched
  regardless of which the bar lists.
- **`data_pasien` key renames in jaksel (all handled — re-verified 2026-06-03):** beyond
  birthplace/DOB, the 2026-06-03 audit surfaced a fuller jaksel-only key set vs the
  slash-style regions: `Nama`, `No. HP`, `Tanggal`, `Nama KK`, `Tempat & Tgl Lahir`, plus
  `ID Encounter Satu Sehat` / `ID Pelayanan` / `Jenis Kepesertaan BPJS`. The converter-critical
  ones are covered: `_map_identitas` reads `Nama Pasien` **or** `Nama`, and birthplace/DOB via
  `Tempat/Tgl Lahir` **or** `Tempat & Tgl Lahir` (comma vs slash; it anchors the parse on the
  trailing `dd-mm-yyyy`, so separator/region-agnostic). The rest (phone, visit date, KK name,
  IDs, BPJS) have **no ASIK target**. jaksel identitas → **6.00/6** (Tempat 100%, Tgl 100%).
  - *Fix history:* before the `Tempat & Tgl Lahir` read was added (2026-06-03), ~65% of jaksel
    patients silently lost `Tempat Lahir` + `Tanggal Lahir` (identitas fill 4.1 vs 5.8). That
    `_map_identitas` change is in the working tree (**uncommitted** as of this run) → it needs a
    **worker restart + re-merge of jaksel patients** with `force_remerge` to take effect.

**Extraction parity (adults 18–59, age-controlled):** after the identitas fix, all 3 regions
fill within parity (re-verified 2026-06-03: `audit_regions` extraction ratio 94%/94%/100% for
jaksel/kotatangerang/kotabekasi, no form differs >2.0 across regions; `verify_converter
--all-regions --n 6 --models oss` PASS for every region — 0 hallucination / complete / valid
shape); core clinical forms are byte-identical (`Tekanan Darah` 3.0/3.0/3.0, `Pemeriksaan Gula
Darah` ~1.1 everywhere). No evidence of converter shape-drift on mapped fields. **Lesson: control for age band when comparing regions** — a raw avg-filled gap is
mostly age mix (jaksel skews younger, fewer lansia), not a converter weakness.

**Note: the OSS model endpoint (`openai/gpt-oss-20b`) returned 404/502 during the 2026-06-03 evening re-check** — the cross-model divergence check (`--models oss`) fails. The converter itself is clean: `verify_converter --all-regions --n 2 --models gpt` and `--models deepseek` both PASS for all 3 regions. Use `--models gpt` (or `deepseek`) until OSS is restored.

**Re-check:**
```bash
# cross-region shape diff + extraction parity + uncovered-per-region (exit≠0 if a region under-extracts)
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_regions.py --source epus
# full 0-hallucination / complete / shape gate, run once PER region:
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/verify_converter.py --source epus --all-regions --n 6 --models gpt
# scope any single-region check (audit_coverage / audit_uncovered / profile_source):
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_uncovered.py --source epus --region jaksel
```

## Sources

| Source | Converter | Coverage | Last audited | Status |
|---|---|---|---|---|
| **EPUS** (ePuskesmas) | `app/services/epus_to_asik.py` | adult clinical battery + dental + **under-18 battery** (growth/vitals/glucose/dental/TB-cough) + **Laboratorium-tab labs** (Albumin Urin/Trombosit/Hb, added 2026-06-03); lansia-instrument/skin + pediatric newborn/immunization/development are EPUS-less shells | 2026-06-03 | ✅ shipped, 0 name/label drift, 0 hallucination across 3 regions |

### EPUS — known gaps (EPUS has no source for these; emitted as shells or null)

- Lansia instruments (SKILAS Mobilisasi/Kognitif/Depresi/Malnutrisi + their Lanjutan
  forms) — geriatric tests EPUS doesn't run.
- ~~Lab panels beyond EPUS PTM (HbA1C, Trombosit…); adult Trombosit genuinely sourceless.~~
  **WRONG — corrected 2026-06-03.** This was a `fields`-only blind spot: the **Laboratorium
  tab's result GRID** (`tabs.Laboratorium.tables["Ubah Data Laboratorium"]`) carries the
  real lab results and was never read (the converter + both audits walked only `fields`).
  Now mapped: **Microalbuminuria → Konsentrasi Albumin Urin** (Skrining Kerusakan Ginjal),
  **Trombosit → Pemeriksaan Trombosit** (Fibrosis/Sirosis Hati), **Hb → Kadar Hemoglobin**
  (Calon Pengantin Perempuan) — all 3 verified across Cipondoh/Tebet/Pekayon, 0 hallucination.
  Still sourceless in the lab tab: **Konsentrasi Kreatinin Urin** (EPUS has only *serum*
  Kreatinin, from PTM) and **UACR**. Other lab tests (urinalysis, full hematology, serology
  HbsAg) are uncovered candidates — see the 2026-06-03 uncovered-source note.
- Frambusia/Kusta/Skabies, Kesehatan Jiwa (PHQ-2/GAD-2 — no EPUS source),
  Hati risk questionnaire, Faktor Risiko HIV&Sifilis (`in_audit=False`, not live;
  asks risk-behavior not the EPUS IMS `Tanda Klinis` signs), Prediksi Jantung/Stroke.
- `Faktor Risiko dan Skrining X-Ray TB` — only the cough Q mapped (BB-turun / demam /
  keringat-malam are candidates if EPUS Anamnesa exposes them — unverified).
- Cervical: `Kanker Leher Rahim` gating Q emitted as shell (no EPUS sexual-activity field).

### EPUS — verified correct (don't "fix")

- HT/DM parent radios live in `Tekanan Darah` / `Pemeriksaan Gula Darah` forms (the
  `Riwayat Hipertensi & Diabetes` / `Pemeriksaan Tekanan Darah` / `Gula Darah Lanjutan`
  forms in the mapping are `in_audit=False` spec-only alternates — not live).
- Field labels byte-match live ASIK; field placement confirmed against the live dump.
- **Dental** (added 2026-05-29): `Skrining Karies dan Gigi Hilang` + `Skrining Penyakit
  Periodontal` are sourced from `Anamnesa > Pemeriksaan Dasar Gigi` (~5% of patients).
  `Gigi Goyang` ← `Goyang` (1:1); `Gigi karies` ← `Status Karies`/`Karies Gigi`;
  `Penyakit Periodontal` ← `Warna Gusi`/`Pem-bengkakan`. `Gigi hilang/dicabut` has no
  source. **Do NOT use the EPUS Odontogram** — its `Diastema`/`Gigi Anomali` are constant
  `"Ada"` defaults (123/123), i.e. noise.
- **Cervical/breast (IVA/SADANIS) IS mapped — `audit_coverage` "MISSING" here is a sampling
  false-positive, don't chase it** (clarified 2026-06-03). `_map_iva_sadanis` emits
  `Pemeriksaan Inspekulo dan IVA` (Inspekulo Normal/Curiga-kanker + IVA Negatif/Positif) and
  `Skrining Kanker Payudara` (`Pemeriksaan yang dilakukan` = `SADANIS`), gated on **perempuan,
  age ≥30, with populated `PTM > Pemeriksaan IVA dan Sadanis > Hasil IVA` / `Hasil Sanadis`**.
  Those results are rare: a 3000-patient scan found only 6 with data, but all 5 eligible women
  emitted both forms correctly (Inspekulo=Normal, IVA=Negatif, Payudara=SADANIS) and the lone
  24-yo was correctly suppressed by the age gate. A random `audit_coverage` n≈120 almost never
  includes an IVA/SADANIS case → the forms don't emit in that sample → they show as
  `[MISSING]`. This is **not** a coverage gap. (The `Kanker Leher Rahim` *gating* Q stays a
  shell — no EPUS sexual-activity field.)

### EPUS — uncovered-source audit (2026-06-03 re-sweep: NOW walks `tables`)

⚠ The 2026-05-29 sweep below missed an entire data class: `audit_uncovered.py` (and
`profile_source.py`) only walked `tabs.<T>.fields`, never `tabs.<T>.tables` — so the
**Laboratorium result grid** was invisible and Trombosit/Albumin-Urin/Hb were wrongly
called sourceless. Both scripts now walk `fields` + `tables` (SKILL.md Golden rule 7).
Re-sweep findings (lab tab, all 3 regions):
- **Mapped now:** Microalbuminuria→Albumin Urin, Trombosit→Pemeriksaan Trombosit,
  Hb→Kadar Hemoglobin (see known-gaps correction above).
- **Already covered via PTM (don't double-map):** lab `Glukosa Puasa/Kolesterol/HDL/LDL/
  Trigliserida/SGOT/Kreatinin/Ureum/HbA1c` duplicate the PTM values the converter reads.
- **Uncovered candidates (no clean adult ASIK target / needs value coercion — left for a
  future pass):** urinalysis (`Protein/Glukosa Urine`), full hematology (`Eritrosit/
  Hematokrit/Lekosit/MCV/MCH/MCHC`), serology `HbsAg` (would need rapid-test coercion to
  feed `Pemeriksaan Hepatitis`). Region spelling varies — match leaves exactly.

### EPUS — show-page sidebar fields `riwayat_pasien` / `alergi` / `data_skrining` (2026-06-05): scraped, NO ASIK target

The patient scraper now also captures three left-sidebar tables off `/pelayanan/show`
(`scrapers/epus/patient_scraper.py` → output keys `riwayat_pasien`, `alergi`, `data_skrining`;
region-robust — see memory `project_epus_portal_builds`). Measured against the full target
schema (565 questions / 119 forms): **none has an ASIK CKG target — nothing to map into the
converter.** Stored in the encrypted `scraped_epus_data` blob (display/audit/future use), but
deliberately NOT wired into `epus_to_asik.py`:

- **`alergi`** (Obat/Makanan/Udara/Umum → "Tidak Ada"): ASIK has **0 allergy questions**
  (grep of all 565 question labels). No target — full stop.
- **`riwayat_pasien`** (Riwayat Penyakit Sekarang/Dulu/Keluarga, free-text): the only ASIK
  "riwayat" questions are *structured screening* items (TB contact, smoking, family
  cancer/talasemia, immunization records) — each already sourced from STRUCTURED EPUS fields
  (PTM Faktor Risiko/PUMA, cough logic, `Riwayat PTM pada Keluarga` for cancer). Re-deriving
  them from this free-text narrative ("…DM tidak ada, asma tidak ada, TB tidak ada…") would be
  hallucination-prone NLP for zero coverage gain. Consistent with the ruled-out family-history
  + Keluhan-Utama notes below.
- **`data_skrining`** (legacy screening index: type + date + detail_href): a historical
  *index*, not a clinical answer to any ASIK question. Current-visit screening detail is
  already covered via the module tabs; past-visit detail has no ASIK target (and the generic
  `/skrining/create/{id}` detail pages 500 anyway).

No converter change ⇒ no new gate run needed; the 2026-06-05 converter gates stand.

### EPUS — uncovered-source audit (2026-05-29, `audit_uncovered.py`, `fields`-only — superseded)

Swept all populated EPUS leaf-fields (~600) vs the converter. **Converter is complete for
the live adult battery** — every uncovered field is noise or has no live adult target.
Ruled-out candidates (don't re-investigate; no ASIK target exists):

- **Family history (non-cancer)** `Riwayat PTM pada Keluarga > DM/HT/Jantung/Stroke/Asma/
  Kolesterol/Benjolan Payudara` @90% — only **cancer** family-hx is asked by adult ASIK
  (Kanker Paru/Usus), already covered. The rest has no target.
- **Diet/behavior** `Faktor Risiko > Gula/Garam/Lemak Berlebihan`, `Kurang Makan Buah dan
  Sayur`, `Konsumsi Alkohol` @90% — no live adult perilaku/diet form.
- **IMS clinical signs** `Periksa Fisik > Tanda Klinis/Diagnosis (DTV/Ulkus/Jengger/Bubo)`
  @60% — target `Faktor Risiko HIV dan Sifilis` is `in_audit=False`/not live and asks
  risk-behavior, not signs.
- **Vitals/anthro ASIK skips** `Detak Nadi`, `Nafas`, `Suhu`, `MAP`, `IMT`/`Hasil IMT`
  (ASIK computes IMT server-side from BB/TB we already send).
- **Redundant fallbacks** (IVA-module BB/TB, `Riwayat Identitas > status_kawin`,
  `Tekanan Darah & IMT > IMT`) — primary source already covered.
- **General physical-exam narratives** `Keadaan Fisik > Pemeriksaan Telinga / Mata /
  Mulut dan Bibir / Kulit > Inspeksi/Palpasi` (88–91%, checked 2026-06-02) — free-text
  normal/abnormal blurbs. The live Telinga/Mata form is already sourced from the specific
  PTM `Gangguan Pendengaran/Penglihatan` sub-blocks (4/5 live Q exactly), dental from
  `Pemeriksaan Dasar Gigi`; the narratives are less specific and add nothing.
- **`data_pasien > No Telp / HP`** (70%, checked 2026-06-02) — ASIK has **no**
  phone-number question in any adult form, so there is no target.
- **`Anamnesa > Keluhan Utama` / `Lama Sakit`** (100%) — not standalone targets; already
  consumed indirectly by the TB cough-duration logic (`_cough_duration`).

Also added `Pemeriksaan EKG` (the one genuinely-new live question) to `Hasil Pemeriksaan -
Skrining Jantung` in the mapping json — no EPUS source, tracked so the tally reads 1/2.
The other `capture_target` "new questions" (Kesehatan Jiwa, Barthel, lansia depresi/cog,
and — re-confirmed 2026-06-02 — `Tingkat Aktivitas Fisik (sedang dan berat)` + `SKILAS
Pemeriksaan Gejala Depresi - Lansia`) were **placeholder/whitespace label drift**, not
absent — all are sourceless self-assessment/lansia forms (EPUS has no GPAQ/GDS/Barthel
source), so this is mapping-label cosmetics only — fix on the next Padanan rebuild, not a
converter change. (`audit_coverage.py` reports 0 converter name/label drift independently.)

> `covered_by_converter`/`epus_source` in `asik_form_mapping.json` derive from
> `EPUS_BREADCRUMBS` (see `build_mapping.py`); rerun `build_mapping.py` (needs the Padanan
> Excel) to refresh them after a breadcrumb edit. The live `audit_coverage.py` tally is the
> authoritative coverage signal in the meantime.

## How to re-check (commands)

> À-la-carte commands for targeted re-checks. For the full ordered run, use the
> **Full research pass** procedure at the top of this file.

```bash
# drift in the ASIK target (after a fresh scraper dump)
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/capture_target.py --dump <dump.json>
# converter coverage + name/label drift (exit 0 = clean)
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_coverage.py --source epus
# SOURCE-side: populated source fields the converter does NOT consume (candidates)
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_uncovered.py --source epus
# POPULATION + per-band tab reality (shell detection) — run BEFORE scoping any slice
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/profile_source.py --source epus --sample 3000
# end-to-end quality (0 hallucination, complete, consistent) — add --all-regions to gate EVERY region
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/verify_converter.py --source epus --n 10 --models deepseek,gpt,oss
# CROSS-REGION shape diff + extraction parity (EPUS is multi-instance — see Regions section)
backend/.venv/bin/python .claude/skills/ckg-form-research/scripts/audit_regions.py --source epus
```

## Pediatric (under-18) — PARTIALLY SHIPPED (2026-06-02)

**Correcting an earlier assumption.** "Pediatric is out of scope because EPUS has no kid
data" was asserted without checking and is **false**. `profile_source.py --source epus`
shows **~23% of EPUS patients are under 18** (≈14.6k unique people: ~1.4k bayi <1, ~4k
balita, ~5.5k anak, ~3.8k remaja). So pediatric is a *deferred build decision*, not a
source wall.

**But the second layer decides it.** Most EPUS pediatric tabs are **hollow shells** —
present but holding only staff names + dates (profile_source flags them `<-- SHELL`):
- `Imunisasi` — visit log only (BB/PB/diagnosa); **no antigen-level history** (no BCG/OPV/
  DPT/Campak per-dose). → immunization forms NOT fillable.
- `Tumbuh Kembang Anak` — 0 clinical leaves in 100% of records (staff names only). →
  KPSP / M-CHAT / GPPH / KMPE development forms NOT fillable.
- `Periksa Gizi` (SNST) — ~empty for kids, and it's an adult/ibu-hamil screen anyway.

The **real** pediatric data is the general clinical battery shared with adults:
`Anamnesa > Periksa Fisik` (BB/TB/IMT/vitals), `PTM` (vision/hearing), `Laboratorium`
(GDS), `MTBS` (fever/cough/BB), `Anamnesa Keluhan`.

### What shipped (converter `_pediatric_forms`, verified 2026-06-02)

**Bug fixed:** `epus_to_asik` now routes `years < 18` to `_pediatric_forms` and returns — kids
no longer fall through to the adult battery. **~9% of matched patients (600 of 6516) were
affected** (mis-emitted as "Demografi Dewasa" + adult forms). Forms below are byte-exact
against the live forms matched kids carry; values are filled only from the general clinical
battery shared with adults. Gates: `audit_coverage` = **0 drift**; `verify_converter --min-age
0 --max-age 17 --n 8` = **0 hallucination / complete / valid shape**; adult `--min-age 18`
regression still passes. (4 live forms not previously in `asik_form_mapping.json` were added to
it: `Gizi Anak Sekolah`, `Tekanan Darah Anak dan Remaja`, `Pertumbuhan 5-6`, `TB X-Ray Anak
1-9` — a manual add like the 2026-05-29 EKG one; a `build_mapping.py` rebuild from the Padanan
xlsx would drop them.)

| Form | age band | EPUS source |
|---|---|---|
| Skrining Pertumbuhan - Balita dan Anak Prasekolah 1-5 Tahun | 1-4 | Periksa Fisik BB/TB + Cara Ukur (posisi) |
| Skrining Pertumbuhan - Balita dan Anak Prasekolah 5-6 Tahun | 5-6 | Periksa Fisik TB |
| Gizi Anak Sekolah | 7-17 | Periksa Fisik BB/TB |
| Tekanan Darah Anak dan Remaja | 7-17 | Periksa Fisik Sistole/Diastole |
| Pemeriksaan Gula Darah Anak / Remaja | 2-14 / 15-17 | self-report DM radio + PTM Pemeriksaan Gula (GDS) |
| Pemeriksaan Gigi - Anak | 1-17 | Pemeriksaan Dasar Gigi (Status Karies "-" → "Tidak ada"; no count source) |
| Faktor Risiko dan Skrining X-Ray TB (Anak 1-9 tahun) | 1-9 | Anamnesa cough (reuses `_cough_duration`) |
| Frambusia / Kusta / Skabies | all ≥1 | shells (no source, like adults) |

### Confirmed NO source (don't chase)
- **Skrining Telinga dan Mata (anak)** — checked 2026-06-02: EPUS `PTM > Gangguan Penglihatan /
  Pendengaran` (the adult source) is **0% populated for under-18** (0 of 124 matched kids). The
  feasibility pass wrongly listed this as "fillable, reuse adult PTM" — children's ear/eye is
  recorded via a pediatric flow EPUS doesn't capture in PTM. No source → not built. (Lesson,
  again: measure source *population* per band before calling a form fillable, not just whether
  the field exists for adults.)
- ~~All newborn screening (… Bayi Kuning/Kramer, … PJB pulse-ox …)~~ — **PARTLY WRONG,
  corrected 2026-08-24: EPUS DOES have Bayi-Kuning ikterus AND PJB pulse-ox sources.** See
  **"Bayi baru lahir / newborn registry (PJBK + Ikterus)"** section below. Still genuinely no
  source: SHK/G6PD/HAK heel-prick, Saluran Empedu, EID; Immunization beyond Hep-B0 (`Imunisasi`
  shell); Development KPSP/M-CHAT/GPPH/KMPE (`Tumbuh Kembang Anak` shell); Kesehatan Jiwa
  Anak/Remaja; Talasemia panels.
- **Demografi Anak**: live matched kids carry **no** demografi form at all, so there is nothing
  to fill (don't emit one — earlier feasibility wrongly listed it; corrected by the live audit).

### Paket grouping — FIXED 2026-06-02 (klaster-aware)
`paket_map.paket_for` matched `berat badan` / `tekanan darah` / `gula darah` keywords FIRST and
grouped kid BB/TB/BP/GDS into the **adult** paket cards. Fixed: `paket_for` now short-circuits
when the layanan (form) name is pediatric (`_is_pediatric_layanan` — tokens `anak/balita/bayi/
remaja/prasekolah`, none of which appear in any adult/lansia form) and returns the kid form as
its own card. So the merged output is now the **real ASIK form structure** for kids, not just
correct values under adult labels. Adult grouping is byte-identical (verified: pediatric +
adult `paket_for` regression both pass).

**After this change:** restart the Celery worker and re-merge affected (under-18) patients with
`force_remerge` to surface the pediatric output (backend change — see project memory). No worker
was running at build time.

## Bayi baru lahir / newborn registry (PJBK + Ikterus) — SOURCE RESEARCH DONE, scraper + registry NOT built (2026-08-24)

Client wants 3 registry sheets — **PJBK** (pulse-oximetry congenital-heart screen),
**Ikterus**, **Ikterus Berat** — for newborns. Research verified LIVE against jaksel
(Tebet), real bayi `pelayanan_id=2121393` "BAYI NYONYA NI KOMANG LINDA RAHAYU" (the same
bayi as the client's screenshot). **This corrects the stale "newborn = NO source" claim above.**

**Data availability (measured on prod 2026-08-24, aggregate scan of all 331 bayi):**
331 records named "BAYI %"; **330 `epus_only` + 1 `asik_only` → 0 matched.** ASIK has
essentially no bayi data → the client's "match ASIK∩EPUS" rule yields ~0. **Decision: the
newborn registries are EPUS-only** (like the dashboard scans), no ASIK-match requirement.

**Bayi vs. parent identity (the client's worry) — SOLVED.** In one Persalinan visit EPUS
carries TWO separate `pelayanan` records: the parent (`id=2121031`, `umur_tahun=30`) and the
bayi (`id=2121393`, `umur_tahun=0`, nama "BAYI NYONYA <ibu>"). Bayi has **its own
pelayanan_id** holding its own clinical tabs, and carries the **parent's NIK** (no KTP; the
`data_pasien.NIK` may even have HTML junk like `</br>`). So: **identify a bayi by
`umur_tahun==0` + nama prefix "BAYI ", read that record's own tabs, and NEVER join bayi-parent
by NIK.** No collision risk once you key off the bayi's own pelayanan record.

**Source 1 — Ikterus (module `mtbm`, Manajemen Terpadu Bayi Muda):** already scraped, but the
classification is **JS-applied, so our no-JS scraper reads it EMPTY (confirmed empty in 100%
of prod bayi).** The raw HTML has `<select name="MtbmDetail[klasifikasi][2]">` with the exact
registry options **Tidak ada ikterus(1) / Ikterus(2) / Ikterus berat(3)**, but no `selected`
attr; an inline `var json`/`var data` + `setDataDetail(data)` applies the saved value via
jQuery `.val()`. **Proven capturable by JS-render** (rendering mtbm populated the Diare
classification `value='1'`/`'Tidak diare'`; write-guard blocks the `/klaster_siklushidup` POST
so it stays read-only). Fix = JS-render the bayi's `mtbm` page, or parse the embedded `var json`.

**Source 2 — PJB pulse-ox (module `skriningpjb`):** the dedicated **"Skrining Penyakit Jantung
Bawaan (PJB)"** page is a REAL EPUS module we simply never scraped — **NOT in `_KNOWN_MODULES`,
not in the jaksel Anamnesa bar, not embedded in mtbm/kartubayi.** Route: **`GET
/skriningpjb/create/{pelayanan_id}` fetched WITHOUT the `X-Requested-With` header** returns the
full HTML form (116 KB). WITH the XHR header the SAME url returns a dokter-dropdown JSON
(Laravel `Request::ajax()`) — that false lead cost a probe. The scraper's `_parallel_fetch`
sends no XHR header, so **adding `skriningpjb` to `_KNOWN_MODULES` is enough to fetch the form.**
Fields (match registry columns 1:1): `SkriningPjb[pemeriksaan][N][waktu | tangan |
saturasi_tangan | kaki | saturasi_kaki | perbedaan_saturasi | interpretasi | warna]`;
`[tangan]` in {Tangan Kanan,Tangan Kiri}, `[kaki]` in {Kaki Kanan,Kaki Kiri}. **OPEN:** the
test bayi's PJB was blank, so whether saved readings are server-rendered (`value=`) or
JS-applied (like mtbm) is UNVERIFIED — needs one FILLED bayi before writing the value parser.

**Source 3 — Rujuk Eksternal column (referral):** server-rendered HTML report tables (no XHR)
at **`GET /laporanrujukanexternal?search[dari_tanggal]=DD-MM-YYYY&search[sampai_tanggal]=…`**
(and `/laporanrujukaninternal`); add `search[dari_umur_tahun]=0&search[sampai_umur_tahun]=0` to
scope to bayi. Columns: Tanggal, Nama, NIK, DOB, Umur, JK, Diagnosa, Tujuan Rujukan. Match a
registry bayi by NIK+Nama+Tanggal.

**Classification (client confirmed "pakai field EPUS langsung"):** ikterus → the
`MtbmDetail[klasifikasi]` select label; PJB → the `[interpretasi]` field. No backend recompute.

**NOT built yet:** (1) scraper: add `skriningpjb` module + JS-capture the mtbm ikterus
classification (verify PJB value storage on a filled bayi first); (2) re-scrape bayi; (3) an
**EPUS-only** registry scan (pattern of `hipertensi_registry_scan`, keyed on bayi markers) +
report routes + chatbot packs. The stale `epus_to_asik.py:~1751` comment ("MTBM has only a
SINGLE saturasi → PJB shell") is WRONG; correct it when the converter/registry work lands.

## Formulir Skrining battery (Klaster & Siklus Hidup) — NEW source class (converter shipped; re-verified per-region 2026-06-05)

EPUS's own **CKG screening forms** under "Klaster & Siklus Hidup" — a THIRD data class
beyond `tabs.fields` + `tabs.tables`, never scraped before (the show-parser blocklists
`box-KlasterSiklusHidup`). They hold the questionnaire data the Padanan sheet marked
"Belum ada di ePus" (Kesehatan Jiwa PHQ-4, SKILAS/ADL-Barthel lansia, PPOK PUMA, cancer
risk, TB risk, …). See `documents/SKRINING_RECLASSIFICATION.md` + memory
`project_formulir_skrining_source`.

**Recon (3 regions, n=160/region, tahun=2026):** 47 distinct screening types. Done-rates:
jaksel/Tebet 42% (up to 29 forms/patient), kotatangerang/Cipondoh 26%, kotabekasi/Pekayon
Jaya 20% (the converter's home + POOREST — why it was missed). `sudah_ckg` does NOT predict
done-screenings. **~503/740 "Belum ada" questions** are in forms a screening now sources
(adult/lansia); the rest is maternal/newborn/pediatric + Hati/Malaria/NTD/Lab-Hepatitis.

**Read path (read-only, in `scrapers/epus/patient_scraper.py`):** hub `POST
/klaster_siklushidup/{pid}/getlist` (tahun&pelayanan_id&_token) → per done screening keep
the getlist **record** (instruments carry all items: ADL 10 Barthel scores, SKILAS 14
items, HT klasifikasi, DM/payudara kesimpulan, PHQ skor/interpretasi) + best-effort
`/{route}/edit/{id}` **detail** (questionnaire radios; some render via JS → invisible to
no-JS scrape → record is the reliable source). Output key `skrining_klaster` — the done-gate was
REMOVED, so EVERY offered form is recorded (done OR not; a not-done form is a `{done:false}` stub →
the per-patient offered-form catalog is complete; the converter skips stubs). Also
`rujukan`/`surat_keterangan` parsed from the `#content` /show summary. CPPT SOAP via
its DataTables XHR → key `cppt`. Edit-url varies: `/{route}/edit/{id}` | `/edit/{id}/{pid}`
| PHQ `/edit/{pid}?header={id}` | gejala_tbc `/{route}/{pid}`. Tools:
`tools/recon_skrining.py` + `tools/skrining_inventory.py` (catalogs in `scrapers/epus/output/`);
`tools/enrich_db_skrining.py` re-scrapes a sample into the DB for the gates.

**Converter (`epus_to_asik.py`) — SHIPPED + VERIFIED (gates below all pass, 2026-06-04):**
`_skrining_index` flattens `skrining_klaster` (record ∪ detail, detail wins). Mapped (each
source-wins, degrades to {} when the screening is absent):
- **Skrining Kanker Payudara** ← payudara `kesimpulan` (SADANIS result; "Normal" verified live
  2026-06-05). USG: the edit-page `hasil_usg` (Normal/Simple cyst/Non simple cyst — the ASIK
  options) is now captured by `_extract_js_answers` and emitted when USG was actually performed.
- **Kesehatan Jiwa** ← the EPUS PHQ-4 **per-item** answers. The live ASIK form = 4 PHQ-4 frequency
  questions (verified 2026-06-05); EPUS's PHQ-4 form holds the SAME 4 + the 0-3 scale, but the saved
  answers render via Vue `viewData` (so the no-JS `detail` was empty — why this was first wrongly
  reverted to a shell). `patient_scraper._extract_js_answers` now parses `viewData.skriningDetail`
  (per-item skor 0-3); the converter maps each question → ASIK label + skor → frequency ("Tidak sama
  sekali" 0 / "Kurang dari 1 minggu" 1; 2,3 inferred from EPUS labels). PHQ-4 uses 2 headers
  (PHQ-2+GAD-2) — `_fetch_skrining` now fetches BOTH (`/edit/{pid}?header=*`).
- **PPOK (5 questions)** ← PTM > Faktor Risiko, with the EPUS PUMA screening (`napas_pendek`/`dahak`/
  `batuk`/`pemeriksaan_fungsi_paru`/`pernah_merokok`, JS-applied → captured by `_extract_js_answers`)
  as a direct-source fallback when PTM is blank. The "Hasil Skor Kuesioner PUMA" SCORE field is NOT
  on the live ASIK form (per `_map_ppok_puma`) — the earlier emission was a phantom → removed 2026-06-05.
- **Skrining Jantung** Hasil Pemeriksaan EKG (fallback for PTM) ← resiko_jantung edit-page
  `SkriningJantung[ekg_v2]` (verified live; the old bare-`ekg_v2` read never matched → fixed 2026-06-05).
- **SKILAS Gejala Depresi** ← skilas `depresi_terganggu`/`depresi_minat` (direct Ya/Tidak).
- **SKILAS Malnutrisi** ← skilas `malnutrisi_badanberkurang`/`_makan`/`_lila`.
- **SKILAS Mobilisasi** ← skilas `mobilisasi_tidak` via `_mobilisasi_answer`. The EPUS question
  is POSITIVE ("dapat berdiri 5x dalam 14 detik?", verified live jaksel+ktg 2026-06-05): radio
  value **0="Ya"/dapat, 1="Tidak"/tidak-dapat** — the OPPOSITE value→label ordering from the
  symptom fields. The edit-page detail (which wins) carries the "Ya"/"Tidak" label so live output
  is correct, but the raw record code is INVERTED vs `_skilas_yn`, so it's mapped explicitly to
  stay correct when only the record code is present.
- **SKILAS Penurunan Kognitif** ← the 4 EPUS checkboxes (recall pair `harus_diingat`/
  `kognitif_tidakmengulang` → Q1+Q3 Ya/Tidak; orientation pair `dijawab_tepat`/`kognitif_salahsatu`
  → Q2 "Benar semua"/"Salah satu/Dua"). Conditional-fill; "Tidak Tahu" has no EPUS source.
  (Mapped 2026-06-05 per the "EPUS owns the data" decision — previously a shell.)
- **Barthel Index** ← adl 10 scored items, coerced 0/1/2/3 → exact ASIK option labels
  (`_BARTHEL`). Score direction verified live (Tebet 2026-06-05: 0=worst … max="Mandiri"); the
  rare 0-score labels use canonical Kemenkes wording (unseen in the live scan).
`EPUS_BREADCRUMBS` added for all of the above. The mapping json's placeholder labels for
Barthel + SKILAS-Depresi (`"…ADL…-01"`, `"SKILAS-Gejala Depresi-01"`) were patched to the live
question text so `audit_coverage` reads 0 drift.

**Gates (2026-06-04, all green):** `audit_coverage` = **0 name/label drift**;
`verify_converter --all-regions --n2 --models gpt` = **PASS (jaksel/kotatangerang/kotabekasi,
0 halluc/complete/shape)**; `audit_uncovered` (now walks `skrining_klaster`) triaged — remaining
unmapped screening fields are metadata, redundant clinical (sistole/diastole/klasifikasi already
from Periksa Fisik/PTM), or conclusions, i.e. **no missed coverage**. **End-to-end proven**: the
real merge pipeline on an enriched lansia patient yields `merged_data` containing SKILAS Depresi/
Malnutrisi/Mobilisasi + Barthel with correct values. **Per-region LIVE verification (2026-06-05,
read-only login to jaksel+kotatangerang+kotabekasi)** confirmed against the real EPUS edit forms +
live ASIK captures: mobilisasi polarity, ADL score direction, EKG field/key, payudara `kesimpulan`,
PUMA `interpretasi`, and that the live Kesehatan-Jiwa form is the 4 PHQ-4 frequency questions.

**KEY LESSON — JS-applied answers (2026-06-05).** Many screening forms (PHQ-4, PUMA, payudara, …)
apply the SAVED per-item answers via JavaScript — Vue `viewData` JSON, or jQuery
`$('input[name="X"][value="Y"]').prop('checked',true)` — so the no-JS scrape's `detail` is EMPTY and
the getlist record carries only the SUMMARY (score/conclusion). **Do NOT conclude "no EPUS source"
from an empty `detail` + summary-only record** — check the edit HTML for the JS-applied answers.
`patient_scraper._extract_js_answers` now extracts them (viewData `skriningDetail` + jQuery
`.prop`/`.val`); this is what made **Kesehatan Jiwa** (PHQ-4 per-item, after first being wrongly
reverted) and the **PUMA-screening fallback** mappable. (PHQ-4 also splits across 2 headers →
`_fetch_skrining` fetches both.)

**Intentionally NOT mapped (with reason):**
- Redundant clinical screenings (hipertensi/DM/obesitas/ginjal vitals & classifications) —
  those ASIK questions are already filled from Periksa Fisik / PTM / lab, so mapping the
  screening adds **no coverage** and risks breaking working maps. Documented, deliberately skipped.
- Cervical (`skrining_resiko_kanker_serviks`) — its detail/record fields aren't captured
  reliably (mostly JS-applied / empty); no clean source.

**REMAINING — production rollout only (the agreed final step):** full re-scrape of all patients
with the new scraper (read-only, ~hours), then Celery **worker restart** (converter is a
`backend/app` change) + **force_remerge** (LLM cost). A 150-patient sample was enriched
2026-06-04 via `tools/enrich_db_skrining.py` and proven end-to-end. `profile_source.py` not yet
extended for the `skrining_klaster` class (minor; `audit_uncovered.py` is).

## Next sources (planned / placeholder)

_None yet. When one arrives, follow SKILL.md "Adding a brand-new source", then add a
row above + its `<SOURCE>_TO_ASIK_VERIFICATION.md`._
