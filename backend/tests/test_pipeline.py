"""Data collection: pairing games, finished-game ingest, and headlines."""
import datetime as dt
from unittest import mock

import pytest
import requests

import db
from pipeline import headlines, results
from pipeline.history import build_tables, current_season
from tests.conftest import fake_season_rows


def test_current_season_rolls_over_in_october():
    assert current_season(dt.date(2026, 10, 1)) == "2026-27"
    assert current_season(dt.date(2027, 3, 15)) == "2026-27"
    assert current_season(dt.date(2026, 9, 30)) == "2025-26"


def test_build_tables_pairs_home_and_away():
    import numpy as np
    df = fake_season_rows("2025-26", dt.date(2025, 10, 21), 2, np.random.default_rng(0),
                          {t: 0 for t in range(1, 13)})
    games, team_stats = build_tables(df)
    assert len(team_stats) == 2 * len(games)
    g = games.iloc[0]
    rows = team_stats[team_stats["game_id"] == g["game_id"]]
    home = rows[rows["is_home"] == 1].iloc[0]
    assert home["team_id"] == g["home_team_id"] and home["opp_team_id"] == g["away_team_id"]
    assert home["won"] == g["home_win"] == int(g["home_pts"] > g["away_pts"])


def _team(tid, score, stats=False):
    t = {"teamId": tid, "teamName": f"N{tid}", "teamCity": f"C{tid}",
         "teamTricode": f"T{tid}", "score": score}
    if stats:
        t["statistics"] = {"points": score, "fieldGoalsMade": 40, "fieldGoalsAttempted": 88,
                           "threePointersMade": 12, "threePointersAttempted": 35,
                           "freeThrowsMade": 18, "freeThrowsAttempted": 22,
                           "reboundsOffensive": 10, "reboundsDefensive": 33,
                           "reboundsTotal": 43, "assists": 25, "steals": 7, "blocks": 5,
                           "turnoversTotal": 13, "foulsPersonal": 19}
    return t


def test_finished_games_are_added_to_history_once():
    with db.get_conn() as conn:
        db.upsert(conn, "games", [
            {"game_id": "0022600001", "game_date": "2026-11-01", "status": 3,
             "home_team_id": 1, "away_team_id": 2},
            {"game_id": "0012600002", "game_date": "2026-11-01", "status": 3,   # preseason
             "home_team_id": 3, "away_team_id": 4},
        ], ["game_id"])

    class FakeBox:
        def __init__(self, game_id, **kw): pass
        def get_dict(self):
            return {"game": {"gameStatus": 3, "homeTeam": _team(1, 110, True),
                             "awayTeam": _team(2, 99, True)}}

    with mock.patch.object(results.boxscore, "BoxScore", FakeBox), \
         mock.patch.object(results, "REQUEST_DELAY", 0):
        results.update_results()
        results.update_results()   # second run must not duplicate anything

    with db.get_conn() as conn:
        hist = db.fetch_all(conn, "SELECT * FROM historical_games")
        stats = db.fetch_all(conn, "SELECT * FROM team_game_stats")
    assert len(hist) == 1 and len(stats) == 2     # preseason game skipped
    assert hist[0]["season"] == "2026-27" and hist[0]["home_win"] == 1


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Story one</title><link>https://x/1</link><pubDate>Mon, 02 Nov 2026 14:00:00 GMT</pubDate></item>
<item><title>Story two</title><link>https://x/2</link></item></channel></rss>"""


class FakeResponse:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content


def test_headlines_survive_one_blocked_source_and_skip_duplicates():
    def fake_get(url, **kw):
        if "espn" in url:
            return FakeResponse(202)              # bot protection
        if "cbs" in url:
            return FakeResponse(200, RSS)
        raise requests.ConnectionError("down")

    with mock.patch.object(headlines.requests, "get", fake_get):
        headlines.update_headlines()
        headlines.update_headlines()
    with db.get_conn() as conn:
        assert db.fetch_value(conn, "SELECT COUNT(*) FROM headlines") == 2


def test_headlines_fail_loudly_when_every_source_is_empty():
    with mock.patch.object(headlines.requests, "get", lambda url, **kw: FakeResponse(403)):
        with pytest.raises(SystemExit):
            headlines.update_headlines()
