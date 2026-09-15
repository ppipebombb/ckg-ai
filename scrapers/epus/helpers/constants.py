"""
Shared constants and config loader for the epus-v2 scraper.

Paths are resolved relative to the epus-v2/ folder (one level above
helpers/), so the scraper behaves identically whether launched from
inside the folder or via its absolute path.

Env-var overrides (used by Celery worker for parallel-safe runs):
  SCRAPER_CONFIG          → overrides CONFIG_PATH
  SCRAPER_OUTPUT_DIR      → overrides OUTPUT_DIR
  SCRAPER_SESSION_DIR     → overrides SESSION_DIR
  SCRAPER_SCREENSHOT_DIR  → overrides SCREENSHOT_DIR
"""

import json
import os
from pathlib import Path


EPUS_V2_DIR = Path(__file__).parent.parent

CONFIG_PATH = Path(os.environ.get("SCRAPER_CONFIG") or (EPUS_V2_DIR / "config.json"))
OUTPUT_DIR = Path(os.environ.get("SCRAPER_OUTPUT_DIR") or (EPUS_V2_DIR / "output"))
SCREENSHOT_DIR = Path(os.environ.get("SCRAPER_SCREENSHOT_DIR") or (EPUS_V2_DIR / "screenshots"))
SESSION_DIR = Path(os.environ.get("SCRAPER_SESSION_DIR") or (EPUS_V2_DIR / "session"))
SESSION_STATE_PATH = SESSION_DIR / "playwright_state.json"
SESSION_STORAGE_PATH = SESSION_DIR / "web_storage.json"

# Status dropdown on Pelayanan Medis maps to these `status_periksa` query
# param values. The site's form uses string values.
STATUS_PERIKSA = {
    "belum": "2",         # Belum Diperiksa (default landing state)
    "sudah": "3",         # Sudah Diperiksa (target filter)
}

# Target ruangan (poli). "0" = - Semua Ruangan - (all poli; UI default token).
# Old: filtered to UMUM (0001). To revert, change back to "0001".
# DEFAULT_RUANGAN_ID = "0001"
DEFAULT_RUANGAN_ID = "0"

# Per the site's DataTables UI, limit caps at 100.
DEFAULT_LIMIT = "100"


def today_ddmmyyyy() -> str:
    """Today's date in the site's DD-MM-YYYY format."""
    from datetime import datetime
    return datetime.now().strftime("%d-%m-%Y")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}
