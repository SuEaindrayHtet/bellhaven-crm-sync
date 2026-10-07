"""All settings in one place. Thresholds here are the first thing to tune."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


def _load_dotenv() -> None:
    """Tiny .env reader so the project has no extra dependency."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

SITE_URL = os.environ.get("BELLHAVEN_SITE_URL", "https://analyst-assessment-production.up.railway.app")
API_URL = SITE_URL + "/api/v1"
API_TOKEN = os.environ.get("BELLHAVEN_API_TOKEN", "")
DB_PATH = Path(os.environ.get("BELLHAVEN_DB", ROOT / "data" / "proposals.db"))

# The parent account every website location should sit under.
OPERATOR_PARENT_NAME = "Bellhaven Senior Living"

# --- Matching thresholds (0-100 similarity) ---------------------------------
STREET_FUZZY_MIN = 85   # same house number + street text at least this similar
NAME_MATCH_MIN = 90     # name-only match, and only inside the same city or zip
NEAR_MISS_MIN = 80      # shown to the reviewer as "looked similar, not matched"

# Safety: if a scrape returns far fewer locations than last time, stop before
# flagging half the CRM as "no longer on the website".
MIN_SCRAPE_RATIO = 0.7

# Website care offering -> CRM care_type vocabulary.
CARE_MAP = {
    "Assisted Living": "Assisted Living",
    "Memory Support": "Memory Care",
    "Short-Term Rehabilitation & Nursing": "Skilled Nursing",
    "Independent Living": "Independent Living",
}
