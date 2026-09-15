# EPUS → ASIK Conversion: Live Verification Report

> ## Addendum — 2026-06-03 (evening re-run — same state, OSS model down)
>
> Evening re-run on the same date confirmed all findings from the morning pass. **No MUST-FIX,
> no converter change this run.** Difference from the morning: the OSS model endpoint
> (`openai/gpt-oss-20b`) returned 404/502, so `--models oss` cross-model divergence check
> fails. The converter itself is clean — `--models gpt` and `--models deepseek` both PASS
> all 3 regions. Results:
> - **Regions** (`audit_regions.py`): PASS — 3 regions (jaksel/kotatangerang/kotabekasi),
>   age-controlled extraction ratio 94%/94%/100% (adults 18–59), all 6 converter-critical tabs
>   present, no form differs >2.0 across regions. The jaksel `data_pasien` renames (`Nama`,
>   `Tempat & Tgl Lahir`, `No. HP`, …) are all handled by the converter or have no ASIK target.
> - **Per-region verify** (`verify_converter --all-regions --n 6 --models gpt`): PASS for every
>   region (0 hallucination / complete / valid shape). Same result with `--models deepseek`.
>   `--models oss` FAILs due to the endpoint being down (404/502).
> - **Coverage** (`audit_coverage.py`): **0 name/label drift.** The `[MISSING]` list is all
>   `in_audit=False` spec-only alternates + sourceless shells, **plus a sampling false-positive**
>   for `Pemeriksaan Inspekulo dan IVA` + `Skrining Kanker Payudara`: these ARE mapped by
>   `_map_iva_sadanis` (perempuan ≥30 with populated `Hasil IVA`/`Hasil Sanadis`), but only
>   ~0.2% of patients have that data, so a random n≈120 rarely triggers the emission. Verified
>   on data: 6/3000 had results; all 5 eligible women emitted both forms; the 24-yo was
>   age-gated out. Not a gap.
> - **Uncovered source** (`audit_uncovered.py`): no genuinely-new candidates — same set as the
>   2026-05-29 sweep (family-hx non-cancer, diet/behavior, vitals ASIK-skips, physical-exam
>   narratives, COVID/ISPA block, phone, status-kawin), all noise or no live adult target.
> - **ASIK drift** (`capture_target.py`, fresh 4-patient `selesai` Pekayon Jaya dump): **0 new
>   live forms; 0 new questions in any EPUS-sourced clinical form.** The reported "new questions"
>   are the known placeholder/whitespace label-drift in sourceless self-assessment/lansia forms
>   (Kesehatan Jiwa, Barthel, GDS/Mini-Cog/SKILAS, GPAQ) — fix on the next Padanan rebuild.
>
> **Ops:** no converter edit this run → no new restart from this run. **But** the
> `_map_identitas` jaksel `Tempat & Tgl Lahir` fix remains in the working tree **uncommitted**;
> it needs a Celery worker restart + `force_remerge` of jaksel patients to take effect.

> ## Addendum — 2026-06-02 (pediatric under-18 battery shipped)
>
> Fixed a latent klaster bug and shipped the fillable pediatric forms. **~9% of matched
> patients (600 of 6516) are under-18** and were previously mis-emitted as "Demografi Dewasa"
> + the full adult battery — `epus_to_asik` now routes `years < 18` to `_pediatric_forms` and
> returns before the adult cluster.
>
> **Shipped** (byte-exact vs the live forms matched kids carry; values only from the
> adult-shared clinical battery — `Anamnesa > Periksa Fisik`, `PTM > Pemeriksaan`, Anamnesa
> cough, basic dental): Skrining Pertumbuhan Balita 1-5 (BB/TB/posisi) + 5-6 (TB); Gizi Anak
> Sekolah (BB/TB, 7-17); Tekanan Darah Anak dan Remaja (sistol/diastol, 7-17); Pemeriksaan Gula
> Darah Anak/Remaja (self-report DM radio + GDS); Pemeriksaan Gigi - Anak (`Status Karies` "-" →
> "Tidak ada"; no count source); Faktor Risiko X-Ray TB Anak 1-9 (cough via `_cough_duration`);
> Frambusia/Kusta/Skabies shells. 4 of these live forms were added to `asik_form_mapping.json`
> (manual, like the EKG add — a `build_mapping.py` rebuild would drop them).
>
> **Gates:** `audit_coverage` 0 name/label drift; `verify_converter --min-age 0 --max-age 17
> --n 8` → 0 hallucination / complete / valid shape; adult `--min-age 18` regression still
> passes.
>
> **Not built / no source:** newborn screening, immunization (`Imunisasi` is a shell),
> development KPSP/M-CHAT/GPPH/KMPE (`Tumbuh Kembang Anak` is a shell), Kesehatan Jiwa Anak/
> Remaja, Talasemia. `Demografi Anak` — matched kids carry no demografi form. **telinga/mata-anak
> also has no source** — EPUS `PTM > Gangguan Penglihatan/Pendengaran` (the adult source) is 0%
> populated for under-18 (the feasibility pass wrongly assumed it carried over). See
> `RESEARCH_STATUS.md` → Pediatric for the full verdict.
>
> **Paket grouping fixed too** (`paket_map.py`): `paket_for` now short-circuits pediatric
> layanan names so kid BB/TB/BP/glucose group under their own kid card instead of the adult
> theme card — the merged output is the real ASIK form structure for kids, not just correct
> values under adult labels. Adult grouping unchanged (regression checked).
>
> **Ops:** backend change (converter + `paket_map.py`) — restart Celery worker + re-merge
> under-18 patients with `force_remerge`.

> ## Addendum — 2026-05-29 (uncovered-source audit + dental)
>
> Re-audited the shipped converter two ways: ASIK-target drift (`capture_target.py`
> vs a fresh Pekayon Jaya live dump) and the **EPUS source side** (new
> `audit_uncovered.py`: ~600 populated leaf-fields vs the converter).
>
> **Verdict: converter is complete for the live adult CKG battery.** `verify_converter.py`
> `--n 8` passes (0 hallucination). `audit_coverage.py` exits 0 (0 name/label drift).
> Every uncovered EPUS field is admin/visit noise or has no live adult target — see
> `RESEARCH_STATUS.md` "uncovered-source audit" for the ruled-out list (family-hx non-cancer,
> diet/alcohol behavior, IMS clinical-signs, vitals).
>
> **Changes this run:**
> - **Dental mapped** (closes §10 item 9, but via the right source). `Skrining Karies dan
>   Gigi Hilang` + `Skrining Penyakit Periodontal` now source from `Anamnesa > Pemeriksaan
>   Dasar Gigi` (~5% fill, all radio Ya/Tidak): `Gigi Goyang`←`Goyang`; `Gigi karies`←
>   `Status Karies`/`Karies Gigi`; `Penyakit Periodontal`←`Warna Gusi`/`Pem-bengkakan`;
>   `Gigi hilang/dicabut`→null. **The EPUS Odontogram was rejected** — its `Diastema`/
>   `Gigi Anomali` are constant `"Ada"` defaults (123/123), i.e. noise (corrects §6/§10's
>   "map Odontogram" guidance).
> - **`Pemeriksaan EKG`** added to `Hasil Pemeriksaan - Skrining Jantung` in the mapping
>   json — the only genuinely-new live question; no EPUS source, tracked for an honest tally.
> - Other `capture_target` "new questions" were placeholder/whitespace **label drift**, not
>   absent questions — defer to the next `build_mapping.py` (Padanan Excel) rebuild.
>
> The 2026-04-29 report below is the original pre-ship audit; its open action items are done.

---

**Date:** 2026-04-29
**Scope:** Verify `backend/app/services/epus_to_asik.py` against (a) 32 matched patients in local Postgres `ckg-ai-postgres-1` (decrypted EPUS + ASIK blobs) and (b) 52 live ASIK form URLs visited via agent-browser logged in as `julineaurora@gmail.com` (Pekayon Jaya).

Audit data persisted under `testing-epus-asik/asik_audit_20260429/` (one JSON per ASIK form, schema captured from rendered SurveyJS DOM).

---

## 1. Verdict

The deterministic converter is **structurally correct** for the 5 always-emit clinical forms it covers:

- `Tekanan Darah Dewasa Lansia`
- `Pemeriksaan Gula Darah Dewasa Lansia`
- `Gizi (BB - TB - Lingkar Perut) Perempuan|Laki-laki`
- `Pemeriksaan PPOK (Skrining PUMA)` — **with one label-drift bug, see §3**
- `Demografi Dewasa <gender> | Lansia` — **with two missing fields, see §5**

It is **incomplete** in two ways:

1. **Missing forms** that ASIK records show 100 % of patients fill (12 forms; §6). Converter currently emits zero shells for them, so the Convert tab shows nothing.
2. **Wrong age cap** on the female cancer-screening forms (§4) — converter caps Inspekulo / Sadanis / HPV at age 50, but live ASIK runs them for all female ≥ 30 (incl. 60+ patients in our DB).

The 9 categorical mismatches in the existing comparator are **not converter bugs** — they are real-world data drift between the EPUS and ASIK visits (clinical-truth `Ya` vs patient-self-report `Tidak` weeks later). Existing design (`clinical` flag wins) is correct per the rules doc.

---

## 2. How verification ran

| Step | Source | What it confirmed |
|------|--------|-------------------|
| Decrypt 32 matched patients | `patients.scraped_epus_data` + `scraped_asik_data` (Fernet, `CRED_ENCRYPTION_KEY`) | Converter input shape / output values |
| Run converter, diff against real ASIK | `epus_to_asik(epus)` vs `pelayanan_nakes` + `pemeriksaan_mandiri` | 144 exact matches, 71 numeric drift (different-visit), 9 categorical conflicts (self-report flips) |
| Visit 52 form URLs live | `https://form.kemkes.go.id/v2/skrining-form/...` via agent-browser | Field-by-field schema, exact labels, conditional reveals |
| Click each gating radio | `input[type=radio]` that matches `Ya` / `Iya` / `Bersedia` / `Curiga gangguan penglihatan` | Confirmed conditional reveals (§7) |

---

## 3. Field-label drift (will break ASIK form posting)

The schema dump shorthand ≠ live label. When the merge-back submits to ASIK, label-keyed payloads must match the live label byte-for-byte.

| Form | Converter label | Live label | Action |
|------|----------------|-----------|--------|
| `Pemeriksaan PPOK (Skrining PUMA)` | `…untuk mengetahui fungsi paru anda?` | `…untuk mengetahui fungsi paru?` | **Drop the trailing ` anda` in the converter key.** |
| `Tekanan Darah Dewasa Lansia` | `Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter?` | `Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? Isi Total Bulan Sejak didiagnosis dokter hingga saat ini, misal didiagnosis 1 tahun yang lalu = 12, dst` | Schema match works on prefix today; if posting to ASIK keys on full label, append the `Isi Total Bulan…` suffix. **No EPUS source for this value anyway**, so converter emits null — submission impact is zero unless the merge layer drops the key. |
| `Pemeriksaan Gula Darah Dewasa Lansia` (GDS-2) | not emitted | `Gula Darah Sewaktu Kedua (GDS 2). Lakukan jika hasil GDS 1 Prediabetes (≥140-199mg/dl) atau Hiperglikemia (≥200mg/dl) dan BELUM PERNAH didiagnosis Diabetes` | Converter intentionally skips. Note the long label so any future emitter uses verbatim. |

All other emitted labels match live char-for-char.

---

## 4. Age-gating — empirical vs converter rules

Across 32 matched patients (gender × age band):

| Form | Converter gate | Live data shows | Verdict |
|------|----------------|----------------|---------|
| Tekanan Darah / Gula Darah / Gizi / PPOK / Telinga-Mata / Demografi | always | always | ✅ correct |
| `Pemeriksaan PPOK (Skrining PUMA)` | always | only ≥ 40 (0/2 L 30-39, 0/4 P 30-39, 0/2 P <30) | ⚠️ converter over-emits — ASIK simply drops missing form so harmless, but list view shows form unnecessarily for adults <40 |
| `POCT Lipid Panel (≥40)` | `years ≥ 40` | 100 % `≥ 40` | ✅ |
| `Skrining Fungsi Ginjal <gender> (≥40)` | `years ≥ 40` | 100 % `≥ 40` | ✅ |
| `Skrining Kanker Paru (≥45)` | `years ≥ 45` | 100 % `≥ 45` | ✅ |
| `Hasil Pemeriksaan - Skrining Jantung` | `clinical.HT or DM` | 100 % `≥ 45` regardless of HT/DM (incl. HARTONO, YUKI both no flags) | ⚠️ **gate is age-based, not flag-based** — converter under-emits for ≥45 non-HT/DM patients |
| `Pemeriksaan Inspekulo dan IVA` | `Perempuan AND 30 ≤ years ≤ 50 AND Hasil IVA non-null` | 100 % female ≥ 30 incl. 60+ | ⚠️ **upper cap of 50 is wrong** — drop it |
| `Skrining Kanker Payudara` | same | same | ⚠️ same fix |
| `Hasil Pemeriksaan HPV-DNA` | not emitted | 100 % female ≥ 30 | ❌ add: female ≥ 30 |
| Lansia Lanjutan battery (SPPB / MNA-SF / AD-8 / Mini Cog / Gejala Depresi Lanjutan) | not emitted | 100 % `≥ 60` | ❌ add as shells alongside SKILAS |
| `Skrining Kerusakan Ginjal (≥40)` | not emitted | 100 % `≥ 40` | ❌ add as shell |
| `Pemeriksaan Lanjutan Kanker Usus` | not emitted | 100 % `≥ 45` | ❌ add as shell, per §7 conditional |
| `Faktor Risiko Kanker Usus` | not emitted | 100 % `≥ 45` | ❌ add as shell |
| `Pemeriksaan Calon Pengantin Perempuan` (Kadar Hb only) | not emitted | 100 % female adult | ❌ add as shell *or* map from Laboratorium tab Hb if present |
| `Riwayat Imunisasi Tetanus … - Hanya untuk Catin` | not emitted | 100 % female adult | ❌ add as shell |

---

## 5. Demografi forms — converter currently empty

Converter emits `{}` for `Demografi Dewasa Laki-Laki` and `Demografi Lansia`, and only `Apakah Anda sedang hamil?` for `Demografi Dewasa Perempuan`. Live forms have:

| Live field | Options | EPUS source |
|-----------|---------|-------------|
| `Status Perkawinan` | Belum Menikah / Menikah / Cerai Mati / Cerai Hidup | EPUS `data_pasien."Status Perkawinan"` (string) — needs value-map: `Kawin`→`Menikah`, etc. **Worth wiring up.** |
| `Apakah Anda penyandang disabilitas?` | Non disabilitas / Penyandang disabilitas | No EPUS source — leave null. Form expects answer; default `Non disabilitas` is reasonable but better left null and flagged for manual entry. |

Note: real ASIK records don't list Demografi forms in `pelayanan_nakes` / `pemeriksaan_mandiri` (Demografi is part of `detail_data.data_individu` registration). Converter still emits Demografi forms as shells for the frontend's Convert tab — this is fine for UX.

---

## 6. Forms NOT emitted by converter that 100 % of real records have

Each appears in **all 32 matched patients' ASIK output** but converter emits zero shell. Add as empty shells (or, for the few with EPUS sources, populate them):

| Form | Fields | EPUS source candidate | Action |
|------|--------|----------------------|--------|
| `Faktor Risiko TB - Dewasa & Lansia` | 1 radio | EPUS `tabs.PTM.fields."Faktor Risiko"` — has TB-style coughing questions | **map** parent `Apakah Anda pernah atau sedang mengalami batuk yang tidak sembuh-sembuh?` → trinary radio |
| `Faktor Risiko dan Skrining X-Ray TB (Dewasa & Lansia)` | 6 radio | overlap with EPUS PTM Faktor Risiko (BB turun, demam, keringat malam — exists in EPUS Anamnesa). Verify field paths before mapping. | **partial map** |
| `Pemeriksaan Tuberkulosis (Dewasa & Lansia)` | 2 dropdown | none in EPUS PTM | shell |
| `Pemeriksaan Penyakit Frambusia / Kusta / Skabies` | 1 radio/dropdown each | EPUS Penyakit Tropis Terabaikan tab (not yet inspected — `tabs` lookup needed) | shell for now |
| `Skrining Karies dan Gigi Hilang` | 2 radio | EPUS `tabs.Odontogram` (rich) — needs reduction to "any caries? any missing?" booleans | shell first; map later |
| `Skrining Penyakit Periodontal` | 2 radio | same — Odontogram | shell |
| `Pemeriksaan Hepatitis` | 2 radio (HBsAg / HCV reactivity) | EPUS Laboratorium tab if present | shell |
| `Pemeriksaan Fibrosis/Sirosis Hati` | 2 number (SGOT, Trombosit) | EPUS Laboratorium tab | shell, map when Lab parser is added |
| `Pemeriksaan Kadar CO` | 1 number (Kadar CO Pernapasan) | not in EPUS PTM | shell |
| `Pemeriksaan HIV` | 1 radio (Reaktif/Non Reaktif) | EPUS Konseling HIV tab | shell |
| `Pemeriksaan Sifilis` | 1 radio | EPUS Periksa IMS tab | shell |
| `Hati` | 9 radio (hepatitis risk factors) | none in EPUS PTM | shell |

---

## 7. Conditional reveals — verified live (click-and-see)

| Form | Parent question | Trigger value | Revealed children | Converter handles |
|------|----------------|---------------|--------------------|--------------------|
| `Tekanan Darah Dewasa Lansia` | `Apakah Anda pernah dinyatakan tekanan darah tinggi?` | `Ya` | `Sudah Berapa Bulan Anda Didiagnosis Hipertensi Oleh Dokter? Isi Total Bulan Sejak…` | ✅ emits `null` (EPUS no source) |
| `Tekanan Darah Dewasa Lansia` | — | always visible | `Tekanan Darah Sistolik Ke-2`, `Tekanan darah diastolik ke-2` | ⚠️ NOT optional in DOM but optional logically — converter skips (acceptable) |
| `Pemeriksaan Gula Darah Dewasa Lansia` | `Apakah Anda pernah dinyatakan diabetes…?` | `Ya` | `Sudah Berapa Bulan Anda Didiagnosis Diabetes Melitus Oleh Dokter?` | ✅ emits `null` |
| `Pemeriksaan Gula Darah Dewasa Lansia` | `Gula Darah Sewaktu (GDS) (mg/dl)` | `≥ 140` | `Gula Darah Sewaktu Kedua (GDS 2). …` (long label) | ✅ never emits (EPUS no source) |
| `Pemeriksaan PPOK (Skrining PUMA)` | `Apakah anda sedang/mempunyai riwayat merokok?` | `Iya` | `Jika Perokok Aktif, berapa bungkus per tahun?` (`<20 / 20-30 / >30 bungkus per tahun`) | ✅ emits bucket from `(rokok/20)*lama` |
| `Skrining Telinga dan Mata (≥40)` | `Apa hasil skrining tajam penglihatan?` | `Curiga gangguan penglihatan (visus <6/12)` | `Hasil pemeriksaan visus (snellen chart)` (one new field — schema dump claimed pinhole+refraksi which are NOT direct children — likely cascade further) | ❌ not handled — converter emits empty `{}` shell |
| `Pemeriksaan Lanjutan Kanker Usus` | `Kesediaan untuk diperiksa Colok Dubur` | (rendered always) | `Colok Dubur (hanya apabila bersedia)`, `Hasil pemeriksaan Darah Samar (hanya apabila bersedia)` — DOM keeps them visible regardless; conditional logic enforced by labels alone | ❌ converter doesn't emit at all |

**Schema-dump correction:** `testing-epus-asik/ASIK_FORM_SCHEMA.md` claimed "Skrining Telinga ≥40 reveals `Pemeriksaan Pinhole` + `Apa hasil pemeriksaan refraksi?`". Live audit shows only `Hasil pemeriksaan visus (snellen chart)` is the direct child of `Apa hasil skrining tajam penglihatan?` = `Curiga gangguan penglihatan`. Pinhole/refraksi may be cascade children of the visus answer — not yet inspected. Update the schema doc.

---

## 8. Disease (clinical-flag) gating — verified

Converter computes two flag sets per `_detect_chronic_flags`:

- **`self_report`** (Riwayat PTM Diri Sendiri only) — exposed but unused.
- **`clinical`** (Riwayat ∪ `Tandai Penyakit Kronis` ∪ ICDX prefix scan) — drives every parent radio + every disease-gated form.

Empirically:

| Patient | EPUS self_report | EPUS Tandai Kronis | ICDX | clinical | ASIK self-report at visit | Outcome |
|---------|------------------|---------------------|------|----------|---------------------------|---------|
| ALI IKHSAN | HT=No | — | I10 / E11 | HT=Yes, DM=Yes | answered "Tidak" to HT | converter `Ya`, ASIK `Tidak` → categorical mismatch flagged but **converter answer is medically correct** |
| HERLINA NUSADIAH | HT=No | — | I10 / E11 | HT=Yes, DM=Yes | answered "Tidak" both | same |
| (7 more like this) | — | — | — | — | — | self-report flips, irreducible |

**Verdict:** clinical-wins design is correct. The 9 categorical mismatches are not converter bugs — they reflect patients denying ICDX-coded diagnoses at ASIK visit time. Keep clinical gating.

ICDX prefixes wired in converter (verified):

- DM: `E10`-`E14`
- HT: `I10`-`I13`, `I15`
- Heart chronic: `I20`-`I25`, `I50`
- Lung chronic: `J40`-`J45`, `J47`
- Cancer: `C00`-`C99`
- Stroke: Tandai Kronis only (no ICDX scan in converter)

---

## 9. Numeric drift (71 cases) — not bugs

Sistole / Diastole / BB / Lingkar Perut / TB / GDS values differ between EPUS visit and ASIK visit by typical biometric variance (e.g. systolic ±10–30 mmHg over weeks). Converter writes the EPUS value; merge layer flags `is_conflict: true` and the LLM `reasoning` describes plausibility (which value is more clinically credible) per the prompt rules. No action.

---

## 10. Action items (sorted by impact)

### Quick wins (1–2 line code changes, high impact)

1. **PPOK Q5 label** — drop trailing ` anda` so converter key matches live ASIK label exactly.
   ```python
   # backend/app/services/epus_to_asik.py:_map_ppok_puma
   "Apakah Dokter atau tenaga medis lainnya pernah meminta Anda untuk melakukan pemeriksaan spirometri atau peak flow meter (meniup ke dalam suatu alat) untuk mengetahui fungsi paru?"
   #                                                                                                                                                                       ^^^^^ remove ' anda'
   ```

2. **Inspekulo / Sadanis / HPV — drop upper age cap.** Replace `30 <= years <= 50` with `years >= 30` in `_map_iva_sadanis`. Add HPV-DNA emission.

3. **Skrining Jantung gate.** Change `if HT or DM` → `if years >= 45 or HT or DM` (or just `years >= 45` if data shows that's the canonical rule).

4. **Demografi `Status Perkawinan`.** Map `data_pasien."Status Perkawinan"` → `{Kawin: Menikah, Belum Kawin: Belum Menikah, Cerai Hidup: Cerai Hidup, Cerai Mati: Cerai Mati}`.

### Add empty shells (frontend renders eligibility correctly)

5. Add 12 missing always-emit form shells listed in §6, plus `Hati` and `Penapisan Risiko Kanker Paru` if eligibility says so.

6. Add age-gated shells:
   - `Skrining Kerusakan Ginjal` (≥40)
   - `Faktor Risiko Kanker Usus` (≥45)
   - `Pemeriksaan Lanjutan Kanker Usus` (≥45)
   - Lansia Lanjutan: `Mobilisasi - Pemeriksaan Lanjutan (SPPB)`, `Skrining Malnutrisi - Pemeriksaan Lanjutan (MNA-SF)`, `Penurunan Kognitif - Tindak Lanjut (AD-8 INA)`, `Penurunan Kognitif - Tindak Lanjut (Mini Cog-Clock Draw)`, `Pemeriksaan Gejala Depresi - Pemeriksaan Lanjutan` (all ≥60)

### Optional value-mapping work

7. Map EPUS Faktor Risiko → `Faktor Risiko TB` parent + four follow-up questions (BB turun, demam, keringat malam — paths confirmed in `tabs.PTM.fields."Faktor Risiko"`).

8. Map EPUS Laboratorium → POCT Lipid (HDL/LDL/Trigliserida/Kol Total), Skrining Fungsi Ginjal (Kreatinin/Ureum), Fibrosis Hati (SGOT/Trombosit), Calon Pengantin Hb. Requires a Laboratorium-tab parser (rows-by-test-name).

9. Map EPUS Odontogram → Karies (any caries Y/N) + Periodontal (any Y/N).

### Schema-doc fixes

10. Update `testing-epus-asik/ASIK_FORM_SCHEMA.md` Skrining Telinga & Mata ≥40 conditional row — direct child of `Apa hasil skrining tajam penglihatan?` is `Hasil pemeriksaan visus (snellen chart)`, not pinhole/refraksi. Pinhole/refraksi probably cascade further from the visus answer (not yet audited).

---

## 11. What I did NOT verify (left for later)

- Cascade-of-cascade conditionals on Skrining Telinga & Mata (visus → pinhole? → refraksi?).
- Faktor Risiko Kanker Usus parent → Pemeriksaan Lanjutan child relationship (separate forms — likely chained by SurveyJS visibleIf across forms).
- Live EPUS DOM — converter assumes EPUS path constants (`tabs.PTM.fields…`) are stable. Verified empirically by running converter against 32 decrypted blobs without KeyError; full live EPUS dump audit pending.
- Catin (Calon Pengantin) workflow — only `Pemeriksaan Calon Pengantin Perempuan` (Kadar Hb) audited.
- Lansia Lanjutan dropdown options — extractor returned empty option lists for SurveyJS dropdowns (closed-set, options revealed only on click). Field names captured; option vocab not.

---

## Appendix: artifacts

- `testing-epus-asik/asik_audit_20260429/` — 52 JSON dumps (one per ASIK form, schema as captured 2026-04-29).
- `/tmp/converter_verify.json` — 32-patient diff (converter output vs real ASIK).
- `/tmp/verify_converter.py`, `/tmp/drill_gating.py`, `/tmp/compare_live_vs_converter.py` — verification scripts (kept for re-run).
