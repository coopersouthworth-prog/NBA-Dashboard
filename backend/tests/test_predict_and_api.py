"""Predictions lock before tip-off, and the API grades them correctly."""
import json
from unittest import mock

import joblib
import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

import db
from model import predict
from model.features import FEATURE_COLUMNS, build_game_features


def _game(gid, status, home, away, hs=None, as_=None, date="2026-11-02"):
    return {"game_id": gid, "game_date": date, "start_time_utc": f"{date}T23:00:00Z",
            "status": status, "status_text": "", "home_team_id": home, "home_team": f"Home {home}",
            "home_tricode": f"T{home:02d}", "home_score": hs, "away_team_id": away,
            "away_team": f"Away {away}", "away_tricode": f"T{away:02d}", "away_score": as_,
            "updated_at": "2026-11-02T12:00:00+00:00"}


@pytest.fixture
def trained_model(history, tmp_path):
    games = build_game_features()
    model = LogisticRegression(max_iter=1000).fit(games[FEATURE_COLUMNS], games["home_win"])
    path = tmp_path / "model.joblib"
    joblib.dump({"model": model, "features": FEATURE_COLUMNS,
                 "metrics": {"model": "Logistic regression"}}, path)
    with mock.patch.object(predict, "MODEL_PATH", path):
        yield


def test_predicts_only_games_that_have_not_started(trained_model):
    with db.get_conn() as conn:
        db.upsert(conn, "games", [_game("0022600010", 1, 1, 2),
                                  _game("0022600011", 2, 3, 4, 50, 48),     # already live
                                  _game("0012600012", 1, 5, 6)], ["game_id"])  # preseason
    rows = predict.predict_today()
    assert [r["game_id"] for r in rows] == ["0022600010"]
    p = rows[0]
    assert 0 < p["home_win_prob"] < 1
    assert p["predicted_winner_id"] == (1 if p["home_win_prob"] >= 0.5 else 2)


@pytest.fixture
def client(tmp_path):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"model": "Logistic regression", "test_season": "2025-26",
                                   "test_games": 1225, "test": {"accuracy": 0.681},
                                   "baselines": {"Elo favorite": {"accuracy": 0.677}}}))
    from app import main
    with mock.patch.object(main, "METRICS_PATH", metrics), TestClient(main.app) as c:
        yield c


def test_api_grades_final_games(client):
    with db.get_conn() as conn:
        db.upsert(conn, "games", [_game("0022600020", 3, 1, 2, 110, 100),    # home won
                                  _game("0022600021", 3, 3, 4, 90, 101),     # away won
                                  _game("0022600022", 1, 5, 6)], ["game_id"])
        db.upsert(conn, "predictions", [
            {"game_id": "0022600020", "game_date": "2026-11-02", "home_team_id": 1,
             "away_team_id": 2, "home_win_prob": 0.7, "predicted_winner_id": 1,
             "predicted_tricode": "T01"},
            {"game_id": "0022600021", "game_date": "2026-11-02", "home_team_id": 3,
             "away_team_id": 4, "home_win_prob": 0.6, "predicted_winner_id": 3,
             "predicted_tricode": "T03"}], ["game_id"])

    body = client.get("/api/games").json()
    by_id = {g["game_id"]: g for g in body["games"]}
    assert by_id["0022600020"]["prediction"]["correct"] is True
    assert by_id["0022600021"]["prediction"]["correct"] is False
    assert by_id["0022600022"]["prediction"] is None
    assert by_id["0022600022"]["home"]["score"] is None    # no score before tip-off

    record = client.get("/api/model").json()["season_record"]
    assert record == {"games": 2, "correct": 1, "accuracy": 0.5}


def test_api_rejects_bad_dates_and_empty_days(client):
    assert client.get("/api/games?date=not-a-date").status_code == 400
    assert client.get("/api/games?date=2020-01-01").json()["games"] == []
    assert client.get("/api/health").json() == {"status": "ok"}
