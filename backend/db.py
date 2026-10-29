"""Database access that works with both SQLite and PostgreSQL.

* No DATABASE_URL set  -> a local SQLite file (backend/data/nba.db)
* DATABASE_URL set     -> PostgreSQL, e.g. a free Neon database

Every query in the project goes through the helpers below and uses
:name-style parameters, so the same SQL runs on both databases.
"""
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, text

from config import DATABASE_URL, DB_PATH


def _engine_url():
    if DATABASE_URL:
        url = DATABASE_URL
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix):]
        return url
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


# pool_pre_ping quietly replaces connections a hosted database has closed.
engine = create_engine(_engine_url(), pool_pre_ping=True)
IS_POSTGRES = engine.dialect.name == "postgresql"
AUTO_ID = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

SCHEMA = [
    # Today's slate: scheduled, live, and finished games from the live scoreboard.
    """CREATE TABLE IF NOT EXISTS games (
        game_id        TEXT PRIMARY KEY,
        game_date      TEXT NOT NULL,      -- YYYY-MM-DD (NBA's scoreboard date)
        start_time_utc TEXT,
        status         INTEGER,            -- 1 = scheduled, 2 = live, 3 = final
        status_text    TEXT,
        home_team_id   INTEGER NOT NULL,
        home_team      TEXT,
        home_tricode   TEXT,
        home_score     INTEGER,
        away_team_id   INTEGER NOT NULL,
        away_team      TEXT,
        away_tricode   TEXT,
        away_score     INTEGER,
        updated_at     TEXT
    )""",
    # One row per completed historical game (the labels for the model).
    """CREATE TABLE IF NOT EXISTS historical_games (
        game_id      TEXT PRIMARY KEY,
        season       TEXT NOT NULL,
        game_date    TEXT NOT NULL,
        home_team_id INTEGER NOT NULL,
        home_tricode TEXT,
        away_team_id INTEGER NOT NULL,
        away_tricode TEXT,
        home_pts     INTEGER,
        away_pts     INTEGER,
        home_win     INTEGER
    )""",
    # One row per team per game (box score stats, used to build model features).
    """CREATE TABLE IF NOT EXISTS team_game_stats (
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
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tgs_team_date ON team_game_stats (team_id, game_date)",
    # One prediction per game, locked in before tip-off.
    """CREATE TABLE IF NOT EXISTS predictions (
        game_id             TEXT PRIMARY KEY,
        game_date           TEXT NOT NULL,
        home_team_id        INTEGER NOT NULL,
        away_team_id        INTEGER NOT NULL,
        home_win_prob       REAL NOT NULL,
        predicted_winner_id INTEGER NOT NULL,
        predicted_tricode   TEXT,
        model               TEXT,
        created_at          TEXT
    )""",
    f"""CREATE TABLE IF NOT EXISTS headlines (
        id           {AUTO_ID},
        title        TEXT NOT NULL,
        link         TEXT NOT NULL UNIQUE,
        summary      TEXT,
        source       TEXT,
        published_at TEXT,
        fetched_at   TEXT
    )""",
]


@contextmanager
def get_conn():
    """A connection inside a transaction: commits on success, rolls back on error."""
    with engine.begin() as conn:
        yield conn


def init_db():
    with get_conn() as conn:
        for statement in SCHEMA:
            conn.execute(text(statement))


# ---- Query helpers ----------------------------------------------------------
def fetch_all(conn, sql, **params):
    """Rows as a list of dicts."""
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def fetch_value(conn, sql, **params):
    """The first column of the first row (or None)."""
    return conn.execute(text(sql), params).scalar()


def read_df(conn, sql, **params):
    return pd.read_sql(text(sql), conn, params=params)


def records(df):
    """DataFrame -> list of dicts with plain Python values (no numpy types or NaN)."""
    out = []
    for row in df.to_dict("records"):
        out.append({k: (None if pd.isna(v) else v.item() if hasattr(v, "item") else v)
                    for k, v in row.items()})
    return out


def upsert(conn, table, rows, keys, update=True):
    """Insert rows; on a duplicate key, update the row (or skip it if update=False)."""
    if not rows:
        return
    cols = list(rows[0])
    if update:
        sets = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in keys)
        action = f"DO UPDATE SET {sets}"
    else:
        action = "DO NOTHING"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT ({', '.join(keys)}) {action}")
    conn.execute(text(sql), rows)


# ---- One-time move from the local SQLite file to PostgreSQL -----------------
TABLE_KEYS = {
    "historical_games": ["game_id"],
    "team_game_stats": ["game_id", "team_id"],
    "games": ["game_id"],
    "predictions": ["game_id"],
    "headlines": ["link"],
}


def copy_sqlite_to_postgres(batch=1000):
    """Copy everything in backend/data/nba.db into the DATABASE_URL database."""
    if not IS_POSTGRES:
        raise SystemExit("Set DATABASE_URL to your PostgreSQL connection string first.")
    if not DB_PATH.exists():
        raise SystemExit(f"No local SQLite database found at {DB_PATH}")

    init_db()
    source = create_engine(f"sqlite:///{DB_PATH}")
    for table, keys in TABLE_KEYS.items():
        with source.connect() as src:
            df = read_df(src, f"SELECT * FROM {table}")
        if table == "headlines":
            df = df.drop(columns="id")   # PostgreSQL assigns its own ids
        rows = records(df)
        with get_conn() as conn:
            for i in range(0, len(rows), batch):
                upsert(conn, table, rows[i:i + batch], keys, update=(table != "headlines"))
        print(f"[copy] {table}: {len(rows)} rows")
