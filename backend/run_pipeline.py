"""Command-line entry point for the data pipeline and model.

Usage (from the backend/ folder):
    python run_pipeline.py init        # create the database tables
    python run_pipeline.py today       # today's games + live scores
    python run_pipeline.py headlines   # latest headlines
    python run_pipeline.py history     # last N seasons of results (slow, run locally)
    python run_pipeline.py results     # add newly finished games to the history
    python run_pipeline.py features    # build model features -> data/features.csv
    python run_pipeline.py train       # train, evaluate, and save the model
    python run_pipeline.py predict     # refresh games + results, then predict today
    python run_pipeline.py all         # today, headlines, history, results, predict
"""
import argparse

from config import DB_PATH
from db import init_db
from pipeline.games_today import update_todays_games
from pipeline.headlines import update_headlines
from pipeline.history import update_history
from pipeline.results import update_results


def build_features():
    # Model code is imported inside these functions so data-only commands start faster.
    from model.features import FEATURE_COLUMNS, build_game_features, summarize

    games = build_game_features()
    out = DB_PATH.parent / "features.csv"
    keep = ["game_id", "season", "game_date", "home_tricode", "away_tricode",
            "home_pts", "away_pts", "home_win"] + FEATURE_COLUMNS
    games[keep].to_csv(out, index=False)
    summarize(games)
    print(f"[features] saved to {out}")


TASKS = ["init", "today", "headlines", "history", "results",
         "features", "train", "predict", "all"]


def main():
    parser = argparse.ArgumentParser(description="NBA dashboard data pipeline")
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--seasons", nargs="*", help="e.g. --seasons 2024-25 2025-26")
    args = parser.parse_args()
    t = args.task

    init_db()  # safe to run every time
    if t in ("today", "predict", "all"):
        update_todays_games()
    if t in ("headlines", "all"):
        update_headlines()
    if t in ("history", "all"):
        update_history(args.seasons)
    if t in ("results", "predict", "all"):
        update_results()
    if t == "features":
        build_features()
    if t == "train":
        from model.train import train
        train()
    if t in ("predict", "all"):
        from model.predict import predict_today
        predict_today()
    if t == "init":
        print("[db] tables ready")


if __name__ == "__main__":
    main()
