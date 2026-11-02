"""Save the betting market's win probability for each upcoming game.

Sportsbook moneyline odds are converted to probabilities, the bookmaker's
built-in margin (the "vig") is removed so each game's two sides add up to
100%, and the median across books becomes the market's estimate. Like the
model's predictions, odds are only saved for games that haven't started.

Uses The Odds API (the-odds-api.com). The free plan has 500 credits a month;
each call here costs 1 credit (one market, one region), so running twice a
day uses about 60.
"""
from datetime import datetime, timezone
from statistics import median

import requests

from config import ODDS_API_KEY
from db import fetch_all, get_conn, upsert

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

# Team nickname -> tricode. Matching on nicknames avoids "LA" vs "Los Angeles" mismatches.
NICKNAMES = {
    "Hawks": "ATL", "Celtics": "BOS", "Nets": "BKN", "Hornets": "CHA", "Bulls": "CHI",
    "Cavaliers": "CLE", "Mavericks": "DAL", "Nuggets": "DEN", "Pistons": "DET",
    "Warriors": "GSW", "Rockets": "HOU", "Pacers": "IND", "Clippers": "LAC", "Lakers": "LAL",
    "Grizzlies": "MEM", "Heat": "MIA", "Bucks": "MIL", "Timberwolves": "MIN",
    "Pelicans": "NOP", "Knicks": "NYK", "Thunder": "OKC", "Magic": "ORL", "76ers": "PHI",
    "Suns": "PHX", "Trail Blazers": "POR", "Kings": "SAC", "Spurs": "SAS", "Raptors": "TOR",
    "Jazz": "UTA", "Wizards": "WAS",
}


def tricode_for(team_name):
    for nickname, tricode in NICKNAMES.items():
        if team_name.endswith(nickname):
            return tricode
    return None


def american_to_prob(price):
    """Moneyline odds -> implied probability (still includes the vig)."""
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def consensus_home_prob(event):
    """Median vig-free home win probability across bookmakers, and how many books."""
    home, away = event["home_team"], event["away_team"]
    probs = []
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            prices = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if home in prices and away in prices:
                h, a = american_to_prob(prices[home]), american_to_prob(prices[away])
                probs.append(h / (h + a))   # remove the vig
    return (median(probs), len(probs)) if probs else (None, 0)


def match_game(event, upcoming):
    """Find our scheduled game for an Odds API event: same teams, start within 12 hours."""
    home, away = tricode_for(event["home_team"]), tricode_for(event["away_team"])
    start = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
    for g in upcoming:
        if g["home_tricode"] != home or g["away_tricode"] != away or not g["start_time_utc"]:
            continue
        ours = datetime.fromisoformat(g["start_time_utc"].replace("Z", "+00:00"))
        if abs((ours - start).total_seconds()) < 12 * 3600:
            return g
    return None


def update_odds():
    if not ODDS_API_KEY:
        print("[odds] skipped: no ODDS_API_KEY set")
        return []
    with get_conn() as conn:
        upcoming = fetch_all(conn, "SELECT * FROM games WHERE status = 1")
    if not upcoming:
        print("[odds] no upcoming games")
        return []

    try:
        resp = requests.get(ODDS_URL, timeout=20, params={
            "apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american"})
    except requests.RequestException as e:
        print(f"[odds] request failed: {e}")
        return []
    if resp.status_code != 200:
        print(f"[odds] HTTP {resp.status_code}: {resp.text[:200]}")
        return []

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for event in resp.json():
        game = match_game(event, upcoming)
        prob, books = consensus_home_prob(event)
        if game and prob is not None:
            rows.append({"game_id": game["game_id"], "market_home_prob": round(prob, 4),
                         "bookmakers": books, "fetched_at": now})
    with get_conn() as conn:
        upsert(conn, "odds", rows, keys=["game_id"])

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] saved market odds for {len(rows)} of {len(upcoming)} upcoming games "
          f"({remaining} API credits left this month)")
    return rows
