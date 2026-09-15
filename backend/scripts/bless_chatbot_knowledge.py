"""Re-bless the chatbot knowledge packs against their pinned source files.

Recomputes the sha256 of every pinned source and rewrites
``chatbot/knowledge.lock.json``. Run this ONLY after re-reading the affected
pack(s) in ``chatbot/knowledge/`` and confirming their claims still match the
changed source (see ``chatbot/README.md``):

    cd backend && python scripts/bless_chatbot_knowledge.py

Dev-machine / CI tool — resolves paths relative to the repo checkout, not the
container layout.
"""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / "chatbot" / "knowledge.lock.json"

# Every file whose behavior the knowledge packs describe. Editing any of these
# without re-blessing fails backend/tests/test_chatbot_knowledge.py — that is
# the point: it forces a "did this change what the bot tells users?" review.
PINNED_SOURCES = [
    "backend/app/services/hipertensi_registry_scan.py",
    "backend/app/services/hipertensi_charts_scan.py",
    "backend/app/services/dashboard_scan.py",
    "backend/app/api/routes/hipertensi_report.py",
    "backend/app/api/routes/gdp_report.py",
    "backend/app/api/routes/report_dashboards.py",
    "frontend-shared/hipertensi/components/hipertensi-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/dashboard/page.tsx",
    "frontend-dashboard/app/(dashboard)/hipertensi-report/page.tsx",
    # The 6 dashboard charts themselves: dashboard.md describes what each one
    # plots and how its on-point labels read. Pinning the page alone missed a
    # label change that made the pack wrong (it still said the % was tooltip-only).
    "frontend-shared/hipertensi/components/charts/cascade-chart.tsx",
    "frontend-shared/hipertensi/components/charts/tertatalaksana-chart.tsx",
    "frontend-shared/hipertensi/components/charts/monthly-area-chart.tsx",
    "frontend-shared/hipertensi/components/charts/proporsi-chart.tsx",
    "frontend-shared/hipertensi/components/charts/chart-point-label.tsx",
    # The 6-card grid both apps render: every chart title, colour, denominator
    # and headline wording dashboard.md describes now lives here rather than in
    # dashboard/page.tsx, so the coverage that pin used to give has to follow.
    "frontend-shared/hipertensi/components/hipertensi-charts-grid.tsx",
    # Gap Tatalaksana — gap-tatalaksana.md quotes this page's filter labels,
    # its column list and its 20-rows-per-page.
    "frontend-shared/hipertensi/components/gap-tatalaksana-view.tsx",
    "frontend-shared/hipertensi/components/gap-tatalaksana-table.tsx",
    # Registri Diabetes Melitus: registri-diabetes-melitus.md quotes this scan's
    # interpretasi/follow-up labels, its threshold bands and its syarat verbatim,
    # describes the route's cache/summary behavior, and must never contradict the
    # on-screen "Cara Membaca" card or the page's own title/description.
    "backend/app/services/dm_registry_scan.py",
    "backend/app/api/routes/dm_report.py",
    "frontend-shared/dm/components/dm-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/dm-report/page.tsx",
    # Registri Dislipidemia: same contract as the DM block above. This registry
    # diverges from its siblings in three ways the pack states explicitly
    # (measurement-only syarat, riwayat does not pin the label, QUARTERLY control
    # months), so a change to any of them makes the pack actively wrong, not just
    # stale.
    "backend/app/services/lipid_registry_scan.py",
    "backend/app/api/routes/lipid_report.py",
    "frontend-shared/lipid/components/lipid-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/lipid-report/page.tsx",
    # Registri Obesitas: same contract as the two blocks above. This registry's
    # IMT is DERIVED rather than read from either source, its bands sum to the
    # total (unlike Dislipidemia's overlapping analyte counts), and its control
    # window is 3-6 months (unlike DM's monthly and Dislipidemia's quarterly) —
    # the pack states all three explicitly, so a change to any of them makes the
    # pack actively wrong, not just stale.
    "backend/app/services/obesitas_registry_scan.py",
    "backend/app/api/routes/obesitas_report.py",
    "frontend-shared/obesitas/components/obesitas-formula-card.tsx",
    "frontend-dashboard/app/(dashboard)/obesitas-report/page.tsx",
]

# Every entry above MUST also appear in REQUIRED_PINNED in
# backend/tests/test_chatbot_knowledge.py. That set is the ratchet: it lives in
# the test so this list cannot silently drop a pin and weaken the guard.


def sha256_normalized(path: Path) -> str:
    """sha256 of the file with line endings normalized to LF.

    The repo is checked out with ``core.autocrlf=true`` on Windows, so the same
    committed file is CRLF on one machine and LF on another. Hashing raw bytes
    made every pin "stale" on a Windows checkout, and re-blessing there rewrote
    the whole lock with CRLF hashes that then failed on Linux/CI. Normalizing
    makes the lock a property of the content, not of the checkout. Kept
    byte-identical to the same helper in backend/tests/test_chatbot_knowledge.py.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    pinned = {rel: sha256_normalized(REPO / rel) for rel in PINNED_SOURCES}
    LOCK.write_text(
        json.dumps(
            {
                "comment": (
                    "sha256 of the source files chatbot/knowledge/*.md were "
                    "verified against. Regenerate ONLY via "
                    "backend/scripts/bless_chatbot_knowledge.py after "
                    "re-checking the packs (chatbot/README.md)."
                ),
                "pinned": pinned,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"blessed {len(pinned)} sources -> {LOCK.relative_to(REPO)}")


if __name__ == "__main__":
    main()
