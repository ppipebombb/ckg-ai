import json
import logging
import re
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from app.celery_app import celery_app
from app.config import settings
from app.core.resource_sampler import ResourceSampler
from app.core.security import decrypt_json, encrypt_json
from app.crud import llm_config as llm_config_crud
from app.crud import llm_log as llm_log_crud
from app.crud import merge_job as merge_job_crud
from app.crud import patient as patient_crud
from app.database import SessionLocal
from app.integrations.llm_chat import ChatResult, chat_complete
from app.models.merge_job import MergeJob, MergeStatus
from app.models.patient import MatchStatus, Patient
from app.data.paket_map import LAINNYA_PAKET_NAME, LAINNYA_PAKET_SLUG, paket_for
from app.services.epus_to_asik import EPUS_BREADCRUMBS, epus_to_asik

log = logging.getLogger(__name__)

_PER_MILLION = Decimal("1000000")
LOG_RING_MAX = 500
LOG_TTL_SECONDS = 86400

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "merge_patient.md"


_JOB_TASK_COLS = (
    MergeJob.id, MergeJob.puskesmas_id, MergeJob.patient_id,
    MergeJob.date_filter, MergeJob.status,
    MergeJob.celery_task_id, MergeJob.force_remerge, MergeJob.total_count,
    MergeJob.processed_count, MergeJob.succeeded_count, MergeJob.failed_count,
    MergeJob.skipped_count, MergeJob.duration_seconds, MergeJob.notes,
    MergeJob.started_at, MergeJob.finished_at, MergeJob.error_message,
)

_PATIENT_COLS = (
    Patient.id, Patient.nik, Patient.nama, Patient.match_status,
    Patient.scraped_asik_data, Patient.scraped_epus_data,
    Patient.merged_at, Patient.filter_date, Patient.match_group_id,
)


# (section_slug_substring, parent_field_substring, trigger_value,
# child_field_substrings) — children only valid when the rule's section
# contains a parent whose merged_value matches the trigger. Section anchor
# prevents a parent label substring from matching across unrelated forms.
_CONDITIONAL_REVEALS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "tekanan_darah",
        "pernah dinyatakan tekanan darah tinggi",
        "Ya",
        ("Sudah Berapa Bulan Anda Didiagnosis Hipertensi",),
    ),
    (
        "gula_darah",
        "pernah dinyatakan diabetes",
        "Ya",
        ("Sudah Berapa Bulan Anda Didiagnosis Diabetes",),
    ),
    (
        "ppok",
        "sedang/mempunyai riwayat merokok",
        "Iya",
        ("Jika Perokok Aktif, berapa bungkus per tahun",),
    ),
    (
        "telinga_dan_mata",
        "hasil skrining tajam penglihatan",
        "Curiga gangguan penglihatan",
        ("Hasil pemeriksaan visus",),
    ),
)


def _slugify_form(form_name: str) -> str:
    """Mirror the slug rules documented in merge_patient.md.

    Lowercase; replace ``=>`` with ``di_atas``; strip ``()/-&`` punctuation;
    replace remaining non-alphanumerics with ``_``; collapse repeats; trim.
    Preserves a literal ``identitas_pasien`` key (already a slug).
    """
    if form_name == "identitas_pasien":
        return form_name
    s = form_name.lower().replace("=>", " di_atas ")
    s = re.sub(r"[()/&\-]", " ", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# Built once at module load — slug → ASIK form name. Used by the post-
# processor to rewrite epus_question after the LLM emits the merged JSON.
_SLUG_TO_FORM: dict[str, str] = {
    _slugify_form(name): name for name in EPUS_BREADCRUMBS
}


def _overwrite_epus_questions(merged: dict) -> dict:
    """Replace LLM-supplied ``epus_question`` with canonical truth.

    Lookup table is :data:`EPUS_BREADCRUMBS` in the converter.
    Three semantic cases, each producing a definite ``epus_question``:

    - **Section in table, field in form's map with a string path**: use
      that path.
    - **Section in table, field in form's map with explicit ``None``**:
      EPUS truly has no counterpart for this field (e.g. ``Sudah Berapa
      Bulan...`` — converter emits the key with value ``None`` to mirror
      ASIK's conditional reveal, but no EPUS data backs it). Force
      ``epus_question = None``.
    - **Section in table, field NOT in form's map**: ASIK-only field
      within a shared form (e.g. ``Sistolik Ke-2`` in Tekanan Darah).
      Force ``epus_question = None``.
    - **Section slug NOT in table at all**: ASIK-only form (Faktor Risiko
      TB, Hati, etc.). Force every item's ``epus_question = None``.

    The LLM's fallback (mirroring the ASIK slug) never survives this pass.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for section_key, items in sections.items():
        if not isinstance(items, list):
            continue
        form_name = _SLUG_TO_FORM.get(section_key)
        if form_name is None:
            for it in items:
                if isinstance(it, dict):
                    it["epus_question"] = None
            continue
        field_map = EPUS_BREADCRUMBS[form_name]
        for it in items:
            if not isinstance(it, dict):
                continue
            key = it.get("merged_key")
            if not isinstance(key, str):
                continue
            it["epus_question"] = field_map.get(key)
    return merged


def _values_equal(a: Any, b: Any) -> bool:
    """Numeric-tolerant / case-insensitive value equality.

    Mirrors the ``_num`` coercion in epus_to_asik so ``"168"`` vs ``168.0``
    counts as identical. Booleans compared exactly. Either side ``None``
    short-circuits to ``False`` (one_source status is decided elsewhere).
    """
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    try:
        fa = float(str(a).replace(",", "."))
        fb = float(str(b).replace(",", "."))
    except (ValueError, TypeError):
        return str(a).strip().lower() == str(b).strip().lower()
    if fa.is_integer() and fb.is_integer():
        return int(fa) == int(fb)
    return abs(fa - fb) < 0.5


def _enforce_merged_value(merged: dict) -> dict:
    """Force ``merged_value = asik_value`` when EPUS lacks the value.

    The merge prompt's default rule is "EPUS wins" — but when input 1
    contains a field whose value is ``null`` (converter emitted the key
    as a placeholder for a conditional-reveal child or an unmapped EPUS
    path) and ASIK has a real value, the LLM sometimes still picks
    ``null`` for ``merged_value``. That would discard a perfectly good
    ASIK value. Force the ASIK side to win here.

    Identical semantic case: a converted EPUS form has only a partial
    set of fields populated; ASIK fields without an EPUS counterpart
    should carry through to ``merged_value`` rather than being nulled
    by the "EPUS wins" default.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for items in sections.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("epus_value") is not None:
                continue
            asik = it.get("asik_value")
            if asik is None:
                continue
            it["merged_value"] = asik
    return merged


def _normalize_status_flags(merged: dict) -> dict:
    """Deterministically set is_conflict / is_same_answer from value state.

    Status must not depend on which model ran the merge. Applied to every item
    (LLM-emitted or backend-added):

    - one side null (or both)  → not a conflict, not same-answer.
    - both present, value-equal (numeric-tolerant / case-insensitive)
      → "Sesuai": not a conflict, not same-answer. (Kills the ``168`` vs ``168``
      and NIK-equal false positives.)
    - both present, differ, in ``identitas_pasien`` → never a conflict (patient
      matched by NIK; a formatting/detail difference is "Makna Sama"), so
      is_same_answer=True.
    - both present, differ, in a clinical form → conflict, deterministically.
      The converter already normalises EPUS to ASIK vocabulary, so a remaining
      difference is a real disagreement (0 genuine same-meaning cases observed
      across the whole benchmark). Flagging it here rather than trusting the
      LLM removes the last source of cross-model / run-to-run variance — status
      now depends only on the values, never on the model.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for sk, items in sections.items():
        is_identitas = sk == "identitas_pasien"
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            a, e = it.get("asik_value"), it.get("epus_value")
            if a is None or e is None:
                it["is_conflict"] = False
                it["is_same_answer"] = False
            elif _values_equal(a, e):
                it["is_conflict"] = False
                it["is_same_answer"] = False
            elif is_identitas:
                it["is_conflict"] = False
                it["is_same_answer"] = True
            else:
                it["is_conflict"] = True
                it["is_same_answer"] = False
    return merged


def _drop_orphan_conditional_children(merged: dict) -> dict:
    """Remove conditional-reveal child entries whose parent didn't trigger.

    Defensive: each rule is anchored to a specific section slug substring so a
    parent label cannot match in an unrelated form. Within the matched
    section, find the parent; if its ``merged_value`` doesn't contain the
    trigger as a whole-word substring (case-insensitive), drop matching
    children.

    Word-boundary substring (rather than plain ``in``) protects against enum
    drift while keeping short triggers like ``Ya`` / ``Iya`` from matching
    inside unrelated words (e.g. ``Saya``). The ASIK Skrining Telinga & Mata
    visus enum is ``Curiga gangguan penglihatan (visus <6/12)`` but the
    trigger is the short prefix ``Curiga gangguan penglihatan``; the
    word-boundary check still matches because the prefix ends at a space.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for section_anchor, parent_substr, trigger, child_substrs in _CONDITIONAL_REVEALS:
        for section_key, items in sections.items():
            if not isinstance(items, list):
                continue
            if section_anchor not in section_key.lower():
                continue
            parent = next(
                (
                    it for it in items
                    if isinstance(it, dict)
                    and isinstance(it.get("merged_key"), str)
                    and parent_substr.lower() in it["merged_key"].lower()
                ),
                None,
            )
            if parent is None:
                continue
            mv = parent.get("merged_value")
            parent_matches_trigger = isinstance(mv, str) and re.search(
                rf"\b{re.escape(trigger)}\b", mv.strip(), re.IGNORECASE
            ) is not None
            if parent_matches_trigger:
                continue
            items[:] = [
                it for it in items
                if not (
                    isinstance(it, dict)
                    and isinstance(it.get("merged_key"), str)
                    and any(
                        cs.lower() in it["merged_key"].lower()
                        for cs in child_substrs
                    )
                )
            ]
    return merged


def _extract_asik_form_names(asik: dict) -> dict[str, str]:
    """Build slug → ASIK form name map from a patient's raw ASIK record.

    Walks both ``pelayanan_nakes[]`` and ``pemeriksaan_mandiri[]`` and
    keys each entry's ``layanan`` by its slugified form. Used downstream
    to backfill ``asik_question`` for ASIK-only forms (whose slug is not
    in :data:`_SLUG_TO_FORM`).
    """
    out: dict[str, str] = {}
    if not isinstance(asik, dict):
        return out
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("layanan")
            if isinstance(name, str) and name:
                out[_slugify_form(name)] = name
    return out


def _backfill_asik_questions(merged: dict, asik_slug_to_form: dict[str, str]) -> dict:
    """Reconstruct ``asik_question`` = ``"<form_name> > <merged_key>"``.

    The merge prompt instructs the LLM to emit ``asik_question: ""`` to
    save tokens. This pass rebuilds the breadcrumb server-side using
    :data:`_SLUG_TO_FORM` (forms also present in EPUS) and the
    patient-specific ``asik_slug_to_form`` map (ASIK-only forms).

    Falls back to the slug itself when neither map has a match — better
    than leaving the field empty and breaking the frontend's display.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for section_key, items in sections.items():
        if section_key == "identitas_pasien":
            form_name = "identitas_pasien"
        else:
            form_name = (
                _SLUG_TO_FORM.get(section_key)
                or asik_slug_to_form.get(section_key)
                or section_key
            )
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            key = it.get("merged_key")
            if isinstance(key, str) and key:
                it["asik_question"] = f"{form_name} > {key}"
    return merged


def _slugify_section_keys(merged: dict) -> dict:
    """Normalise LLM section keys to canonical slugs.

    The prompt asks the LLM to key each section by the ASIK form NAME (not a
    hand-slugified string) — LLMs slugify inconsistently, and a mis-slugged key
    orphans the section from every downstream lookup (``_SLUG_TO_FORM``,
    paket map). We slugify here with the same :func:`_slugify_form` the rest of
    the pipeline uses, so the LLM never has to. Idempotent on keys that are
    already slugs. Two keys collapsing to the same slug have their item lists
    merged.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    new: dict[str, Any] = {}
    for k, v in sections.items():
        slug = "identitas_pasien" if k == "identitas_pasien" else _slugify_form(k)
        if slug in new and isinstance(new[slug], list) and isinstance(v, list):
            new[slug].extend(v)
        else:
            new[slug] = v
    merged["sections"] = new
    return merged


def _complete_source_fields(merged: dict, converted_epus: dict, asik: dict) -> dict:
    """Deterministically reconcile field PRESENCE and raw values from sources.

    Field presence and raw values are mechanical — a field exists iff a source
    has it, and its asik/epus values ARE the source values. Leaving this to the
    LLM produced large cross-model swings in one-sided ("Terisi Salah Satu")
    fields (e.g. 18 vs 47 on the same patient) because a field one model emits
    another silently drops, and let models mis-transcribe values. The backend
    now owns it, so the displayed field set is identical regardless of model.

    Build ``{(slug, field): (asik, epus)}`` from converted EPUS ∪ raw ASIK
    (``pelayanan_nakes`` + ``pemeriksaan_mandiri``). Then per (slug, field):

    - already in ``merged`` → overwrite ``asik_value`` / ``epus_value`` /
      ``merged_value`` from the source (keep the LLM's ``is_conflict`` /
      ``is_same_answer`` / ``reasoning`` — its judgment on both-filled fields).
    - missing → append a row with deterministic values and status.

    ``merged_value`` = epus if not None else asik (ePuskesmas wins; ASIK fills).
    An ADDED row is a conflict only when both sides are present and not
    value-equal. ``identitas_pasien`` is skipped — :func:`_rebuild_identitas`
    owns it (its ASIK side lives in ``detail_data``, not the form arrays).
    """
    # NB: not ``setdefault`` — a model can legitimately emit ``"sections": null``
    # (which _validate_merge_shape permits), and setdefault returns that None.
    # Coerce so completion still runs and builds the full set from source.
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        sections = merged["sections"] = {}

    field_map: dict[tuple[str, str], dict] = {}

    def _seed(form: str, field: str, side: str, val: Any) -> None:
        slug = _slugify_form(form)
        if slug == "identitas_pasien":
            return
        rec = field_map.get((slug, field))
        if rec is None:
            rec = {"asik": None, "epus": None, "form": form}
            field_map[(slug, field)] = rec
        rec[side] = val
        if side == "asik":  # prefer the live ASIK layanan name for breadcrumbs
            rec["form"] = form

    if isinstance(converted_epus, dict):
        for form, fields in converted_epus.items():
            if isinstance(form, str) and isinstance(fields, dict):
                for field, val in fields.items():
                    if isinstance(field, str):
                        _seed(form, field, "epus", val)
    if isinstance(asik, dict):
        for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
            for entry in asik.get(arr_key) or []:
                if not isinstance(entry, dict):
                    continue
                form = entry.get("layanan")
                form_data = entry.get("form_data")
                if isinstance(form, str) and form and isinstance(form_data, dict):
                    for field, val in form_data.items():
                        if isinstance(field, str):
                            _seed(form, field, "asik", val)

    existing: dict[tuple[str, str], dict] = {}
    for sk, items in sections.items():
        if sk == "identitas_pasien" or not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("merged_key"), str):
                existing[(sk, it["merged_key"])] = it

    for (slug, field), rec in field_map.items():
        asik_v, epus_v = rec["asik"], rec["epus"]
        merged_v = epus_v if epus_v is not None else asik_v
        row = existing.get((slug, field))
        if row is not None:
            # Source owns the raw values; the LLM keeps its conflict judgment on
            # this both-filled field.
            row["asik_value"] = asik_v
            row["epus_value"] = epus_v
            # EPUS wins the merged value by default. Exception: the LLM may flag
            # the EPUS value as physically/clinically implausible for this
            # patient (e.g. a 2 kg adult weight — a data-entry typo). When it
            # does AND ASIK has a value, honour the plausible ASIK value. This
            # is the one field whose merged_value the LLM is allowed to steer
            # away from the EPUS-wins default.
            if row.get("epus_implausible") is True and asik_v is not None:
                row["merged_value"] = asik_v
            else:
                row["merged_value"] = merged_v
            continue
        items = sections.get(slug)
        if not isinstance(items, list):
            items = sections[slug] = []
        both = asik_v is not None and epus_v is not None
        is_conf = both and not _values_equal(asik_v, epus_v)
        items.append(
            {
                "merged_key": field,
                "merged_value": merged_v,
                "asik_question": "",
                "epus_question": "",
                "asik_value": asik_v,
                "epus_value": epus_v,
                "reasoning": _REASONING_AUTO_CONFLICT if is_conf else "",
                "is_same_answer": False,
                "is_conflict": is_conf,
                # Backend-added rows are never an implausible-EPUS override —
                # only the LLM, seeing both raw values, can make that call.
                "epus_implausible": False,
            }
        )

    # Prune orphan / hallucinated rows: any non-identitas item whose
    # (slug, field) is not a real source field. Catches a model emitting an
    # abbreviated form name (wrong slug → duplicate section) or inventing a
    # field/value. The correct row was already (re)built above from source.
    valid = set(field_map.keys())
    for sk in list(sections.keys()):
        if sk == "identitas_pasien":
            continue
        items = sections[sk]
        if not isinstance(items, list):
            continue
        kept = [
            it for it in items
            if isinstance(it, dict) and (sk, it.get("merged_key")) in valid
        ]
        if kept:
            sections[sk] = kept
        else:
            del sections[sk]
    return merged


# ASIK identitas lives in detail_data, not the form arrays. Field → (block, key).
_IDENTITAS_ASIK_MAP: dict[str, tuple[str, str]] = {
    "NIK": ("data_individu", "NIK"),
    "Nama": ("data_individu", "Nama"),
    "Tanggal Lahir": ("data_individu", "Tanggal Lahir"),
    "Jenis Kelamin": ("data_individu", "Jenis Kelamin"),
    "Tempat Lahir": ("data_individu", "Tempat Lahir"),
    "Alamat Domisili": ("data_domisili", "Alamat Domisili"),
}


def _rebuild_identitas(merged: dict, converted: dict, asik: dict) -> dict:
    """Replace ``identitas_pasien`` with a deterministic, source-built section.

    Identitas is pure lookup — EPUS side from the converter's normalised
    ``identitas_pasien`` form, ASIK side from ``detail_data.data_individu`` /
    ``data_domisili``. It needs no LLM judgment (the patient is matched by NIK),
    yet leaving it to the LLM produced cross-model status flips (one model
    calling NIK a conflict, another a match). Build it identically every time.

    ``merged_value`` follows ASIK (the authoritative source for patient
    identity) when present, else the ePuskesmas value — ASIK-wins, the INVERSE
    of the EPUS-wins rule used for clinical fields, because the patient's own
    ASIK record is the system of record for identity; EPUS only fills gaps.
    Status is set later by :func:`_normalize_status_flags` (equal → consistent;
    differ → same-meaning, never a conflict).
    """
    conv_id = (converted or {}).get("identitas_pasien") or {}
    detail = (asik or {}).get("detail_data") or {}
    di = detail.get("data_individu") or {}
    dom = detail.get("data_domisili") or {}
    if not isinstance(conv_id, dict):
        conv_id = {}
    fields = list(dict.fromkeys(list(conv_id.keys()) + list(_IDENTITAS_ASIK_MAP.keys())))
    items: list[dict] = []
    for field in fields:
        epus_v = conv_id.get(field)
        block, key = _IDENTITAS_ASIK_MAP.get(field, (None, None))
        if block == "data_individu":
            asik_v = di.get(key) if isinstance(di, dict) else None
        elif block == "data_domisili":
            asik_v = dom.get(key) if isinstance(dom, dict) else None
        else:
            asik_v = None
        if epus_v is None and asik_v is None:
            continue
        items.append(
            {
                "merged_key": field,
                "merged_value": asik_v if asik_v is not None else epus_v,
                "asik_question": "",
                "epus_question": "",
                "asik_value": asik_v,
                "epus_value": epus_v,
                "reasoning": "",
                "is_same_answer": False,
                "is_conflict": False,
                "epus_implausible": False,
            }
        )
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        sections = merged["sections"] = {}
    sections["identitas_pasien"] = items
    return merged


# Identitas fields kept in the LLM input: sex + DOB + birthplace give the
# value-plausibility check its age/sex context. Everything else — NIK, Nama,
# Alamat Domisili, and the raw ASIK detail_data (phone, guardian, occupation,
# ticket, domicile) — is withheld, since the backend builds the identitas
# section deterministically (:func:`_rebuild_identitas`) and never needs it.
_IDENTITAS_LLM_KEEP = ("Jenis Kelamin", "Tanggal Lahir", "Tempat Lahir")


def _strip_identitas_for_llm(converted: dict) -> dict:
    """Return a shallow copy of ``converted`` whose ``identitas_pasien`` form
    keeps only the plausibility-context fields (:data:`_IDENTITAS_LLM_KEEP`).

    The original ``converted`` is untouched — the deterministic identitas
    rebuild (:func:`_rebuild_identitas`) still consumes the full form.
    """
    if not isinstance(converted, dict) or "identitas_pasien" not in converted:
        return converted
    identitas = converted.get("identitas_pasien")
    trimmed = {
        k: identitas[k]
        for k in _IDENTITAS_LLM_KEEP
        if isinstance(identitas, dict) and k in identitas
    }
    out = dict(converted)
    if trimmed:
        out["identitas_pasien"] = trimmed
    else:
        out.pop("identitas_pasien", None)
    return out


_IDENTITAS_SUB_NAME = "Identitas Pasien"
_IDENTITAS_SUB_SLUG = "identitas_pasien"


def _gender_from_converted(converted: dict | None) -> str | None:
    """Pull `Jenis Kelamin` from converted EPUS identitas_pasien to seed paket
    gender disambiguation. Returns ``"Perempuan"`` / ``"Laki-laki"`` / ``None``.

    Falls back to inferring from section names containing `_perempuan`
    / `_laki_laki` so paket lookup still works when identitas is incomplete.
    """
    if not isinstance(converted, dict):
        return None
    identitas = converted.get("identitas_pasien") or {}
    jk = identitas.get("Jenis Kelamin") if isinstance(identitas, dict) else None
    if isinstance(jk, str):
        low = jk.strip().lower()
        if low in {"perempuan", "p", "female"}:
            return "Perempuan"
        if low in {"laki-laki", "laki laki", "l", "male"}:
            return "Laki-laki"
    return None


def _gender_from_section_slug(section_slug: str, fallback: str | None) -> str | None:
    """Refine gender by section slug — e.g. `..._perempuan` overrides converter."""
    s = section_slug.lower()
    if "perempuan" in s:
        return "Perempuan"
    if "laki_laki" in s or "_laki" in s:
        return "Laki-laki"
    return fallback


def _asik_form_sequence(asik: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Canonical section + field order from the raw ASIK scrape.

    Walks ``pelayanan_nakes[]`` then ``pemeriksaan_mandiri[]`` in array order —
    the order ASIK itself presents the forms — returning ``(section_slug order,
    {slug: [field, ...]})``. This is the "follow the ASIK form" ordering used to
    make the merged output deterministic regardless of which model ran.
    """
    section_order: list[str] = []
    field_order: dict[str, list[str]] = {}
    if not isinstance(asik, dict):
        return section_order, field_order
    for arr_key in ("pelayanan_nakes", "pemeriksaan_mandiri"):
        for entry in asik.get(arr_key) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("layanan")
            if not isinstance(name, str) or not name:
                continue
            slug = _slugify_form(name)
            fields = field_order.get(slug)
            if fields is None:
                fields = field_order[slug] = []
                section_order.append(slug)
            form_data = entry.get("form_data")
            if isinstance(form_data, dict):
                for f in form_data:
                    if isinstance(f, str) and f not in fields:
                        fields.append(f)
    return section_order, field_order


def _epus_form_sequence(converted: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Same shape as :func:`_asik_form_sequence`, from the converted EPUS dict.

    Used as the fallback order for forms / fields ASIK does not have, so an
    EPUS-only section still lands in a stable place with stable item order.
    """
    section_order: list[str] = []
    field_order: dict[str, list[str]] = {}
    if not isinstance(converted, dict):
        return section_order, field_order
    for form, fields in converted.items():
        if not isinstance(form, str) or not isinstance(fields, dict):
            continue
        slug = _slugify_form(form)
        cur = field_order.get(slug)
        if cur is None:
            cur = field_order[slug] = []
            section_order.append(slug)
        for f in fields:
            if isinstance(f, str) and f not in cur:
                cur.append(f)
    return section_order, field_order


def _order_by_asik(merged: dict, converted: dict, asik: dict) -> dict:
    """Reorder sections + items into a deterministic, ASIK-form-driven order.

    Section order: ``identitas_pasien`` first, then forms in the order the raw
    ASIK scrape lists them, then EPUS-only forms in converter order, then any
    leftover (stable). Within each section, items follow the ASIK ``form_data``
    field order (converted-EPUS field order as fallback); fields not found in
    either keep their relative order at the end (stable sort).

    Runs on the flat-list shape, BEFORE :func:`_group_into_pakets` — the
    grouping preserves both the section-key order and the per-section item
    order, so the paket sub-sections inherit this ASIK-driven sequence too.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged

    asik_secs, asik_fields = _asik_form_sequence(asik)
    epus_secs, epus_fields = _epus_form_sequence(converted)

    # 1) Section order.
    canonical: list[str] = []
    seen: set[str] = set()

    def _add(slug: str) -> None:
        if slug and slug not in seen:
            seen.add(slug)
            canonical.append(slug)

    _add("identitas_pasien")
    for s in asik_secs:
        _add(s)
    for s in epus_secs:
        _add(s)
    for s in sections:  # leftovers (e.g. ASIK-only forms) in current order
        _add(s)
    ordered = {s: sections[s] for s in canonical if s in sections}

    # 2) Item order within each section. identitas keeps _rebuild_identitas order.
    for slug, items in ordered.items():
        if slug == "identitas_pasien" or not isinstance(items, list):
            continue
        seq = list(asik_fields.get(slug, ()))
        for f in epus_fields.get(slug, ()):  # EPUS fields ASIK doesn't have
            if f not in seq:
                seq.append(f)
        if not seq:
            continue
        idx = {f: i for i, f in enumerate(seq)}

        def _pos(it: Any) -> int:
            key = it.get("merged_key") if isinstance(it, dict) else None
            return idx.get(key, len(seq))

        items.sort(key=_pos)

    merged["sections"] = ordered
    return merged


def _group_into_pakets(merged: dict, converted: dict, asik: dict) -> dict:
    """Regroup each section's flat ``items`` list into paket sub-sections.

    Input shape (post-prior-processors):
    ``sections[<layanan_slug>] = [item, item, ...]``

    Output shape:
    ``sections[<layanan_slug>] = {
        "layanan_label": "<paket parent name>",
        "sub_sections": {
            "<paket_slug>": {"label": "<paket name>", "items": [item, ...]},
            ...
        }
    }``

    Paket resolution per item uses :func:`app.data.paket_map.paket_for` which
    combines theme keywords + a global label→paket index. Items whose paket
    cannot be resolved bucket into ``"lainnya"``. The synthetic
    ``identitas_pasien`` section gets a single ``identitas_pasien`` sub-section.

    Sub-sections render in the order each paket is first seen while walking
    the flat item list — mirrors ASIK PROD's UI grouping for the layanan.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged

    gender_seed = _gender_from_converted(converted)
    # slug → layanan_name from both EPUS-side and ASIK-side maps.
    slug_to_layanan = {**_SLUG_TO_FORM, **_extract_asik_form_names(asik)}

    new_sections: dict[str, dict] = {}
    for section_slug, items in sections.items():
        if not isinstance(items, list):
            continue
        if section_slug == "identitas_pasien":
            new_sections[section_slug] = {
                "layanan_label": _IDENTITAS_SUB_NAME,
                "sub_sections": {
                    _IDENTITAS_SUB_SLUG: {
                        "label": _IDENTITAS_SUB_NAME,
                        "items": [it for it in items if isinstance(it, dict)],
                    }
                },
            }
            continue
        layanan_label = slug_to_layanan.get(section_slug, section_slug)
        gender = _gender_from_section_slug(section_slug, gender_seed)
        order: list[str] = []
        sub_map: dict[str, dict] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            key = it.get("merged_key")
            if not isinstance(key, str):
                continue
            paket_name, paket_slug = paket_for(layanan_label, key, gender)
            if paket_slug is None:
                paket_name, paket_slug = LAINNYA_PAKET_NAME, LAINNYA_PAKET_SLUG
            it["sub_section_slug"] = paket_slug
            it["sub_section_label"] = paket_name
            if paket_slug not in sub_map:
                sub_map[paket_slug] = {"label": paket_name, "items": []}
                order.append(paket_slug)
            sub_map[paket_slug]["items"].append(it)
        new_sections[section_slug] = {
            "layanan_label": layanan_label,
            "sub_sections": {slug: sub_map[slug] for slug in order},
        }

    merged["sections"] = new_sections
    return merged


def _drop_null_null_entries(merged: dict) -> dict:
    """Remove entries where merged_value, asik_value, and epus_value are all null.

    These rows carry zero information — they exist only because the LLM
    walked every ASIK form field and dutifully emitted a row even when
    neither side had data. The downstream sync runner skips
    null-merged_value rows anyway. Dropping here is also what keeps the
    LLM output under DeepSeek's 8K max_tokens cap; the prompt instructs
    the model to skip them, and this pass is the defensive backstop.

    Sections whose array becomes empty after filtering are dropped too,
    except `identitas_pasien` which is preserved for downstream consumers
    that always expect it.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    drop_section_keys: list[str] = []
    for key, items in sections.items():
        if not isinstance(items, list):
            continue
        kept: list = []
        for it in items:
            if isinstance(it, dict) and (
                it.get("merged_value") is None
                and it.get("asik_value") is None
                and it.get("epus_value") is None
            ):
                continue
            kept.append(it)
        items[:] = kept
        if not items and key != "identitas_pasien":
            drop_section_keys.append(key)
    for k in drop_section_keys:
        del sections[k]
    return merged


_REASONING_BOTH_IDENTICAL = "Kedua sumber memuat data yang konsisten. Nilai akhir diambil dari ePuskesmas sebagai sumber rujukan."
_REASONING_SAME_MEANING = "Kedua sumber memuat jawaban yang bermakna sama meskipun bentuk nilainya berbeda. Nilai akhir dinormalisasi dan ditandai is_same_answer: true."
_REASONING_EPUS_ONLY = "Field ini hanya terisi di ePuskesmas dan dipakai apa adanya untuk formulir ASIK."
_REASONING_ASIK_ONLY_FIELD = "Field ini hanya terisi di ASIK; ePuskesmas belum memiliki nilai untuk pertanyaan ini."
_REASONING_ASIK_ONLY_FORM = "Form ini tidak tersedia di ePuskesmas; nilai dipertahankan dari ASIK."
_REASONING_BOTH_EMPTY = "Kedua sumber memiliki slot data untuk field ini, tetapi nilainya sama-sama kosong. Nilai akhir ditetapkan null."
_REASONING_AUTO_CONFLICT = "Nilai berbeda antara ASIK dan ePuskesmas; perlu ditinjau. Nilai akhir mengikuti ePuskesmas sebagai sumber rujukan."
_REASONING_EPUS_IMPLAUSIBLE = "Nilai ePuskesmas tidak masuk akal secara fisik/klinis untuk pasien ini. Nilai akhir mengikuti ASIK karena nilai ePuskesmas tidak masuk akal."
_REASONING_IDENTITAS_CONSISTENT = "Identitas pasien konsisten antara ASIK dan ePuskesmas."
_REASONING_IDENTITAS_SAME_MEANING = "Identitas pasien bermakna sama meskipun bentuk nilainya berbeda."
_REASONING_IDENTITAS_ASIK_ONLY = "Identitas pasien hanya tersedia di ASIK."
_REASONING_IDENTITAS_EPUS_ONLY = "Identitas pasien hanya tersedia di ePuskesmas."


def _fill_template_reasoning(merged: dict) -> dict:
    """Rehydrate canonical Indonesian reasoning text from item state.

    The merge prompt instructs the LLM to emit ``reasoning: ""`` for all
    templated (non-conflict) cases and only author free-form text when
    ``is_conflict: true``. This pass scans every item and, when
    ``reasoning`` is missing or empty AND ``is_conflict`` is false,
    fills it from the canonical templates based on item value-state.

    Skipping ``is_conflict: true`` items preserves LLM-authored
    plausibility commentary on numeric drift / categorical conflict.
    """
    sections = merged.get("sections")
    if not isinstance(sections, dict):
        return merged
    for section_key, items in sections.items():
        is_identitas = section_key == "identitas_pasien"
        # ASIK-only form = section slug not present in EPUS_BREADCRUMBS lookup.
        is_asik_only_form = (
            not is_identitas and _SLUG_TO_FORM.get(section_key) is None
        )
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            existing = it.get("reasoning")
            has_text = isinstance(existing, str) and bool(existing.strip())
            if it.get("is_conflict"):
                # Keep LLM-authored plausibility text; backfill the template
                # only when a (possibly backend-forced) conflict has none. An
                # implausible-EPUS override (merged_value followed ASIK) gets
                # the matching template so the text never contradicts the value.
                if not has_text:
                    it["reasoning"] = (
                        _REASONING_EPUS_IMPLAUSIBLE
                        if it.get("epus_implausible") is True
                        else _REASONING_AUTO_CONFLICT
                    )
                continue
            if has_text:
                continue
            asik = it.get("asik_value")
            epus = it.get("epus_value")
            if epus is not None and asik is None:
                it["reasoning"] = (
                    _REASONING_IDENTITAS_EPUS_ONLY if is_identitas else _REASONING_EPUS_ONLY
                )
            elif asik is not None and epus is None:
                if is_identitas:
                    it["reasoning"] = _REASONING_IDENTITAS_ASIK_ONLY
                elif is_asik_only_form:
                    it["reasoning"] = _REASONING_ASIK_ONLY_FORM
                else:
                    it["reasoning"] = _REASONING_ASIK_ONLY_FIELD
            elif asik is not None and epus is not None:
                if it.get("is_same_answer"):
                    it["reasoning"] = (
                        _REASONING_IDENTITAS_SAME_MEANING if is_identitas else _REASONING_SAME_MEANING
                    )
                else:
                    it["reasoning"] = (
                        _REASONING_IDENTITAS_CONSISTENT if is_identitas else _REASONING_BOTH_IDENTICAL
                    )
            else:
                it["reasoning"] = _REASONING_BOTH_EMPTY
    return merged


def _log_key(job_id: str) -> str:
    return f"merge:job:{job_id}:log"


def _stream_chan(job_id: str) -> str:
    return f"merge:job:{job_id}:stream"


def _cancel_key(job_id: str) -> str:
    return f"merge:job:{job_id}:cancel"


def _calc_cost(tokens: int | None, rate: Decimal | None) -> Decimal | None:
    if tokens is None or rate is None:
        return None
    return Decimal(tokens) * rate / _PER_MILLION


def _publish_line(rc: "redis.Redis", log_key: str, chan: str, line: str) -> None:
    try:
        rc.rpush(log_key, line)
        rc.ltrim(log_key, -LOG_RING_MAX, -1)
        rc.expire(log_key, LOG_TTL_SECONDS)
        rc.publish(chan, line)
    except Exception:
        pass


_THINK_RE = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

# Retry budget for LLM JSON parse failures. Three failure modes seen in
# ckg_prod.llm_logs (source='merge_patient_data', success=false):
#   1. Truncation  — output_tokens == provider cap (8192 on DeepSeek, hit
#      on gpt-4o-mini when we used to ship 8192 as default), finish_reason
#      == "length". Fix: set base_max_tokens to the model's real cap.
#   2. Glitch      — output_tokens well below cap, finish_reason == "stop",
#      raw \n/quote-drop mid-string. Fix: response_format=json_object on
#      providers that support it; re-sample retry for the rest (temp=0 on
#      OpenAI is not strictly deterministic).
#   3. Bad shape   — sections[k] arrives as dict not list, crashes
#      post-processing. Fix: _validate_merge_shape + retry.
# 3 attempts caps cost. Each attempt sends the SAME max_tokens — bumping
# would exceed the provider's hard cap on attempts 2-3 and 400, defeating
# the retry. Retry value here is re-sampling (modes 2 & 3), not raising
# the budget. To raise the budget, change base_max_tokens for the model.
_MERGE_MAX_ATTEMPTS = 3
# OpenAI constrained-decoding flag. Allowlisted by model below — sent ONLY
# to providers known to accept it, because unknown gateways respond with
# HTTP 400 and ``chat_complete`` raises RuntimeError (not retried — would
# break every merge on an unknown provider). Prompt must contain the word
# "json" (merge_patient.md does — verified, 14 mentions).
_JSON_RESPONSE_FORMAT = {"type": "json_object"}

# Per-model output-token cap. Sources: OpenAI model docs, DeepSeek docs.
# `None` means "send no max_tokens" — let provider use its default. Pattern
# match is prefix on the lowercased model id.
#
# Conservative on purpose: when a value below the model's documented max
# still covers our payload (≤16K tokens of merged JSON), use it. Lower =
# faster failure if provider auto-caps and truncates, easier to spot.
_MODEL_MAX_OUTPUT_TOKENS: tuple[tuple[str, int], ...] = (
    # OpenAI — chat completions
    ("gpt-4o-mini", 16384),
    ("gpt-4o", 16384),
    ("gpt-4.1-mini", 16384),
    ("gpt-4.1", 16384),
    ("gpt-4-turbo", 4096),     # real cap 4096; NOT 16384.
    ("gpt-3.5-turbo", 4096),
    # OpenAI — reasoning (use max_completion_tokens; chat_complete handles).
    ("gpt-5", 16384),
    ("o1", 16384),
    ("o3", 16384),
    ("o4", 16384),
    # DeepSeek v4 (deepseek-v4-flash / -pro): 384K max output. 32768 is far
    # under that (no 400) yet well above any merged-patient JSON, so the 8192
    # truncation the older deepseek-chat hit can't recur. Must precede the
    # bare "deepseek" prefix below — first match wins.
    ("deepseek-v4", 32768),
    # Legacy deepseek-chat / -reasoner — hard 8192 cap server-side; over 400s.
    ("deepseek", 8192),
    # gpt-oss-20b (local.juxtalabs.io, model id "openai/gpt-oss-20b"). Reasoning
    # model that spends output tokens on a reasoning channel BEFORE the JSON
    # answer, so the old 8192 default truncated every merge (finish=length,
    # invalid JSON). Set to the model's full 131072 context window — the server
    # clamps max_tokens to the room left after the prompt, so this is the
    # practical max and never truncates. (Large patients may still hit the
    # gateway's 120s read timeout — that's origin speed/load, not this cap.)
    # Matches the "openai/gpt-oss" prefix.
    ("openai/gpt-oss", 131072),
)

# Models that support response_format={"type":"json_object"}. Anything not
# in this list gets `response_format=None` so we don't 400 unknown gateways.
_JSON_FORMAT_SUPPORTED_PREFIXES: tuple[str, ...] = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-3.5-turbo-1106",
    "gpt-3.5-turbo-0125", "gpt-5", "o1", "o3", "o4",
    "deepseek",
    # gpt-oss (local.juxtalabs.io / vLLM) — verified it honours json_object
    # constrained decoding; without it the model occasionally emits malformed
    # JSON mid-stream on big patients (RIKANAH glitched at char ~1500).
    "openai/gpt-oss",
)


def _base_max_tokens_for_model(model: str) -> int | None:
    """Return the safe initial max_tokens for ``model``, or ``None`` to omit.

    Looks up :data:`_MODEL_MAX_OUTPUT_TOKENS` by lowercased prefix. Unknown
    models return 8192 — same value we historically shipped, so adding a
    new llm_config never regresses on token budget (it just doesn't benefit
    from the model-aware bump).
    """
    m = (model or "").strip().lower()
    for prefix, cap in _MODEL_MAX_OUTPUT_TOKENS:
        if m.startswith(prefix):
            return cap
    return 8192


def _json_response_format_for_model(model: str) -> dict | None:
    """Return :data:`_JSON_RESPONSE_FORMAT` only for providers known to accept it.

    Sending it to an unknown gateway risks HTTP 400 ("unsupported
    parameter"), which is not retried and would break every merge for that
    config. Conservative allowlist trades a bit of glitch protection on
    exotic providers for safety on llm_config swaps.
    """
    m = (model or "").strip().lower()
    if any(m.startswith(p) for p in _JSON_FORMAT_SUPPORTED_PREFIXES):
        return _JSON_RESPONSE_FORMAT
    return None


def _validate_merge_shape(merged: object) -> None:
    """Raise ValueError on shapes that crash post-processing.

    Caught by the retry helper so a malformed sampling pass re-runs instead
    of bubbling up as `'dict' object has no attribute 'append'` (seen in
    prod when the LLM emits ``sections[<key>]`` as a dict instead of a
    list of items).
    """
    if not isinstance(merged, dict):
        raise ValueError(f"merged is {type(merged).__name__}, expected dict")
    sections = merged.get("sections")
    if sections is None:
        return
    if not isinstance(sections, dict):
        raise ValueError(f"sections is {type(sections).__name__}, expected dict")
    for k, v in sections.items():
        if not isinstance(v, list):
            raise ValueError(
                f"sections[{k!r}] is {type(v).__name__}, expected list"
            )


def _strip_json_fences(text: str) -> str:
    # Reasoning models (DeepSeek V3.1, etc.) prepend a <think>...</think> block
    # before the answer. Drop it before JSON parsing. Anchored to start so a
    # literal "<think>" inside the JSON payload isn't stripped.
    s = _THINK_RE.sub("", text, count=1).strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
        if s.startswith("json"):
            s = s[4:]
    return s.strip()


def _chat_and_parse_with_retry(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    user_msg: str,
    base_max_tokens: int | None,
    response_format: dict | None,
    reasoning_effort: str | None,
    route_order: str | None,
    rc: "redis.Redis",
    log_key: str,
    chan: str,
    nik: str,
) -> tuple[dict, ChatResult]:
    """Call chat_complete + parse JSON, retrying up to ``_MERGE_MAX_ATTEMPTS``.

    Retries fire on ``json.JSONDecodeError`` AND ``ValueError`` from
    :func:`_validate_merge_shape` — i.e. any output the post-processing
    pipeline can't consume. HTTP / transport failures (``RuntimeError``
    raised by ``chat_complete``) propagate to the caller's outer handler
    and fail this patient without retry, matching prior behavior and
    avoiding wasted token spend on auth / rate-limit / model-config errors.

    Each attempt sends identical ``max_tokens`` — bumping would risk
    exceeding the provider's hard cap on later attempts and 400-ing,
    defeating the retry. Retry value is re-sampling; raise the budget by
    updating ``_MODEL_MAX_OUTPUT_TOKENS`` instead.

    Returns ``(parsed_dict, last_ChatResult)`` on success. On exhaustion,
    raises the last error with ``exc._merge_last_resp`` set to the final
    ``ChatResult`` so the caller's outer handler can still dump it for
    diagnostics.
    """
    last_exc: Exception | None = None
    last_resp: ChatResult | None = None
    for attempt in range(1, _MERGE_MAX_ATTEMPTS + 1):
        resp = chat_complete(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=user_msg,
            max_tokens=base_max_tokens,
            response_format=response_format,
            reasoning_effort=reasoning_effort,
            route_order=route_order,
        )
        last_resp = resp
        try:
            merged = json.loads(_strip_json_fences(resp.text))
            _validate_merge_shape(merged)
            if attempt > 1:
                _publish_line(
                    rc, log_key, chan,
                    f"[retry-ok] {nik} parsed on attempt {attempt}/{_MERGE_MAX_ATTEMPTS}",
                )
            return merged, resp
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            err_msg = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
            if attempt < _MERGE_MAX_ATTEMPTS:
                _publish_line(
                    rc, log_key, chan,
                    f"[retry] {nik} attempt {attempt}/{_MERGE_MAX_ATTEMPTS} parse failed "
                    f"(out_tok={resp.output_tokens} finish={resp.finish_reason} err={err_msg[:80]})",
                )
            else:
                _publish_line(
                    rc, log_key, chan,
                    f"[fail] {nik} all {_MERGE_MAX_ATTEMPTS} attempts parse-failed "
                    f"(last out_tok={resp.output_tokens} finish={resp.finish_reason})",
                )
    assert last_exc is not None
    # Attach last resp so the outer handler's diagnostic dump still fires.
    # Built-in exceptions accept arbitrary attributes; setting one preserves
    # the original exception type so isinstance checks downstream keep working.
    last_exc._merge_last_resp = last_resp  # type: ignore[attr-defined]
    raise last_exc


# Per-patient merge retry. When the LLM provider is flaky/down the first pass
# leaves some patients unmerged; we retry ONLY the still-failing subset, up to
# _MERGE_ROUND_MAX passes total (1 initial + retries), shrinking each round.
# If any eligible patient is still unmerged at the end, the job is marked
# FAILED (never SUCCESS) so a silent LLM outage can't masquerade as a clean run
# and the cron pipeline halts loudly. See run_merge for the driver.
_MERGE_ROUND_MAX = 4
_MERGE_ROUND_BACKOFF_SECONDS = 5


def _is_transport_error(msg: str | None) -> bool:
    """True when an error string looks like an LLM transport / HTTP failure
    (provider down/unreachable) rather than a data/parse error. Used ONLY to
    word the merge-job error_message — control flow treats every failure the
    same (any unmerged patient -> FAILED).
    """
    if not msg:
        return False
    m = msg.lstrip()
    return (
        m.startswith("LLM HTTP ")
        or m.startswith("LLM stream")
        or "urlopen error" in m
        or "timed out" in m
        or "Connection" in m
        or "Max retries" in m
    )


def _decide_merge_status(failed_count: int) -> MergeStatus:
    """A merge job is SUCCESS only when every eligible patient merged. Any
    remaining failure -> FAILED. This is the fix for the silent-success bug:
    a total LLM outage used to leave succeeded=0/failed=N yet status=success.
    """
    return MergeStatus.FAILED if failed_count > 0 else MergeStatus.SUCCESS


def _merge_one_patient(
    db: Session,
    rc: "redis.Redis",
    job: MergeJob,
    job_uuid: uuid.UUID,
    pid: uuid.UUID,
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    in_rate,
    out_rate,
    active_id: uuid.UUID,
    reasoning_effort: str | None,
    route_order: str | None,
    prompt_template: str,
    force: bool,
    puskesmas_id: uuid.UUID,
    log_key: str,
    chan: str,
) -> str | None:
    """Attempt to merge a single patient.

    Returns None when the patient is done (merged, twin-copied, or skipped) —
    the caller drops it from the retry set. Returns the error string when the
    LLM / parse / post-processing failed; the caller keeps it for the next
    round and bumps ``failed_count`` once, AFTER all rounds, so a patient that
    fails one round and succeeds the next is counted exactly once.
    """
    patient = db.scalar(
        select(Patient)
        .options(load_only(*_PATIENT_COLS))
        .where(Patient.id == pid, Patient.deleted_at.is_(None))
    )
    if patient is None:
        merge_job_crud.bump_counters(db, job, processed=1, skipped=1)
        db.commit()
        return None

    if not force and patient.merged_at is not None:
        _publish_line(rc, log_key, chan, f"[skip] {patient.nik} already merged")
        merge_job_crud.bump_counters(db, job, processed=1, skipped=1)
        db.commit()
        return None

    # Cross-date twin shortcut: if this patient is paired with another
    # row via match_group_id and the twin already has merged_data,
    # copy it instead of calling the LLM again. Saves the spend on
    # what is the same (asik, epus) pair already merged from the
    # other side. Skipped when force_remerge is requested.
    if not force and patient.match_group_id is not None:
        twin = db.execute(
            select(Patient.merged_data, Patient.merged_at).where(
                Patient.match_group_id == patient.match_group_id,
                Patient.id != patient.id,
                Patient.merged_data.isnot(None),
                Patient.deleted_at.is_(None),
            ).limit(1)
        ).one_or_none()
        if twin is not None:
            now = datetime.now(UTC)
            patient_crud.apply_merge(db, pid, twin.merged_data, now)
            merge_job_crud.bump_counters(db, job, processed=1, succeeded=1)
            db.commit()
            _publish_line(
                rc, log_key, chan,
                f"[ok] {patient.nik} {patient.nama} (copied from twin)",
            )
            return None

    nik = patient.nik
    nama = patient.nama
    # Reset per patient: a transport failure raises before the
    # `merged, resp =` assignment below, so without this the except
    # handler's diagnostic dump would borrow the PREVIOUS patient's
    # ChatResult (stale tokens / wrong raw body).
    resp = None
    try:
        asik = decrypt_json(patient.scraped_asik_data) if patient.scraped_asik_data else {}
        epus = decrypt_json(patient.scraped_epus_data) if patient.scraped_epus_data else {}
        # Hybrid stage 1: deterministic conversion of EPUS into ASIK form shape.
        converted = epus_to_asik(epus) if epus else {}
        # Hybrid stage 2: LLM reconciles the deterministic conversion against
        # the real ASIK record. Sees ONLY (converted, asik) — raw EPUS withheld.
        # Identity is withheld too: the backend builds the identitas section
        # itself (_rebuild_identitas), so the LLM never needs NIK / Nama / Alamat
        # or the extra PII in ASIK detail_data (phone, guardian, occupation,
        # ticket, domicile). It DOES keep sex / DOB / birthplace as context for
        # the value-plausibility check. These copies are LLM-only; the
        # deterministic post-processing below still consumes the full
        # `converted` / `asik`.
        converted_for_llm = _strip_identitas_for_llm(converted)
        asik_for_llm = {k: v for k, v in asik.items() if k != "detail_data"}
        user_msg = (
            f"{prompt_template}\n\n"
            f"## Converted EPUS-as-ASIK (input 1, canonical)\n"
            f"```json\n{json.dumps(converted_for_llm, ensure_ascii=False)}\n```\n\n"
            f"## ASIK (input 2, raw scrape)\n"
            f"```json\n{json.dumps(asik_for_llm, ensure_ascii=False)}\n```\n"
        )
        _publish_line(rc, log_key, chan, f"[run] {nik} {nama}")
        merged, resp = _chat_and_parse_with_retry(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            user_msg=user_msg,
            base_max_tokens=_base_max_tokens_for_model(model),
            response_format=_json_response_format_for_model(model),
            reasoning_effort=reasoning_effort,
            route_order=route_order,
            rc=rc,
            log_key=log_key,
            chan=chan,
            nik=nik,
        )
        # Normalise LLM section keys then let the BACKEND own field presence +
        # raw values deterministically (the LLM only judges both-filled conflicts).
        merged = _slugify_section_keys(merged)
        merged = _enforce_merged_value(merged)
        merged = _drop_null_null_entries(merged)
        merged = _complete_source_fields(merged, converted, asik)
        merged = _rebuild_identitas(merged, converted, asik)
        merged = _backfill_asik_questions(merged, _extract_asik_form_names(asik))
        merged = _overwrite_epus_questions(merged)
        merged = _normalize_status_flags(merged)
        merged = _fill_template_reasoning(merged)
        merged = _drop_orphan_conditional_children(merged)
        merged = _order_by_asik(merged, converted, asik)
        merged = _group_into_pakets(merged, converted, asik)
        encrypted = encrypt_json(merged)
        now = datetime.now(UTC)
        patient_crud.apply_merge(db, pid, encrypted, now)
        # Cross-date twin propagation: copy the freshly-computed merged_data to
        # the twin so both sides reflect the same canonical merge.
        if patient.match_group_id is not None:
            db.execute(
                update(Patient).where(
                    Patient.match_group_id == patient.match_group_id,
                    Patient.id != pid,
                    Patient.deleted_at.is_(None),
                ).values(
                    merged_data=encrypted,
                    merged_at=now,
                    updated_at=func.now(),
                )
            )
        prompt_cost = _calc_cost(resp.input_tokens, in_rate)
        completion_cost = _calc_cost(resp.output_tokens, out_rate)
        total_cost = (
            prompt_cost + completion_cost
            if prompt_cost is not None and completion_cost is not None
            else None
        )
        llm_log_crud.record(
            db,
            llm_config_id=active_id,
            source="merge_patient_data",
            model=model,
            success=True,
            merge_job_id=job_uuid,
            patient_id=pid,
            puskesmas_id=puskesmas_id,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            total_tokens=resp.total_tokens,
            reasoning_tokens=resp.reasoning_tokens,
            prompt_cost=prompt_cost,
            completion_cost=completion_cost,
            total_cost=total_cost,
            latency_ms=resp.latency_ms,
        )
        merge_job_crud.bump_counters(db, job, processed=1, succeeded=1)
        db.commit()
        _publish_line(rc, log_key, chan, f"[ok] {nik} {nama}")
        return None
    except Exception as exc:
        db.rollback()
        msg = str(exc)[:1000]
        # DIAGNOSTIC: dump raw LLM response on parse failure so we can inspect
        # token counts + tail of the (possibly truncated) JSON.
        _dbg_in = _dbg_out = _dbg_total = _dbg_reason = _dbg_lat = None
        _diag_resp: ChatResult | None = (
            getattr(exc, "_merge_last_resp", None) or resp
        )
        try:
            if _diag_resp is not None:
                _dbg_in = _diag_resp.input_tokens
                _dbg_out = _diag_resp.output_tokens
                _dbg_total = _diag_resp.total_tokens
                _dbg_reason = _diag_resp.reasoning_tokens
                _dbg_lat = _diag_resp.latency_ms
                try:
                    dump_path = f"/tmp/merge_fail_{nik}_{job.id}.txt"
                    with open(dump_path, "w", encoding="utf-8") as f:
                        f.write(
                            f"# nik={nik} nama={nama}\n"
                            f"# in_tok={_dbg_in} out_tok={_dbg_out} total={_dbg_total} reasoning={_dbg_reason} latency_ms={_dbg_lat}\n"
                            f"# error={msg}\n"
                            f"# raw_len_chars={len(_diag_resp.text)}\n"
                            "----- BEGIN RAW LLM RESPONSE -----\n"
                        )
                        f.write(_diag_resp.text)
                    _publish_line(rc, log_key, chan, f"[debug] dumped raw resp to {dump_path} (len={len(_diag_resp.text)} out_tok={_dbg_out})")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            llm_log_crud.record(
                db,
                llm_config_id=active_id,
                source="merge_patient_data",
                model=model,
                success=False,
                merge_job_id=job_uuid,
                patient_id=pid,
                input_tokens=_dbg_in,
                output_tokens=_dbg_out,
                total_tokens=_dbg_total,
                reasoning_tokens=_dbg_reason,
                latency_ms=_dbg_lat,
                error=msg,
            )
            db.commit()
        except Exception:
            db.rollback()
        _publish_line(rc, log_key, chan, f"[fail] {nik}: {msg}")
        return msg


@celery_app.task(bind=True, name="merge.run")
def run_merge(self, job_id: str) -> None:
    db: Session = SessionLocal()
    rc = redis.from_url(settings.REDIS_URL, decode_responses=True)
    log_key = _log_key(job_id)
    chan = _stream_chan(job_id)
    job: MergeJob | None = None
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.scalar(
            select(MergeJob)
            .options(load_only(*_JOB_TASK_COLS))
            .where(MergeJob.id == job_uuid)
        )
        if job is None:
            return
        if job.status == MergeStatus.CANCELLED:
            try:
                rc.publish(chan, "__cancelled__")
            except Exception:
                pass
            return

        active = llm_config_crud.get_active(db)
        if active is None:
            merge_job_crud.mark_failed(
                db, job, "no active llm_config configured", datetime.now(UTC)
            )
            try:
                rc.publish(chan, "__failed__")
            except Exception:
                pass
            return
        try:
            api_key = decrypt_json(active.api_key_enc).get("api_key", "")
        except Exception as exc:
            merge_job_crud.mark_failed(
                db, job, f"active llm_config api_key unreadable: {exc}"[:2000], datetime.now(UTC)
            )
            try:
                rc.publish(chan, "__failed__")
            except Exception:
                pass
            return
        if not api_key:
            merge_job_crud.mark_failed(
                db, job, "active llm_config api_key is empty", datetime.now(UTC)
            )
            try:
                rc.publish(chan, "__failed__")
            except Exception:
                pass
            return

        try:
            prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            merge_job_crud.mark_failed(
                db, job, f"prompt file not found at {PROMPT_PATH}", datetime.now(UTC)
            )
            try:
                rc.publish(chan, "__failed__")
            except Exception:
                pass
            return

        provider = active.provider
        model = active.model
        base_url = active.base_url
        in_rate = active.input_price_per_1m
        out_rate = active.output_price_per_1m
        active_id = active.id
        reasoning_effort = active.reasoning_effort
        route_order = active.route_order
        puskesmas_id = job.puskesmas_id
        force = bool(job.force_remerge)
        per_patient_id = job.patient_id

        if per_patient_id is not None:
            # Per-NIK merge: target the single patient. force_remerge is implicit.
            target_ids = [per_patient_id]
        else:
            date_iso = job.date_filter
            try:
                target_date = date.fromisoformat(date_iso) if date_iso else None
            except ValueError:
                merge_job_crud.mark_failed(
                    db, job, f"invalid date_filter: {date_iso}", datetime.now(UTC)
                )
                try:
                    rc.publish(chan, "__failed__")
                except Exception:
                    pass
                return
            if target_date is None:
                merge_job_crud.mark_failed(
                    db, job, "merge job missing date_filter", datetime.now(UTC)
                )
                try:
                    rc.publish(chan, "__failed__")
                except Exception:
                    pass
                return

            # Snapshot target patient ids up-front so iteration can't be perturbed
            # by other writers; ordering by id keeps the run deterministic.
            stmt = (
                select(Patient.id)
                .where(
                    Patient.puskesmas_id == puskesmas_id,
                    Patient.match_status == MatchStatus.MATCHED,
                    Patient.filter_date == target_date,
                    Patient.deleted_at.is_(None),
                )
                .order_by(Patient.id)
            )
            if not force:
                stmt = stmt.where(Patient.merged_at.is_(None))
            target_ids = list(db.scalars(stmt))

        t0 = time.monotonic()
        sampler = ResourceSampler("self").start()
        resource_metrics: dict | None = None
        merge_job_crud.mark_running(
            db, job, self.request.id or "", datetime.now(UTC), len(target_ids)
        )
        _publish_line(rc, log_key, chan, f"start: {len(target_ids)} matched patient(s) targeted (force={force})")

        cancelled = False
        cancel_key = _cancel_key(job_id)
        # Round-retry: re-attempt ONLY the still-failing patients each pass,
        # shrinking the set. A patient that fails one round and succeeds the
        # next is counted once (failed_count is bumped after all rounds, below).
        remaining = list(target_ids)
        last_errors: dict[uuid.UUID, str] = {}
        for _round_no in range(1, _MERGE_ROUND_MAX + 1):
            if not remaining:
                break
            if _round_no > 1:
                _publish_line(
                    rc, log_key, chan,
                    f"[retry {_round_no}/{_MERGE_ROUND_MAX}] {len(remaining)} patient(s) still failing",
                )
                try:
                    time.sleep(_MERGE_ROUND_BACKOFF_SECONDS)
                except Exception:
                    pass
            still_failed: list[uuid.UUID] = []
            for pid in remaining:
                # Cancel-flag is set by the cancel route in Redis. Polling Redis
                # avoids one SELECT-per-iteration against Postgres (N+1).
                try:
                    if rc.get(cancel_key) == "1":
                        cancelled = True
                        break
                except Exception:
                    pass
                err = _merge_one_patient(
                    db, rc, job, job_uuid, pid,
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    in_rate=in_rate,
                    out_rate=out_rate,
                    active_id=active_id,
                    reasoning_effort=reasoning_effort,
                    route_order=route_order,
                    prompt_template=prompt_template,
                    force=force,
                    puskesmas_id=puskesmas_id,
                    log_key=log_key,
                    chan=chan,
                )
                if err is not None:
                    last_errors[pid] = err
                    still_failed.append(pid)
            if cancelled:
                break
            remaining = still_failed

        duration = time.monotonic() - t0
        resource_metrics = sampler.stop()
        if cancelled:
            # route already wrote CANCELLED + finished_at; persist resource metrics separately
            try:
                if resource_metrics and resource_metrics.get("samples", 0) > 0:
                    merge_job_crud.set_resource_metrics(db, job, resource_metrics)
            except Exception as exc:
                log.warning("failed to persist resource metrics on cancel: %s", exc)
            try:
                rc.publish(chan, "__cancelled__")
            except Exception:
                pass
            return

        # Count each still-unmerged patient as failed exactly once, now.
        for pid in remaining:
            merge_job_crud.bump_counters(db, job, processed=1, failed=1)
        if remaining:
            db.commit()

        status = _decide_merge_status(job.failed_count or 0)
        if status is MergeStatus.FAILED:
            # Word the message so the operator can tell a provider outage (retry
            # later) from a poison record (investigate) — control flow is the
            # same either way: any unmerged patient halts the run.
            transport_only = all(
                _is_transport_error(last_errors.get(pid)) for pid in remaining
            ) if remaining else False
            sample = next(iter(last_errors.values()), "")[:160]
            kind = "LLM provider unreachable" if transport_only else "merge failed (incl. non-transport error)"
            err_msg = (
                f"merge incomplete: {job.failed_count}/{job.total_count} patient(s) unmerged "
                f"after {_MERGE_ROUND_MAX} round(s) — {kind}: {sample}"
            )[:2000]
            merge_job_crud.mark_failed(
                db, job, err_msg, datetime.now(UTC),
                duration_seconds=duration, metrics=resource_metrics,
            )
            _publish_line(
                rc, log_key, chan,
                f"done(FAILED): succeeded={job.succeeded_count} failed={job.failed_count} "
                f"skipped={job.skipped_count} — {kind}",
            )
            try:
                rc.publish(chan, "__failed__")
            except Exception:
                pass
            return

        merge_job_crud.mark_success(db, job, duration, datetime.now(UTC), metrics=resource_metrics)
        _publish_line(
            rc, log_key, chan,
            f"done: succeeded={job.succeeded_count} failed={job.failed_count} skipped={job.skipped_count}",
        )
        try:
            rc.publish(chan, "__done__")
        except Exception:
            pass
    except Exception as exc:
        db.rollback()
        # Sampler.stop() is idempotent — safe to call here whether or not the
        # normal path already stopped it. Guarantees the daemon thread is reaped.
        _sampler = locals().get("sampler")
        _metrics = _sampler.stop() if _sampler is not None else None
        if job is not None:
            try:
                db.refresh(job, ["status"])
                if job.status != MergeStatus.CANCELLED:
                    merge_job_crud.mark_failed(
                        db, job, str(exc)[:2000], datetime.now(UTC), metrics=_metrics
                    )
            except Exception:
                pass
        try:
            rc.publish(chan, "__failed__")
        except Exception:
            pass
        raise
    finally:
        db.close()
