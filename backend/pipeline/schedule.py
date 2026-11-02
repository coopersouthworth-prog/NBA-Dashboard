"""Download the NBA's full schedule for the season.

The schedule lists every game with its status and, for finished games, the
final score, so it gives the season simulator both the current standings and
the games left to play.

The NBA blocks its schedule files from cloud servers like GitHub Actions. So
the schedule is downloaded from a home connection (python run_pipeline.py
schedule), saved in the database, and the scheduled job keeps it current by
copying final scores in from the history table, which the live box score
feed (not blocked) fills in after every game.
"""
import requests
from sqlalchemy import text

from db import fetch_all, fetch_value, get_conn, upsert
from pipeline.history import current_season

SCHEDULE_URLS = [
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json",
]
# The NBA's CDN refuses requests that don't look like they come from NBA.com,
# so send the same kind of headers nba_api uses for the live scoreboard.
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
}
REGULAR_SEASON_PREFIX = "002"


class ScheduleUnavailable(Exception):
    pass


def parse_schedule(data):
    """Turn the NBA's schedule JSON into one row per regular-season game."""
    league = data["leagueSchedule"]
    season = league.get("seasonYear") or current_season()
    rows = []
    for day in league["gameDates"]:
        for g in day["games"]:
            home, away = g["homeTeam"], g["awayTeam"]
            # Skip preseason, playoffs, and games whose teams aren't decided yet
            # (like NBA Cup knockout rounds before the group stage ends).
            if not str(g["gameId"]).startswith(REGULAR_SEASON_PREFIX):
                continue
            if not home.get("teamId") or not away.get("teamId"):
                continue
            start = g.get("gameDateTimeUTC") or g.get("gameDateUTC")
            status = int(g.get("gameStatus") or 1)
            final = status == 3
            rows.append({
                "game_id": g["gameId"],
                "season": season,
                "game_date": (g.get("gameDateEst") or start or "")[:10],
                "start_time_utc": start,
                "status": status,
                "home_team_id": home["teamId"],
                "home_tricode": home.get("teamTricode"),
                "home_team": f'{home.get("teamCity", "")} {home.get("teamName", "")}'.strip(),
                "home_score": home.get("score") if final else None,
                "away_team_id": away["teamId"],
                "away_tricode": away.get("teamTricode"),
                "away_team": f'{away.get("teamCity", "")} {away.get("teamName", "")}'.strip(),
                "away_score": away.get("score") if final else None,
            })
    return season, rows


def fetch_schedule_json():
    """Try the CDN copies first (they usually work from cloud servers), then
    stats.nba.com (works from home connections, often blocked in the cloud)."""
    problems = []
    for url in SCHEDULE_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                print(f"[schedule] source: {url.rsplit('/', 1)[-1]} (NBA CDN)")
                return resp.json()
            problems.append(f"{url}: HTTP {resp.status_code}")
        except (requests.RequestException, ValueError) as e:
            problems.append(f"{url}: {e.__class__.__name__}")
    try:
        from nba_api.stats.endpoints import scheduleleaguev2
        endpoint = scheduleleaguev2.ScheduleLeagueV2(season=current_season(), timeout=60)
        data = endpoint.nba_response.get_dict()
        print("[schedule] source: stats.nba.com (CDN copies refused: "
              + "; ".join(problems) + ")")
        return data
    except Exception as e:  # report every failure together below
        problems.append(f"stats.nba.com: {e.__class__.__name__}: {e}")
    raise ScheduleUnavailable("[schedule] couldn't download the schedule:\n  " + "\n  ".join(problems))


def sync_results_from_history():
    """Mark saved schedule games final using results already in the history table."""
    season = current_season()
    with get_conn() as conn:
        saved = fetch_value(conn, "SELECT COUNT(*) FROM schedule WHERE season = :s", s=season)
        if not saved:
            raise SystemExit("[schedule] no saved schedule to fall back on. Run "
                             "`python run_pipeline.py schedule` once from your own computer.")
        finished = fetch_all(
            conn,
            """SELECT s.game_id, h.home_pts, h.away_pts FROM schedule s
               JOIN historical_games h ON h.game_id = s.game_id
               WHERE s.season = :s AND s.status != 3""", s=season)
        if finished:
            conn.execute(text("UPDATE schedule SET status = 3, home_score = :home_pts, "
                              "away_score = :away_pts WHERE game_id = :game_id"), finished)
        played = fetch_value(conn, "SELECT COUNT(*) FROM schedule WHERE season = :s "
                                   "AND status = 3", s=season)
    print(f"[schedule] using the saved schedule ({saved} games, {played} played; "
          f"{len(finished)} newly marked final from results)")


def update_schedule():
    try:
        data = fetch_schedule_json()
    except ScheduleUnavailable as e:
        print(e)
        sync_results_from_history()
        return None
    season, rows = parse_schedule(data)
    if season != current_season():
        print(f"[schedule] warning: feed is for {season}, expected {current_season()}")
    with get_conn() as conn:
        upsert(conn, "schedule", rows, keys=["game_id"])
    played = sum(r["status"] == 3 for r in rows)
    print(f"[schedule] {season}: {len(rows)} regular-season games ({played} played, "
          f"{len(rows) - played} to go)")
    return rows
