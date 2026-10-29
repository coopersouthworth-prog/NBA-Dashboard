"""Add finished games to the history tables using the live box score feed.

stats.nba.com (used by history.py) often blocks cloud servers, but the live
feed at cdn.nba.com usually doesn't. Running this after each game day keeps the
model's inputs current without a full history pull.
"""
import time
from datetime import date

from nba_api.live.nba.endpoints import boxscore

from config import REQUEST_DELAY
from db import fetch_all, fetch_value, get_conn, upsert
from pipeline.history import current_season

REGULAR_SEASON_PREFIX = "002"   # NBA game ids: 001 preseason, 002 regular season, 004 playoffs...

# Our column name -> field in the live box score's team "statistics".
STAT_FIELDS = {
    "pts": "points", "fgm": "fieldGoalsMade", "fga": "fieldGoalsAttempted",
    "fg3m": "threePointersMade", "fg3a": "threePointersAttempted",
    "ftm": "freeThrowsMade", "fta": "freeThrowsAttempted",
    "oreb": "reboundsOffensive", "dreb": "reboundsDefensive", "reb": "reboundsTotal",
    "ast": "assists", "stl": "steals", "blk": "blocks",
    "tov": "turnoversTotal", "pf": "foulsPersonal",
}


def pending_games(conn):
    """Regular-season games we've seen on the scoreboard that are finished
    (or from an earlier day) but aren't in the history tables yet."""
    latest = fetch_value(conn, "SELECT MAX(game_date) FROM games")
    return fetch_all(
        conn,
        """SELECT game_id, game_date FROM games
           WHERE game_id LIKE :prefix
             AND game_id NOT IN (SELECT game_id FROM historical_games)
             AND (status = 3 OR game_date < :latest)""",
        prefix=REGULAR_SEASON_PREFIX + "%", latest=latest)


def team_row(game_id, season, game_date, team, opp, is_home):
    stats = team["statistics"]
    row = {k: stats.get(field, stats.get("turnovers") if k == "tov" else None)
           for k, field in STAT_FIELDS.items()}
    row.update({
        "game_id": game_id, "team_id": team["teamId"], "tricode": team["teamTricode"],
        "season": season, "game_date": game_date, "is_home": int(is_home),
        "opp_team_id": opp["teamId"], "won": int(team["score"] > opp["score"]),
        "opp_pts": opp["score"],
    })
    return row


def update_results():
    with get_conn() as conn:
        pending = pending_games(conn)

    added = 0
    for i, g in enumerate(pending):
        if i:
            time.sleep(REQUEST_DELAY)
        try:
            box = boxscore.BoxScore(game_id=g["game_id"]).get_dict()["game"]
        except Exception as e:  # e.g. postponed game with no box score
            print(f"[results] skipped {g['game_id']}: {e}")
            continue
        if box.get("gameStatus") != 3:
            continue

        home, away = box["homeTeam"], box["awayTeam"]
        season = current_season(date.fromisoformat(g["game_date"]))
        rows = [team_row(g["game_id"], season, g["game_date"], home, away, True),
                team_row(g["game_id"], season, g["game_date"], away, home, False)]
        game = {
            "game_id": g["game_id"], "season": season, "game_date": g["game_date"],
            "home_team_id": home["teamId"], "home_tricode": home["teamTricode"],
            "away_team_id": away["teamId"], "away_tricode": away["teamTricode"],
            "home_pts": home["score"], "away_pts": away["score"],
            "home_win": int(home["score"] > away["score"]),
        }
        with get_conn() as conn:
            upsert(conn, "team_game_stats", rows, keys=["game_id", "team_id"])
            upsert(conn, "historical_games", [game], keys=["game_id"])
        added += 1
    print(f"[results] added {added} finished games ({len(pending)} pending)")
