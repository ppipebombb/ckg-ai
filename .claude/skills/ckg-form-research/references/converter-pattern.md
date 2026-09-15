# Converter pattern — `app/services/<source>_to_asik.py`

Distilled from the reference implementation `epus_to_asik.py`. Mirror it for a new
source. Pure dict-in/dict-out: **no LLM, no network, no randomness, defensive `.get()`**.

## Public contract

```python
def <source>_to_asik(raw: dict) -> dict:
    """raw decrypted <source> scrape -> {asik_form_name: {asik_field: value}}.
    Only forms the patient is eligible for (age/gender/disease gating).
    None value = field left blank (legal — ASIK accepts partial)."""
```

Plus a breadcrumb table (drives the merge's `epus_question` backfill + the coverage
audit — the field labels here MUST match the live ASIK label byte-for-byte):

```python
<SOURCE>_BREADCRUMBS: dict[str, dict[str, str | None]] = {
    "<asik form name>": {
        "<asik field label, verbatim>": "<source path that produced it>",
        "<field with no single source>": None,   # computed/union -> None
    },
    ...
}
```

`audit_coverage.py --source <source>` reads `<source>_to_asik` + `<SOURCE>_BREADCRUMBS`
by name — keep the naming exact (`epus` → `epus_to_asik` + `EPUS_BREADCRUMBS`).

## The pieces (all in epus_to_asik.py)

1. **Value coercion helpers** — `_num` (str→int/float), `_yatidak` (Ya/Iya/ya→canonical),
   date→Indonesian, gender normalize, enum/bucket mappers (e.g. glucose→4-level). Keep
   them small + total (return None on anything unrecognized).

2. **Klaster gating** — derive age + gender once from the source's identity block; emit
   a form only when the patient is eligible (e.g. lab forms `years >= 40`, female-cancer
   `gender == Perempuan and years >= 30`). Match the live ASIK demographics
   (`demos_union` per form in `asik_form_mapping.json`).

3. **Disease flags (two-tier)** — `self_report` (the patient's own Riwayat answer →
   drives the parent radio) vs `clinical` (Riwayat ∪ diagnosis-mark ∪ ICDX-prefix scan →
   drives form *gating*). The parent radio mirrors the literal self-report field, NOT the
   clinical union, or you create fake conflicts. (See `_detect_chronic_flags`.)

4. **Per-form mapper functions** — one `_map_<form>(...)` each; return the field dict.
   Use the **exact** live ASIK field label as the key (verify via the live dump /
   `asik_form_mapping.json`). Label drift here silently breaks paket grouping + sync-back.

5. **Conditional reveals** — emit a child field only when the parent's value is the
   trigger; else emit `None` (or omit). The merge's `_drop_orphan_conditional_children`
   prunes children whose parent didn't trigger, anchored on `_CONDITIONAL_REVEALS` in
   `merge.py` — add a rule there if you introduce a new parent→child pair.

6. **Identity** — emit a synthetic `identitas_pasien` form (NIK/Nama/Tanggal Lahir/
   Tempat Lahir/Jenis Kelamin/Alamat) normalized to ASIK format. The merge rebuilds
   identity deterministically from source + ASIK `detail_data`, EPUS-wins.

7. **Always-emit shells** — forms the klaster runs but the source can't fill: emit `{}`
   so the convert-preview shows eligibility. **Name them exactly as live ASIK** (run the
   audit — name drift is the #1 issue).

## Naming = the #1 failure mode

Form names must equal the **live** ASIK name byte-for-byte (parens, slashes, "SKILAS"
prefixes, `=> N tahun`). The 2026-05-29 audit found 6 lansia shells drifted (`SPPB` vs
`(SPPB)`, `MNA-SF` vs `(MNA-SF)`, missing `/Barthel`, `SKILAS Malnutrisi`). Always settle
names against a fresh live dump, not an old spec sheet. `audit_coverage.py` flags these;
target 0.

## Don't

- Don't invent values absent from the source.
- Don't recompute things the merge owns (it sets presence, EPUS-wins value, status).
- Don't let a missing source key raise — `.get()` chains, return None.
- Don't use the clinical-union flag for the self-report parent radio.
