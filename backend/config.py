"""Central settings for the backend."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")   # reads backend/.env if it exists (never committed)

# Set DATABASE_URL (e.g. your Neon connection string) to use PostgreSQL.
# Leave it unset to use a local SQLite file instead.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = BASE_DIR / "data" / "nba.db"

# How many seasons of history to pull for model training (including the current one).
HISTORY_SEASONS = 5

# RSS feeds for headlines. Add more sources here as {"Source name": "feed url"}.
HEADLINE_FEEDS = {
    "ESPN": "https://www.espn.com/espn/rss/nba/news",
}

# Seconds to wait between stats.nba.com requests so we don't get rate limited.
REQUEST_DELAY = 1.5
