"""Drift guard for the frontend-dashboard chatbot knowledge base (chatbot/).

Two enforcement layers (see chatbot/README.md):

1. **Content pins** — label strings and thresholds the packs quote must stay
   byte-identical to the constants in the code that produces them.
2. **Source hash lock** — every file whose behavior the packs describe is
   sha256-pinned in chatbot/knowledge.lock.json. Changing one without
   re-verifying the packs (and re-blessing) fails here, on purpose.
"""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHATBOT = REPO / "chatbot"
KNOWLEDGE = CHATBOT / "knowledge"
LOCK = CHATBOT / "knowledge.lock.json"

# Removing a file from the bless script's pin list must not silently weaken
# the guard — the lock must always cover at least these. Every entry added to
# PINNED_SOURCES in backend/scripts/bless_chatbot_knowledge.py must be added
# here too; test_bless_list_matches_lock below catches a script/lock mismatch,
# but only this hardcoded floor stops a pin being dropped from both at once.
REQUIRED_PINNED = {
    "backend/app/services/hipertensi_registry_scan.py",
    "backend/app/services/hipertensi_charts_scan.py",
    "backend/app/services/dashboard_scan.py",
    "backend/app/api/routes/hipertensi_report.py",
    "backend/app/api/routes/gdp_report.py",
    "backend/app/api/routes/report_dashboards.py",
    "frontend-shared/hipertensi/components/hipertensi-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/dashboard/page.tsx",
    "frontend-dashboard/app/(dashboard)/hipertensi-report/page.tsx",
    "frontend-shared/hipertensi/components/charts/cascade-chart.tsx",
    "frontend-shared/hipertensi/components/charts/tertatalaksana-chart.tsx",
    "frontend-shared/hipertensi/components/charts/monthly-area-chart.tsx",
    "frontend-shared/hipertensi/components/charts/proporsi-chart.tsx",
    "frontend-shared/hipertensi/components/charts/chart-point-label.tsx",
    "frontend-shared/hipertensi/components/hipertensi-charts-grid.tsx",
    "frontend-shared/hipertensi/components/gap-tatalaksana-view.tsx",
    "frontend-shared/hipertensi/components/gap-tatalaksana-table.tsx",
    "backend/app/services/dm_registry_scan.py",
    "backend/app/api/routes/dm_report.py",
    "frontend-shared/dm/components/dm-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/dm-report/page.tsx",
    "backend/app/services/lipid_registry_scan.py",
    "backend/app/api/routes/lipid_report.py",
    "frontend-shared/lipid/components/lipid-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/lipid-report/page.tsx",
    "backend/app/services/obesitas_registry_scan.py",
    "backend/app/api/routes/obesitas_report.py",
    "frontend-shared/obesitas/components/obesitas-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/obesitas-report/page.tsx",
}

def _sha256_normalized(path: Path) -> str:
    """sha256 with line endings normalized to LF — see the identical helper in
    backend/scripts/bless_chatbot_knowledge.py. Without this the lock is a
    property of the checkout (``core.autocrlf``), not of the file content, and
    every pin reads as stale on a Windows clone."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


_REBLESS = (
    "Re-read the affected chatbot/knowledge pack(s), update any stale claim, "
    "then re-bless: cd backend && python scripts/bless_chatbot_knowledge.py "
    "(chatbot/README.md)."
)


def test_manifest_pages_resolve_and_cover_all_packs() -> None:
    manifest = json.loads((CHATBOT / "manifest.json").read_text())
    pages: dict[str, list[str]] = manifest["pages"]
    assert "common" in pages, "manifest must define the 'common' fallback page"

    referenced: set[str] = set()
    for page, packs in pages.items():
        assert packs, f"page {page!r} maps to no packs"
        for pack in packs:
            assert (KNOWLEDGE / pack).is_file(), f"page {page!r} → missing pack {pack!r}"
            referenced.add(pack)

    on_disk = {p.name for p in KNOWLEDGE.glob("*.md")}
    orphans = on_disk - referenced
    assert not orphans, f"knowledge packs not referenced by any manifest page: {orphans}"


def test_system_prompt_present_and_small() -> None:
    raw = (CHATBOT / "system.md").read_bytes()
    assert raw.strip(), "system.md is empty"
    assert len(raw) <= 4096, f"system.md is {len(raw)}B — keep the guardrail prompt short (≤4KB)"


def test_registry_pack_quotes_code_constants_verbatim() -> None:
    # Import from the code so a label/wording change breaks this immediately.
    from app.services.hipertensi_registry_scan import (
        _FU_MISSED_VISIT,
        _FU_TERKENDALI,
        _FU_TIDAK_TERKENDALI,
        _INTERP_HIPERTENSI,
    )

    text = (KNOWLEDGE / "registri-hipertensi.md").read_text()
    for label in (_FU_TERKENDALI, _FU_TIDAK_TERKENDALI, _FU_MISSED_VISIT,
                  _INTERP_HIPERTENSI):
        assert label in text, f"label not quoted byte-identical in pack: {label!r}\n{_REBLESS}"

    # KMK 84/2026 band thresholds + band names + a sentinel drug name.
    for needle in ("140", "90", "130", "85", "129", "84",
                   "Hipertensi", "Pre-Hipertensi", "Normal", "Amlodipin"):
        assert needle in text, f"threshold/term missing from registri pack: {needle!r}\n{_REBLESS}"


def test_dm_registry_pack_quotes_code_constants_verbatim() -> None:
    # Same ratchet as the hipertensi pack above: the bot must never invent a
    # label the DM registry does not actually render.
    from app.services.dm_registry_scan import (
        _FU_MISSED_VISIT,
        _FU_TERKENDALI,
        _FU_TIDAK_TERKENDALI,
        _INTERP_DM,
        _INTERP_PREDIABETES,
        _INTERP_TIDAK_VALID,
    )

    text = (KNOWLEDGE / "registri-diabetes-melitus.md").read_text(encoding="utf-8")
    for label in (_FU_TERKENDALI, _FU_TIDAK_TERKENDALI, _FU_MISSED_VISIT,
                  _INTERP_DM, _INTERP_PREDIABETES, _INTERP_TIDAK_VALID):
        assert label in text, f"label not quoted byte-identical in pack: {label!r}\n{_REBLESS}"

    # Baseline diagnosis bands, prediabetes bands, and the U17 follow-up targets.
    for needle in ("126", "200", "100", "125", "140", "199",
                   "7%", "80", "130", "180", "Metformin"):
        assert needle in text, f"threshold/term missing from DM pack: {needle!r}\n{_REBLESS}"


def test_lipid_registry_pack_quotes_code_constants_verbatim() -> None:
    # Same ratchet as the two packs above.
    from app.services.lipid_registry_scan import (
        _FU_MISSED_VISIT,
        _FU_TERKENDALI,
        _FU_TIDAK_TERKENDALI,
        _INTERP_DISLIPIDEMIA,
        _INTERP_NORMAL,
    )

    text = (KNOWLEDGE / "registri-dislipidemia.md").read_text(encoding="utf-8")
    for label in (_FU_TERKENDALI, _FU_TIDAK_TERKENDALI, _FU_MISSED_VISIT,
                  _INTERP_DISLIPIDEMIA, _INTERP_NORMAL):
        assert label in text, f"label not quoted byte-identical in pack: {label!r}\n{_REBLESS}"

    # The four syarat thresholds and a sentinel drug name.
    for needle in ("200", "130", "40", "150", "Simvastatin"):
        assert needle in text, f"threshold/term missing from lipid pack: {needle!r}\n{_REBLESS}"

    # The three divergences from the DM registry. Each is a claim a reader would
    # otherwise carry over from the sibling registries and get wrong, so the pack
    # must say them out loud — not merely omit the DM wording.
    assert "3 bulan" in text, f"pack must state the QUARTERLY control interval\n{_REBLESS}"
    for needle in ("bukan syarat", "pengukuran"):
        assert needle in text, (
            f"pack must state that riwayat HT/DM is reported, not filtered on, and "
            f"that admission is by measurement: missing {needle!r}\n{_REBLESS}"
        )


def test_obesitas_registry_pack_quotes_code_constants_verbatim() -> None:
    # Same ratchet as the three packs above.
    from app.services.obesitas_registry_scan import (
        _FU_MISSED_VISIT,
        _FU_TERKENDALI,
        _FU_TIDAK_TERKENDALI,
        _INTERP_NORMAL,
        _INTERP_OBESITAS_I,
        _INTERP_OBESITAS_II,
    )

    # Whitespace-normalized: the packs are hard-wrapped prose, so a phrase this
    # guard looks for can legitimately straddle a line break. Matching the raw
    # text would make a harmless re-wrap look like a dropped claim (and, worse,
    # would let someone "fix" a real failure by re-wrapping the paragraph).
    raw = (KNOWLEDGE / "registri-obesitas.md").read_text(encoding="utf-8")
    text = " ".join(raw.split())
    for label in (_FU_TERKENDALI, _FU_TIDAK_TERKENDALI, _FU_MISSED_VISIT,
                  _INTERP_OBESITAS_I, _INTERP_OBESITAS_II, _INTERP_NORMAL):
        assert label in text, f"label not quoted byte-identical in pack: {label!r}\n{_REBLESS}"

    # The two IMT band thresholds and the follow-up target.
    for needle in ("25", "30", "5%"):
        assert needle in text, f"threshold missing from obesitas pack: {needle!r}\n{_REBLESS}"

    # What a reader would otherwise carry over wrong from the sibling registries.
    assert "3-6 bulan" in text or "3–6 bulan" in text, (
        f"pack must state the 3-6 month control window\n{_REBLESS}"
    )
    for needle in ("bukan syarat", "pengukuran", "dihitung sendiri"):
        assert needle in text, (
            "pack must state that riwayat HT/DM is reported rather than filtered "
            "on, that admission is by measurement, and that IMT is derived here "
            f"rather than read from a source: missing {needle!r}\n{_REBLESS}"
        )


def test_bless_list_matches_lock() -> None:
    # The lock is generated from PINNED_SOURCES, so the two disagreeing means
    # someone edited the pin list and never re-blessed — the lock is then
    # guarding a stale set of files and says nothing about the new one.
    import sys

    sys.path.insert(0, str(REPO / "backend" / "scripts"))
    from bless_chatbot_knowledge import PINNED_SOURCES

    listed = set(PINNED_SOURCES)
    assert len(listed) == len(PINNED_SOURCES), "PINNED_SOURCES has duplicate entries"

    locked = set(json.loads(LOCK.read_text())["pinned"])
    assert listed == locked, (
        "bless script's PINNED_SOURCES and knowledge.lock.json disagree:\n"
        f"  pinned but not locked: {sorted(listed - locked)}\n"
        f"  locked but not pinned: {sorted(locked - listed)}\n" + _REBLESS
    )

    unratcheted = listed - REQUIRED_PINNED
    assert not unratcheted, (
        "these pins are not in REQUIRED_PINNED, so the bless script could drop "
        f"them without any test failing: {sorted(unratcheted)}\n"
        "Add them to REQUIRED_PINNED in this file."
    )


def test_pinned_sources_match_lock() -> None:
    lock = json.loads(LOCK.read_text())
    pinned: dict[str, str] = lock["pinned"]

    missing = REQUIRED_PINNED - set(pinned)
    assert not missing, f"knowledge.lock.json lost required pins: {missing}\n{_REBLESS}"

    stale = []
    for rel, expected in pinned.items():
        actual = _sha256_normalized(REPO / rel)
        if actual != expected:
            stale.append(rel)
    assert not stale, (
        "Source files changed since the chatbot knowledge was last verified:\n  "
        + "\n  ".join(stale)
        + "\nThe chatbot may now describe outdated behavior. "
        + _REBLESS
    )
