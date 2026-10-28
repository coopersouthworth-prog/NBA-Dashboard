"""Command-line entry point for the data pipeline.

Usage (from the backend/ folder):
    python run_pipeline.py init        # create the database tables
    python run_pipeline.py today       # today's games + live scores
    python run_pipeline.py headlines   # latest headlines
    python run_pipeline.py history     # last N seasons of results (slow, run once)
    python run_pipeline.py all         # everything above
"""
import argparse

from db import init_db
from pipeline.games_today import update_todays_games
from pipeline.headlines import update_headlines
from pipeline.history import update_history


def main():
    parser = argparse.ArgumentParser(description="NBA dashboard data pipeline")
    parser.add_argument("task", choices=["init", "today", "headlines", "history", "all"])
    parser.add_argument("--seasons", nargs="*", help='e.g. --seasons 2024-25 2025-26')
    args = parser.parse_args()

    init_db()  # safe to run every time
    if args.task in ("today", "all"):
        update_todays_games()
    if args.task in ("headlines", "all"):
        update_headlines()
    if args.task in ("history", "all"):
        update_history(args.seasons)
    if args.task == "init":
        print("[db] tables ready")


if __name__ == "__main__":
    main()
