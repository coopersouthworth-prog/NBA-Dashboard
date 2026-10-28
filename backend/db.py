"""SQLite connection helper and schema."""
import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
-- Today's slate: scheduled, live, and finished games from the live scoreboard.
CREATE TABLE IF NOT EXISTS games (
    game_id        TEXT PRIMARY KEY,
    game_date      TEXT NOT NULL,      -- YYYY-MM-DD (NBA's scoreboard date)
    start_time_utc TEXT,
    status         INTEGER,            -- 1 = scheduled, 2 = live, 3 = final
    status_text    TEXT,               -- e.g. "7:30 pm ET", "Q3 4:12", "Final"
    home_team_id   INTEGER NOT NULL,
    home_team      TEXT,
    home_tricode   TEXT,
    home_score     INTEGER,
    away_team_id   INTEGER NOT NULL,
    away_team      TEXT,
    away_tricode   TEXT,
    away_score     INTEGER,
    updated_at     TEXT
);

-- One row per completed historical game (the labels for the model).
CREATE TABLE IF NOT EXISTS historical_games (
    game_id      TEXT PRIMARY KEY,
    season       TEXT NOT NULL,        -- e.g. "2025-26"
    game_date    TEXT NOT NULL,
    home_team_id INTEGER NOT NULL,
    home_tricode TEXT,
    away_team_id INTEGER NOT NULL,
    away_tricode TEXT,
    home_pts     INTEGER,
    away_pts     INTEGER,
    home_win     INTEGER               -- 1 if the home team won
);

-- One row per team per game (box score stats, used to build model features).
CREATE TABLE IF NOT EXISTS team_game_stats (
    game_id     TEXT NOT NULL,
    team_id     INTEGER NOT NULL,
    tricode     TEXT,
    season      TEXT NOT NULL,
    game_date   TEXT NOT NULL,
    is_home     INTEGER,
    opp_team_id INTEGER,
    won         INTEGER,
    pts INTEGER, opp_pts INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
    ftm INTEGER, fta INTEGER, oreb INTEGER, dreb INTEGER, reb INTEGER,
    ast INTEGER, stl INTEGER, blk INTEGER, tov INTEGER, pf INTEGER,
    PRIMARY KEY (game_id, team_id)
);
CREATE INDEX IF NOT EXISTS idx_tgs_team_date ON team_game_stats (team_id, game_date);

CREATE TABLE IF NOT EXISTS headlines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    link         TEXT NOT NULL UNIQUE,
    summary      TEXT,
    source       TEXT,
    published_at TEXT,
    fetched_at   TEXT
);
"""


@contextmanager
def get_conn():
    """Open a connection, commit on success, always close."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
