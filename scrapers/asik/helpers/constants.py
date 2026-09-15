"""
Shared constants and config loader for the ASIK scraper.

Paths are resolved relative to the asik/ folder (one level above helpers/),
so the scraper behaves identically whether launched as `python scraper.py`
from asik/ or via its absolute path.

Env-var overrides (used by Celery worker for parallel-safe runs):
  SCRAPER_CONFIG          → overrides CONFIG_PATH
  SCRAPER_OUTPUT_DIR      → overrides OUTPUT_DIR
  SCRAPER_SESSION_DIR     → overrides SESSION_DIR
  SCRAPER_SCREENSHOT_DIR  → overrides SCREENSHOT_DIR
"""

import json
import os
from pathlib import Path


ASIK_DIR = Path(__file__).parent.parent

CONFIG_PATH = Path(os.environ.get("SCRAPER_CONFIG") or (ASIK_DIR / "config.json"))
OUTPUT_DIR = Path(os.environ.get("SCRAPER_OUTPUT_DIR") or (ASIK_DIR / "output"))
SCREENSHOT_DIR = Path(os.environ.get("SCRAPER_SCREENSHOT_DIR") or (ASIK_DIR / "screenshots"))
SESSION_DIR = Path(os.environ.get("SCRAPER_SESSION_DIR") or (ASIK_DIR / "session"))
SESSION_STATE_PATH = SESSION_DIR / "playwright_state.json"
SESSION_STORAGE_PATH = SESSION_DIR / "web_storage.json"

EXPECTED_COLUMNS = [
    "No", "Nama", "Tanggal Lahir", "Nomor Tiket",
    "Nama Wali", "Unit Pelayanan", "Pemeriksaan Mandiri",
    "Pelayanan", "Pemeriksaan", "Rapor",
]

TARGET_TABS = ["Belum Pemeriksaan", "Sedang Pemeriksaan", "Selesai Pemeriksaan"]
TAB_OPTIONS = {
    "belum": [("Belum Pemeriksaan", "belum_pemeriksaan")],
    "sedang": [("Sedang Pemeriksaan", "sedang_pemeriksaan")],
    "selesai": [("Selesai Pemeriksaan", "selesai_pemeriksaan")],
    "both": [
        ("Selesai Pemeriksaan", "selesai_pemeriksaan"),
        ("Sedang Pemeriksaan", "sedang_pemeriksaan"),
    ],
    "all": [
        ("Belum Pemeriksaan", "belum_pemeriksaan"),
        ("Sedang Pemeriksaan", "sedang_pemeriksaan"),
        ("Selesai Pemeriksaan", "selesai_pemeriksaan"),
    ],
}

# Indonesian abbreviated month names used by the calendar header ("Apr 2026")
MONTH_ABBR_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "jun": 6,
    # "agt" is what the datepicker actually renders for August (id-ID);
    # "agu"/"ags" kept as defensive variants.
    "jul": 7, "agt": 8, "agu": 8, "ags": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
    # English fallbacks
    "may": 5, "aug": 8, "oct": 10, "dec": 12,
}
MONTH_NUM_TO_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
    7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}
