"""
Jarvis Bookkeeping Settings & Quota Configurations
==================================================
Configures storage paths, provider limits, reset dates, and defaults for Phase 6.2.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Storage directory for bookkeeping SQLite DB
BOOKKEEPING_DIR = BASE_DIR / "data" / "bookkeeping"
BOOKKEEPING_DB_PATH = BOOKKEEPING_DIR / "usage.db"

# Default quotas and billing period start dates for external providers
# Period start format: "YYYY-MM-DD"
PROVIDER_QUOTAS = {
    "exa": {
        "quota_limit": 1000,
        "period_start": os.environ.get("EXA_QUOTA_PERIOD_START", "2026-08-10"),
    },
    "tavily": {
        "quota_limit": 1000,
        "period_start": os.environ.get("TAVILY_QUOTA_PERIOD_START", "2026-08-18"),
    },
    "firecrawl": {
        "quota_limit": 1000,
        "period_start": os.environ.get("FIRECRAWL_QUOTA_PERIOD_START", "2026-08-24"),
    },
}
