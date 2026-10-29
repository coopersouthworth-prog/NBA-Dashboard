"""Fetch today's games and live scores from the NBA live scoreboard."""
from datetime import datetime, timezone

from nba_api.live.nba.endpoints import scoreboard

from db import get_conn, upsert


def fetch_todays_games():
    """Return (game_date, list of game dicts) for the NBA's current scoreboard day."""
    board = scoreboard.ScoreBoard().get_dict()["scoreboard"]
    now = datetime.now(timezone.utc).isoformat()

    games = []
    for g in board["games"]:
        home, away = g["homeTeam"], g["awayTeam"]
        games.append({
            "game_id": g["gameId"],
            "game_date": board["gameDate"],
            "start_time_utc": g.get("gameTimeUTC"),
            "status": g.get("gameStatus"),
            "status_text": (g.get("gameStatusText") or "").strip(),
            "home_team_id": home["teamId"],
            "home_team": f'{home["teamCity"]} {home["teamName"]}',
            "home_tricode": home["teamTricode"],
            "home_score": home.get("score"),
            "away_team_id": away["teamId"],
            "away_team": f'{away["teamCity"]} {away["teamName"]}',
            "away_tricode": away["teamTricode"],
            "away_score": away.get("score"),
            "updated_at": now,
        })
    return board["gameDate"], games


def save_games(games):
    with get_conn() as conn:
        upsert(conn, "games", games, keys=["game_id"])


def update_todays_games():
    game_date, games = fetch_todays_games()
    save_games(games)
    print(f"[games] {len(games)} games saved for {game_date}")
    return games
