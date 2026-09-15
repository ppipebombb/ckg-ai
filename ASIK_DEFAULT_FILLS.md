# ASIK Sync — Default Values for Required Fields

**Goal:** let the robot submit a patient's ASIK forms even when ASIK *requires* a
question we have no data for — by putting a safe **default value** and **logging it**,
so reports can always tell real data from auto-filled.

> One line: *ASIK won't let us submit with blanks on required questions. So we fill
> the blanks with a safe default and write down exactly what we faked.*

---

## Where this sits in the flow

```
  EPUS scrape ─┐
               ├─►  AI Merge  ─►  merged_data  ─►  ┌──────────────┐
  ASIK scrape ─┘                                   │  SYNC (this) │ ─► forms submitted on ASIK
                                                    └──────────────┘
                                                    optional · per date · per puskesmas
                                                    (later: a Cron step)
```

The sync feature is **already built** but has **never run in production** (0 sync jobs).
The *only* thing blocking it: a form with a required question we can't fill is abandoned.
This change makes it fill-with-default instead.

---

## The rule per form

```
  For each form the patient has on ASIK:

     ≥1 real answer in that form ? ──NO──►  ⏭  SKIP the whole form (don't submit)
              │
             YES
              ▼
     ①  fill every field we DO have real data for
     ②  any REQUIRED field still empty?   ← read the "*" LIVE from the form
              └─ yes ─►  put a DEFAULT value   +   log {form, question, value}
     ③  click "Kirim"  ✔
```

*Why skip a form with 0 real answers?* Submitting a 100%-invented form (e.g. a mental-health
screen) adds no real data — so we don't. One real answer is enough to keep + complete the form.

---

## How a default is chosen

| Question type | Default we put | Example |
|---|---|---|
| **Yes/No · dropdown · choice** | the **clinically-safe pole**: a negative/normal *result* if the question has one, else `Tidak` (symptom absent), else the *best*-performance band | lab → **Negatif** · HIV → **Non Reaktif** · finding → **Normal** · risk → **Tidak** · mood (PHQ) → **Tidak sama sekali** · gait → **fastest band** |
| **Positive/abnormal result** | 🚫 **never auto-filled** — left blank so the form fails safe (skips) rather than submitting a fabricated diagnosis | EKG "abnormal-only", TB-type |
| **Number** | a fixed **clinically-normal, in-range** value (table below) | BB → **60 kg** · Hb → **13** · Sistolik → **120** |
| **Free text** | an obvious placeholder | **"-"** |
| **Age (Usia)** | 🚫 never faked — taken from the patient's birth date | — |

> **Why not just take ASIK's lowest `nilai_poin`?** Because ASIK's score is **not** a
> universal risk scale — on the newborn (SHK/G6PD/HAK) and geriatric (SPPB) forms it is
> *inverted*, so "lowest score" would default a congenital-disease screen to **Positif** and
> a mobility test to the *worst* band. We instead pick the explicit safe/negative option and
> **never** submit a positive/abnormal finding. (285 questions carry a documented default.)

> **Why not "all numbers = 50"?** 50 is impossible for Hb, and dangerous for blood pressure —
> it would also fail ASIK's own min/max check and re-block the submit. We instead use a
> normal value that's always valid. We can still spot every default because **we log all of them**.

### Every number field + its default (25 fields, all of ASIK)

| Field | Default | Valid range | Field | Default | Valid range |
|---|---|---|---|---|---|
| Berat Badan (kg) | **60** | 1–300 | Kolesterol Total | **180** | <200 |
| Tinggi Badan (cm) | **160** | 30–250 | LDL | **100** | <100 |
| Lingkar Perut (cm) | **80** | 30–200 | Trigliserida | **120** | <150 |
| Kadar Hemoglobin | **13** | 3–25 | HDL | **55** | >40 |
| Nilai SGOT | **25** | <35 | Kreatinin (serum) | **0.9** | 0.6–1.2 |
| Trombosit | **250 000** | 150k–400k | Ureum | **25** | 15–40 |
| GDS | **100** | <140 | e-LFG (eGFR) | **95** | >90 |
| GDP | **90** | <100 | Albumin Urin | **15** | <30 |
| GD 2 Jam PP | **110** | <140 | Kreatinin Urin | **100** | normal |
| Kadar CO napas | **3** | <6 | Sistolik / +ke-2 | **120** | normal |
| — | | | Diastolik / +ke-2 | **80** | normal |

*Specials:* **Usia** never defaulted (from DOB) · **GDS-2** only appears if GDS-1 is abnormal (usually hidden).

---

## ⚠ Critical: "required" is read LIVE, never trusted from a document

We found a real mismatch during this research:

```
   Our documented list says:   "Hati" form = 0/9 required  (all optional)
   Live ASIK today shows:      "Hati" form = 9/9 REQUIRED  (all have "*")
```

ASIK changes its rules over time. **So the robot reads the "*" on the live form at the
moment it fills** — the documentation is only a starting reference. This keeps us correct
even after ASIK silently changes which questions are mandatory. (A form's default *value*
comes from the policy above; whether it's *needed* is decided live.)

---

## What gets logged (the new column)

New column on the patient record — **`asik_default_fills`** (plain JSON, not encrypted):

```json
[
  { "layanan": "Tingkat Aktivitas Fisik", "question": "Apakah Anda melakukan olahraga…", "value": "Tidak", "kind": "radio" },
  { "layanan": "Faktor Risiko X-Ray TB",  "question": "Apakah Anda mengalami demam…",   "value": "Tidak", "kind": "radio" }
]
```

Every dashboard/report can then **subtract these** to separate *real measurements* from
*auto-filled placeholders*.

---

## Coverage

```
  ASIK total: 119 forms · 565 questions
  ├─ Documented safe default ...................... 285 questions (see ASIK_DEFAULTED_QUESTIONS.md)
  └─ Everything else ............................... handled LIVE at fill-time (safety-net rule)
```

Because the robot can compute a safe default from the live widget itself, **no patient's
form can get stuck** — even a question ASIK renders that the audit never captured (drift).
The live safety-net covers three drift cases proven on the GPAQ form:
- **radio/checkbox** — read the visible options, pick the safe/negative one;
- **dropdown** — open it, read its real options, pick the safe one (SurveyJS hides options
  until opened, so the enumerator can't see them — GPAQ Q3/Q5 were missing from the audit);
- **behavioural follow-up numbers** — "how many days/week", "how many minutes/day" appear
  once an activity is answered "Ya"; these get a minimal in-range value (1 day / 30 min).
  (Only activity-frequency numbers — an unknown *clinical* number, e.g. Hb, is still left blank.)

---

## Worked example — DEVINA AURELIA (adult ♀, Pekayon Jaya)

| Her forms | Real answers | What sync does |
|---|---|---|
| Gizi, Tekanan Darah, Gula Darah, Telinga/Mata, Karies, Demografi | full | already done — no action |
| Faktor Risiko TB | 1/1 | submit (no default needed) |
| Perilaku Merokok | 1/2 | submit **+ 1 default** |
| Tingkat Aktivitas Fisik | 1/6 | submit **+ 7 defaults** (5 activity-dropdown gaps + 2 number follow-ups revealed by her 1 real "Ya") |
| Faktor Risiko X-Ray TB | 1/6 | submit **+ 5 defaults** |
| Hati, Kesehatan Jiwa, TB, Fibrosis, Hepatitis, HIV, Sifilis, Hemoglobin, Frambusia, Kusta, Skabies, Kadar CO, Catin | 0 | ⏭ **skipped** |

> Note: every *lab-result* form (HIV, Sifilis, Hepatitis, Hemoglobin…) is skipped for her
> anyway — she has zero real data in each — so defaults only ever touch partial questionnaires.
> **Other patients differ** — a lansia or a laki-laki carries different forms; the live rule covers them all.

---

## Cron integration (`sync_mode`) — optional, off by default

The sync can run automatically after the cron **merge** step, on both cron surfaces
(the "Run for date range" backfill and the scheduled Cron config). A `sync_mode`
setting mirrors `merge_mode`:

| `sync_mode` | What the cron SYNC step does |
|---|---|
| **off** (default) | no sync — run stops after merge |
| **normal** | sync patients merged for that date that are **not yet synced** (`asik_synced_at IS NULL`) |
| **force_resync** | re-sync **all** eligible patients for that date (ignores the guard) |

- The step runs all eligible patients **sequentially in one ASIK session** (one login —
  ASIK is one-account-per-login). It's skipped entirely when `merge_mode = no_merge`.
- `patients.asik_synced_at` is stamped on a successful sync (manual button too), **only when
  no form failed** — so `normal` retries a patient whose forms hit a transient error.
- **Re-submit updates in place** (ASIK keys a screening by patient+date), so `force_resync`
  is a deliberate "push again", not a duplicate. Use it after fixing data.
- **Gap:** `normal` skips any already-synced patient, so **re-merged data is not re-pushed**
  by `normal` — use `force_resync` after a re-merge to send corrected data.
- **Only matched + AI-merged data is ever submitted.** Sync requires `merged_data` on every
  path (cron + manual button). The old EPUS-only fallback (submit raw ePus, no AI merge) is
  disabled behind `ALLOW_EPUS_ONLY_SYNC=False` (kept for later, not deleted).
- **Scheduled lookback window:** the Cron schedule has `lookback_days` (default **3**). Each
  fire re-processes the last N days (spawns a backfill over `[target-(N-1)..target]`) so
  late-arriving ePus/ASIK that only matches a past date once **both** sides land still gets
  scraped → matched → merged → (optionally) synced. `1` = today's single-day behavior.

---

## Implementation plan (for a later, separate go — no code changed yet)

1. **DB** — add `asik_default_fills` JSONB column on `patients` (one migration).
2. **Sync scraper** (`scrapers/asik_sync/sync.py`) — after filling real data, read the
   live required-but-empty fields; for each, look up / compute a default → fill → record it.
   Replace the current *"incomplete → abandon"* branch with *"default → submit"*.
3. **Skip-if-empty** — if a form has 0 real answers, skip it (don't submit).
4. **Backend** (`tasks/sync.py`) — save the recorded defaults into `patients.asik_default_fills`.
5. **Later / optional** — add the sync step to the per-puskesmas Cron (after merge).

*Implemented on branch `akbar/sync-job` (not yet committed/deployed). The full per-question
default list is in `documents/ASIK_DEFAULTED_QUESTIONS.md`.*
