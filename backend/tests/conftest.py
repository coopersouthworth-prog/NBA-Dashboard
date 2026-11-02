"""Shared test setup.

Every test runs against a throwaway SQLite file, never your real database:
DATABASE_URL is set here, before any project code is imported, and
python-dotenv never overrides a variable that is already set.
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="nba-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

import db  # noqa: E402
from pipeline.history import STAT_COLS, build_tables  # noqa: E402

TABLES = ["games", "historical_games", "team_game_stats", "predictions", "headlines"]


@pytest.fixture(autouse=True)
def clean_db():
    """Fresh, empty tables for every test."""
    assert not db.IS_POSTGRES and "nba-tests-" in str(db.engine.url), "tests must not touch a real DB"
    db.init_db()
    with db.get_conn() as conn:
        for t in TABLES:
            conn.execute(text(f"DELETE FROM {t}"))
    yield


def fake_season_rows(season, start, days, rng, strength, n_teams=12):
    """Rows shaped like stats.nba.com's LeagueGameFinder output, for one season."""
    rows, gid = [], int(season[:4]) * 10000
    teams = list(range(1, n_teams + 1))
    for day in range(days):
        date = start + dt.timedelta(days=day)
        order = rng.permutation(teams)
        for h, a in zip(order[::2][:4], order[1::2][:4]):
            gid += 1
            margin = strength[h] - strength[a] + 3 + rng.normal(0, 12)
            hp, ap = int(110 + margin / 2), int(110 - margin / 2)
            hp += hp == ap
            for t, pts, opp_pts, home, opp in ((h, hp, ap, True, a), (a, ap, hp, False, h)):
                st = {c: int(rng.integers(5, 40)) for c in STAT_COLS}
                st.update(PTS=pts, FGA=88, FGM=pts // 3, FG3M=12, FTA=int(rng.integers(15, 30)))
                rows.append(dict(
                    GAME_ID=f"{gid:010d}", TEAM_ID=int(t), TEAM_ABBREVIATION=f"T{t:02d}",
                    GAME_DATE=str(date), WL="W" if pts > opp_pts else "L",
                    MATCHUP=f"T{t:02d} vs. T{opp:02d}" if home else f"T{t:02d} @ T{opp:02d}", **st))
    df = pd.DataFrame(rows)
    df["IS_HOME"] = df["MATCHUP"].str.contains("vs.", regex=False)
    df["SEASON"] = season
    return df


@pytest.fixture
def history():
    """Two short fake seasons stored through the real pipeline code."""
    rng = np.random.default_rng(7)
    strength = {t: rng.normal(0, 5) for t in range(1, 13)}
    for season, start in (("2024-25", dt.date(2024, 10, 22)), ("2025-26", dt.date(2025, 10, 21))):
        games, team_stats = build_tables(fake_season_rows(season, start, 40, rng, strength))
        with db.get_conn() as conn:
            db.upsert(conn, "historical_games", db.records(games), ["game_id"])
            db.upsert(conn, "team_game_stats", db.records(team_stats), ["game_id", "team_id"])
    return strength
