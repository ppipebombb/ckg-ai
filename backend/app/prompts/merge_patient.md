# Merge a patient's ePuskesmas + ASIK records — conflict review

You receive TWO JSON inputs for the SAME patient (same NIK):

1. **EPUS** (input 1) — this patient's ePuskesmas data already converted into ASIK form shape: `{<form_name>: {<field>: <value>}}`. It is the **default source of truth**. Klaster gating, chronic-disease flags, conditional reveals, and value coercion are already applied — **never recompute them**. (You DO still sanity-check each EPUS *value* for plausibility — see **Plausibility check** — but you never recompute the gating/flag logic above.)
2. **ASIK** (input 2) — the raw ASIK scrape: `pelayanan_nakes[]` and `pemeriksaan_mandiri[]`, each entry `{"layanan": <form_name>, "form_data": {<field>: <value>}}`. (Patient identity is **not** included — the backend builds the identity section itself. `identitas_pasien` in input 1 carries only `Jenis Kelamin` / `Tanggal Lahir` / `Tempat Lahir` as context for the plausibility check below; never emit identity items.)

Both inputs are the same NIK. Never match by name, age, or DOB.

## Your only job

Find every field where **BOTH** sources have a non-null value, and decide whether the two values **agree** or **conflict**. The backend deterministically fills in every other field — one-sided fields, empty fields, and patient identity — from the sources, so **do not emit those**. Emitting only the focused both-filled items keeps the output small and reliable.

## Output — return ONLY this raw JSON object

No markdown fences. No commentary before or after. The whole reply must parse as one JSON object.

```json
{"nik":"<NIK>","match_status":"matched","sections":{"<ASIK form name>":[<item>, ...]}}
```

- Section key = the **ASIK form name, verbatim** — e.g. `"Tekanan Darah Dewasa Lansia"`. Do **not** slugify; the backend does that.
- Each item:

```json
{"merged_key":"<ASIK field label, verbatim>","merged_value":<chosen value>,
 "asik_question":"","epus_question":"","asik_value":<raw ASIK value>,
 "epus_value":<raw EPUS value>,"reasoning":"","is_same_answer":<bool>,
 "is_conflict":<bool>,"epus_implausible":<bool>}
```

- `merged_key`: the field label, verbatim (units included).
- `merged_value`: the **EPUS** value by default (ePuskesmas wins). **Exception:** when you set `epus_implausible: true`, use the plausible **ASIK** value instead (see **Plausibility check**).
- `asik_question`, `epus_question`: always `""` — the backend rebuilds them.
- `reasoning`: `""`, except when `is_conflict: true`.
- `epus_implausible`: `false` by default. `true` only when the EPUS value is physically/clinically impossible for this patient AND ASIK is plausible (see **Plausibility check**).

## Agree vs conflict

Match each EPUS form to the ASIK form by name, and fields by their label. For every field where both sides have a value:

| The two values are… | is_conflict | is_same_answer |
|---|---|---|
| Equal after lowercasing + numeric tolerance (ints equal, floats within 0.5) — e.g. `168`=`168.0`, `"Ya"`=`"ya"` | false | false |
| Different in surface form but the same meaning — e.g. `"Laki-laki"`/`"Male"` | false | true |
| Genuinely different — numbers beyond tolerance, or different categories (`"Ya"` vs `"Tidak"`) | **true** | false |

When `is_conflict: true` (and NOT an implausible-EPUS case), write `reasoning` in Bahasa Indonesia: state both values and which is more clinically plausible — adult height should be stable, so 158 vs 150 cm is suspect; blood pressure / blood glucose / weight can legitimately vary between visits — and end with `Nilai akhir mengikuti ePuskesmas.`

## Plausibility check (reason again before trusting EPUS)

ePuskesmas wins **only when its value is physically possible for this patient**. Before you finalize each both-filled field, re-read the EPUS value and sanity-check it against the patient's other data — height and `Tinggi Badan`, age (from `identitas_pasien` → `Tanggal Lahir`), sex — and against real-world ranges. Data-entry slips happen in EPUS: a weight typed `2` instead of `62`, a height `15` instead of `150`.

If the EPUS value is **physically impossible or clinically nonsensical** for this patient AND the ASIK value is plausible, then:

- set `is_conflict: true` **and** `epus_implausible: true`,
- set `merged_value` to the **ASIK** value (the plausible one),
- in `reasoning` (Bahasa Indonesia) state both values, why EPUS is implausible (cite the conflicting context — e.g. an adult's height/age), and end with `Nilai akhir mengikuti ASIK karena nilai ePuskesmas tidak masuk akal.`

Implausible examples: an adult `Berat Badan (Kg)` of `2`; a `Tinggi Badan` of `15`; a measurement impossible for the patient's age/sex.

**Be conservative.** Values that legitimately differ between visits — blood pressure, blood glucose, a believable weight change (e.g. 58 vs 62 kg) — are **normal conflicts**, NOT implausible: leave `epus_implausible: false`, keep `merged_value` = EPUS, and end the reasoning with `Nilai akhir mengikuti ePuskesmas.` Only flag values that genuinely cannot be true.

## Rules

- Emit an item **only** for fields where BOTH sources have a non-null value. Skip one-sided fields, empty fields, and identity — the backend adds them.
- `merged_value` is the EPUS value, **except** when you set `epus_implausible: true` — then it is the ASIK value.
- Never invent a value. Never recompute klaster, flags, age, ICDX, or conditional reveals.

## Inputs follow.
