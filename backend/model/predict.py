"""Predict today's games with the saved model and store the results.

Only games that haven't started yet (status 1) are predicted, so every
prediction is locked in before tip-off and the model's record stays honest.
"""
from datetime import datetime, timezone

import joblib
import pandas as pd

from db import fetch_value, get_conn, read_df, records, upsert
from model.features import (TEAM_COLS, add_advanced_stats, add_matchup_features,
                            compute_elo, latest_team_state, load_team_games,
                            pregame_elo)
from model.train import MODEL_PATH
from pipeline.history import current_season

# Predict regular season, playoffs, play-in, and NBA Cup final; skip preseason/All-Star.
PREDICT_PREFIXES = ("002", "004", "005", "006")


def load_upcoming_games(conn):
    latest = fetch_value(conn, "SELECT MAX(game_date) FROM games")
    games = read_df(conn, "SELECT * FROM games WHERE status = 1 AND game_date = :d", d=latest)
    return games[games["game_id"].str[:3].isin(PREDICT_PREFIXES)]


def predict_today():
    if not MODEL_PATH.exists():
        raise SystemExit("No trained model found. Run: python run_pipeline.py train")
    bundle = joblib.load(MODEL_PATH)
    model, features = bundle["model"], bundle["features"]
    model_name = bundle["metrics"]["model"]

    with get_conn() as conn:
        upcoming = load_upcoming_games(conn)
        history = read_df(conn, "SELECT * FROM historical_games")
    if upcoming.empty:
        print("[predict] no upcoming games to predict")
        return []

    history["game_date"] = pd.to_datetime(history["game_date"])
    _, ratings, last_season = compute_elo(history)
    team_games = add_advanced_stats(load_team_games())

    as_of = pd.Timestamp(upcoming["game_date"].iloc[0])
    season = current_season(as_of.date())
    state = latest_team_state(team_games, as_of, season)

    rows = []
    for g in upcoming.itertuples():
        if g.home_team_id not in state or g.away_team_id not in state:
            print(f"[predict] skipped {g.away_tricode} @ {g.home_tricode}: not enough history")
            continue
        row = {"game_id": g.game_id, "game_date": g.game_date,
               "home_team_id": g.home_team_id, "away_team_id": g.away_team_id,
               "home_tricode": g.home_tricode, "away_tricode": g.away_tricode,
               "home_elo": pregame_elo(ratings, last_season, g.home_team_id, season),
               "away_elo": pregame_elo(ratings, last_season, g.away_team_id, season)}
        for side, tid in (("home", g.home_team_id), ("away", g.away_team_id)):
            row.update({f"{side}_{c}": state[tid][c] for c in TEAM_COLS})
        rows.append(row)
    if not rows:
        return []

    df = add_matchup_features(pd.DataFrame(rows))
    df["home_win_prob"] = model.predict_proba(df[features])[:, 1]
    home_fav = df["home_win_prob"] >= 0.5
    df["predicted_winner_id"] = df["home_team_id"].where(home_fav, df["away_team_id"])
    df["predicted_tricode"] = df["home_tricode"].where(home_fav, df["away_tricode"])
    df["model"] = model_name
    df["created_at"] = datetime.now(timezone.utc).isoformat()

    cols = ["game_id", "game_date", "home_team_id", "away_team_id", "home_win_prob",
            "predicted_winner_id", "predicted_tricode", "model", "created_at"]
    rows = records(df[cols])
    with get_conn() as conn:
        upsert(conn, "predictions", rows, keys=["game_id"])

    print(f"[predict] {len(df)} games for {as_of.date()}:")
    for r in df.itertuples():
        prob = max(r.home_win_prob, 1 - r.home_win_prob)
        print(f"  {r.away_tricode:>3} @ {r.home_tricode:<3}  ->  {r.predicted_tricode} ({prob:.0%})")
    return rows
