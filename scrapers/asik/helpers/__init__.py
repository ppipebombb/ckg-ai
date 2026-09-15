"""Helpers used by asik/scraper.py.

Each submodule is a focused group of Playwright helpers:
  - constants:  paths, table columns, tab / month maps, load_config
  - browser:    APIInterceptor + persistent session (cookies, localStorage)
  - auth:       login, navigate_to_pelayanan, close_popups
  - calendar:   set_date_filter (single-date picker)
  - pagination: click_next_page, navigate_to_page_num, row counters
"""

from .constants import (
    ASIK_DIR,
    CONFIG_PATH,
    OUTPUT_DIR,
    SCREENSHOT_DIR,
    SESSION_DIR,
    SESSION_STATE_PATH,
    SESSION_STORAGE_PATH,
    EXPECTED_COLUMNS,
    TARGET_TABS,
    TAB_OPTIONS,
    MONTH_ABBR_TO_NUM,
    MONTH_NUM_TO_ABBR,
    load_config,
)
from .browser import (
    APIInterceptor,
    launch_persistent_context,
    restore_saved_auth_state,
    save_auth_state,
)
from .auth import login, navigate_to_pelayanan, close_popups, verify_session
from .calendar import set_date_filter
from .pagination import (
    click_next_page,
    navigate_to_page_num,
    get_current_page_num,
    count_visible_patient_rows,
)

__all__ = [
    # constants
    "ASIK_DIR", "CONFIG_PATH", "OUTPUT_DIR", "SCREENSHOT_DIR",
    "SESSION_DIR", "SESSION_STATE_PATH", "SESSION_STORAGE_PATH",
    "EXPECTED_COLUMNS", "TARGET_TABS", "TAB_OPTIONS",
    "MONTH_ABBR_TO_NUM", "MONTH_NUM_TO_ABBR", "load_config",
    # browser
    "APIInterceptor", "launch_persistent_context",
    "restore_saved_auth_state", "save_auth_state",
    # auth
    "login", "navigate_to_pelayanan", "close_popups", "verify_session",
    # calendar
    "set_date_filter",
    # pagination
    "click_next_page", "navigate_to_page_num",
    "get_current_page_num", "count_visible_patient_rows",
]
