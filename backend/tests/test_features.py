"""The most important property of the model: no data leakage."""
import numpy as np
import pandas as pd
from sqlalchemy import text

import db
from model.features import (FEATURE_COLUMNS, ELO_START, add_advanced_stats,
                            add_matchup_features, build_game_features, compute_elo,
                            latest_team_state, load_team_games, pregame_elo)


def test_every_game_has_complete_features(history):
    games = build_game_features()
    assert len(games) > 300
    assert not games[FEATURE_COLUMNS].isna().any().any()
    assert set(games["home_win"].unique()) <= {0, 1}


def test_changing_a_result_never_changes_that_games_features(history):
    """If a game's features could see its own result, flipping the result would
    change them. They must stay identical, for that game and every earlier one."""
    before = build_game_features().set_index("game_id")
    target = before.sort_values("game_date").index[len(before) // 2]
    target_date = before.loc[target, "game_date"]

    with db.get_conn() as conn:   # flip the winner and wreck the box score
        conn.execute(text("UPDATE historical_games SET home_pts = away_pts - 30, "
                          "home_win = 1 - home_win WHERE game_id = :g"), {"g": target})
        conn.execute(text("UPDATE team_game_stats SET pts = 0, fgm = 0, won = 1 - won "
                          "WHERE game_id = :g"), {"g": target})
        conn.execute(text("UPDATE team_game_stats SET opp_pts = 0 WHERE game_id = :g"), {"g": target})

    after = build_game_features().set_index("game_id")
    up_to_target = before.index[before["game_date"] <= target_date]
    pd.testing.assert_frame_equal(before.loc[up_to_target, FEATURE_COLUMNS],
                                  after.loc[up_to_target, FEATURE_COLUMNS])
    # ...while later games DO change, proving the edit actually took effect.
    later = before.index[before["game_date"] > target_date]
    assert not np.allclose(before.loc[later, FEATURE_COLUMNS], after.loc[later, FEATURE_COLUMNS])


def test_live_features_match_training_features(history):
    """Predictions must compute features exactly like training did."""
    train = build_game_features()
    game = train[train["season"] == "2025-26"].iloc[100]
    with db.get_conn() as conn:
        hist = db.read_df(conn, "SELECT * FROM historical_games")
    hist["game_date"] = pd.to_datetime(hist["game_date"])
    _, ratings, last_season = compute_elo(hist[hist["game_date"] < game["game_date"]])
    state = latest_team_state(add_advanced_stats(load_team_games()), game["game_date"], game["season"])

    row = {"home_elo": pregame_elo(ratings, last_season, game["home_team_id"], game["season"]),
           "away_elo": pregame_elo(ratings, last_season, game["away_team_id"], game["season"])}
    for side in ("home", "away"):
        row.update({f"{side}_{k}": v for k, v in state[game[f"{side}_team_id"]].items()})
    live = add_matchup_features(pd.DataFrame([row]))
    np.testing.assert_allclose(live[FEATURE_COLUMNS].iloc[0].astype(float),
                               game[FEATURE_COLUMNS].astype(float), atol=1e-9)


def test_elo_is_zero_sum_and_starts_even(history):
    with db.get_conn() as conn:
        hist = db.read_df(conn, "SELECT * FROM historical_games WHERE season = '2024-25'")
    hist["game_date"] = pd.to_datetime(hist["game_date"])
    games, ratings, _ = compute_elo(hist)
    assert games.iloc[0]["home_elo"] == ELO_START
    assert abs(sum(ratings.values()) - ELO_START * len(ratings)) < 1e-6


def test_better_teams_get_higher_elo(history):
    strength = history
    with db.get_conn() as conn:
        hist = db.read_df(conn, "SELECT * FROM historical_games")
    hist["game_date"] = pd.to_datetime(hist["game_date"])
    _, ratings, _ = compute_elo(hist)
    best = max(strength, key=strength.get)
    worst = min(strength, key=strength.get)
    assert ratings[best] > ratings[worst]
