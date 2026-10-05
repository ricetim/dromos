from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data" / "fit_files")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

_db_dir = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
_db_dir.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{_db_dir}/dromos.db"

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN", "")

COROS_EMAIL = os.getenv("COROS_EMAIL", "")
COROS_PASSWORD = os.getenv("COROS_PASSWORD", "")

# IANA timezone used to decide which calendar day an activity belongs to.
# Activities are stored as naive UTC; day-bucketing converts to this zone first
# so the day flips at local midnight. Mirrors frontend src/config.ts DISPLAY_TZ.
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "America/Los_Angeles")

# CARTO basemaps (the "light" and "dark" map styles) require an API key. Without
# it CARTO serves an "API KEY REQUIRED" watermark tile — see routers/tiles.py.
# Only the server-side tile proxy uses it; it is never sent to the browser.
CARTO_API_KEY = os.getenv("CARTO_API_KEY", "")
