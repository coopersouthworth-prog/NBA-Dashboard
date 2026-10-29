"""Pull historical regular-season results and box scores for model training."""
import time
from datetime import date

import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder

from config import HISTORY_SEASONS, REQUEST_DELAY
from db import get_conn, records, upsert

STAT_COLS = ["PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
             "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF"]


def current_season(today=None):
    """NBA seasons start in October, so Oct 2026 -> '2026-27', Mar 2027 -> '2026-27'."""
    today = today or date.today()
    start = today.year if today.month >= 10 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def recent_seasons(n=HISTORY_SEASONS):
    start = int(current_season()[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(start - n + 1, start + 1)]


def fetch_season(season):
    """One row per team per game for a season (completed games only)."""
    df = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        league_id_nullable="00",              # NBA only
        season_type_nullable="Regular Season",
        timeout=60,
    ).get_data_frames()[0]

    df = df[df["WL"].notna()].copy()          # drop games not played yet
    df["IS_HOME"] = df["MATCHUP"].str.contains("vs.", regex=False)

    # Keep only games where we have both teams' rows.
    counts = df.groupby("GAME_ID")["TEAM_ID"].transform("count")
    df = df[counts == 2]
    df["SEASON"] = season
    return df


def build_tables(df):
    """Turn the raw team-game rows into the two tables we store."""
    # Attach each row's opponent id and points.
    opp = df[["GAME_ID", "TEAM_ID", "PTS"]].rename(
        columns={"TEAM_ID": "OPP_TEAM_ID", "PTS": "OPP_PTS"})
    tg = df.merge(opp, on="GAME_ID")
    tg = tg[tg["TEAM_ID"] != tg["OPP_TEAM_ID"]]

    team_stats = pd.DataFrame({
        "game_id": tg["GAME_ID"],
        "team_id": tg["TEAM_ID"],
        "tricode": tg["TEAM_ABBREVIATION"],
        "season": tg["SEASON"],
        "game_date": tg["GAME_DATE"],
        "is_home": tg["IS_HOME"].astype(int),
        "opp_team_id": tg["OPP_TEAM_ID"],
        "won": (tg["WL"] == "W").astype(int),
        "opp_pts": tg["OPP_PTS"],
        **{c.lower(): tg[c] for c in STAT_COLS},
    })

    home = df[df["IS_HOME"]]
    away = df[~df["IS_HOME"]]
    g = home.merge(away, on="GAME_ID", suffixes=("_H", "_A"))
    games = pd.DataFrame({
        "game_id": g["GAME_ID"],
        "season": g["SEASON_H"],
        "game_date": g["GAME_DATE_H"],
        "home_team_id": g["TEAM_ID_H"],
        "home_tricode": g["TEAM_ABBREVIATION_H"],
        "away_team_id": g["TEAM_ID_A"],
        "away_tricode": g["TEAM_ABBREVIATION_A"],
        "home_pts": g["PTS_H"],
        "away_pts": g["PTS_A"],
        "home_win": (g["PTS_H"] > g["PTS_A"]).astype(int),
    })
    return games, team_stats


def update_history(seasons=None):
    seasons = seasons or recent_seasons()
    for i, season in enumerate(seasons):
        if i:
            time.sleep(REQUEST_DELAY)
        raw = fetch_season(season)
        games, team_stats = build_tables(raw)
        with get_conn() as conn:
            upsert(conn, "historical_games", records(games), keys=["game_id"])
            upsert(conn, "team_game_stats", records(team_stats), keys=["game_id", "team_id"])
        print(f"[history] {season}: {len(games)} games")
