"""Betting-market odds: conversion, matching, storage, and the API comparison."""
import json
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import db
from pipeline import odds


def test_american_odds_convert_to_probabilities():
    assert odds.american_to_prob(-200) == pytest.approx(2 / 3)
    assert odds.american_to_prob(+150) == pytest.approx(0.4)
    assert odds.american_to_prob(+100) == pytest.approx(0.5)


def _event(home, away, books, start="2026-11-02T23:30:00Z"):
    return {"home_team": home, "away_team": away, "commence_time": start,
            "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": h}, {"name": away, "price": a}]}]} for h, a in books]}


def test_consensus_removes_the_vig_and_takes_the_median():
    event = _event("Atlanta Hawks", "Miami Heat", [(-110, -110), (-200, +170), (-150, +130)])
    prob, books = odds.consensus_home_prob(event)
    assert books == 3
    implied = odds.american_to_prob(-150), odds.american_to_prob(130)
    assert prob == pytest.approx(implied[0] / sum(implied))   # the middle book, vig removed


def test_team_names_match_despite_la_vs_los_angeles():
    assert odds.tricode_for("Los Angeles Clippers") == "LAC"
    assert odds.tricode_for("Portland Trail Blazers") == "POR"
    assert odds.tricode_for("Philadelphia 76ers") == "PHI"
    upcoming = [{"game_id": "g1", "home_tricode": "LAC", "away_tricode": "LAL",
                 "start_time_utc": "2026-11-03T03:30:00Z"}]
    assert odds.match_game(_event("Los Angeles Clippers", "Los Angeles Lakers", [],
                                  start="2026-11-03T03:30:00Z"), upcoming)["game_id"] == "g1"
    # Same teams on a different day is not a match.
    assert odds.match_game(_event("Los Angeles Clippers", "Los Angeles Lakers", [],
                                  start="2026-11-06T03:30:00Z"), upcoming) is None


def _game(gid, status, home, away, home_tri, away_tri, hs=None, as_=None):
    return {"game_id": gid, "game_date": "2026-11-02", "start_time_utc": "2026-11-02T23:30:00Z",
            "status": status, "status_text": "", "home_team_id": home, "home_team": home_tri,
            "home_tricode": home_tri, "home_score": hs, "away_team_id": away,
            "away_team": away_tri, "away_tricode": away_tri, "away_score": as_,
            "updated_at": "2026-11-02T12:00:00+00:00"}


class FakeResponse:
    status_code = 200
    headers = {"x-requests-remaining": "480"}
    def __init__(self, data): self._data = data
    def json(self): return self._data


def test_odds_saved_only_for_games_not_yet_started():
    with db.get_conn() as conn:
        db.upsert(conn, "games", [_game("g1", 1, 1, 2, "ATL", "MIA"),
                                  _game("g2", 2, 3, 4, "BOS", "NYK", 50, 48)], ["game_id"])
    events = [_event("Atlanta Hawks", "Miami Heat", [(-200, +170)]),
              _event("Boston Celtics", "New York Knicks", [(-150, +130)])]
    with mock.patch.object(odds, "ODDS_API_KEY", "test"), \
         mock.patch.object(odds.requests, "get", lambda *a, **k: FakeResponse(events)):
        rows = odds.update_odds()
    assert [r["game_id"] for r in rows] == ["g1"]
    assert 0.6 < rows[0]["market_home_prob"] < 0.7


def test_missing_api_key_is_skipped_not_an_error():
    with mock.patch.object(odds, "ODDS_API_KEY", ""):
        assert odds.update_odds() == []


@pytest.fixture
def client(tmp_path):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"model": "Logistic regression"}))
    from app import main
    with mock.patch.object(main, "METRICS_PATH", metrics), TestClient(main.app) as c:
        yield c


def test_api_compares_model_and_market(client):
    with db.get_conn() as conn:
        db.upsert(conn, "games", [_game("g1", 3, 1, 2, "ATL", "MIA", 110, 100),   # home won
                                  _game("g2", 3, 3, 4, "BOS", "NYK", 95, 101)],   # away won
                  ["game_id"])
        db.upsert(conn, "predictions", [
            {"game_id": "g1", "game_date": "2026-11-02", "home_team_id": 1, "away_team_id": 2,
             "home_win_prob": 0.7, "predicted_winner_id": 1, "predicted_tricode": "ATL"},
            {"game_id": "g2", "game_date": "2026-11-02", "home_team_id": 3, "away_team_id": 4,
             "home_win_prob": 0.4, "predicted_winner_id": 4, "predicted_tricode": "NYK"}],
            ["game_id"])
        db.upsert(conn, "odds", [
            {"game_id": "g1", "market_home_prob": 0.65, "bookmakers": 5, "fetched_at": "x"},
            {"game_id": "g2", "market_home_prob": 0.6, "bookmakers": 5, "fetched_at": "x"}],
            ["game_id"])

    games = {g["game_id"]: g for g in client.get("/api/games").json()["games"]}
    assert games["g1"]["market"]["agrees_with_model"] is True
    assert games["g2"]["market"]["agrees_with_model"] is False
    assert games["g2"]["market"]["favorite_tricode"] == "BOS"

    vs = client.get("/api/model").json()["vs_market"]
    assert vs["games"] == 2
    assert vs["model_accuracy"] == 1.0 and vs["market_accuracy"] == 0.5
    assert vs["disagreements"] == 1 and vs["model_won_disagreements"] == 1
    assert vs["model_log_loss"] < vs["market_log_loss"]
