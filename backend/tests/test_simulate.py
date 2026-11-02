"""Season simulator: the odds must add up, and better teams must do better."""
import numpy as np
import pytest

from model.simulate import CONFERENCE, series_win_prob, simulate_season
from pipeline.schedule import parse_schedule


def test_series_math():
    assert series_win_prob(0.5, 0.5) == pytest.approx(0.5)
    assert series_win_prob(1.0, 1.0) == pytest.approx(1.0)
    # Winning 60% of every game wins a best-of-seven about 71% of the time.
    assert series_win_prob(0.6, 0.6) == pytest.approx(0.7102, abs=1e-4)
    # Home court helps: same road odds, better home odds -> better series odds.
    assert series_win_prob(0.7, 0.5) > series_win_prob(0.5, 0.5)


@pytest.fixture(scope="module")
def league():
    """30 real teams, 20 games left each, with team 0 much stronger than the rest."""
    tricodes = sorted(CONFERENCE)
    n = len(tricodes)
    rng = np.random.default_rng(0)
    remaining = [(int(h), int(a)) for _ in range(300)
                 for h, a in [rng.choice(n, 2, replace=False)]]
    rating = np.zeros(n)
    rating[0] = 1.5
    home_prob = 1 / (1 + np.exp(-(rating[:, None] - rating[None, :] + 0.2)))
    p_left = [home_prob[h, a] for h, a in remaining]
    result = simulate_season(
        team_ids=list(range(n)), conference=[CONFERENCE[t] for t in tricodes],
        wins=np.full(n, 5), losses=np.full(n, 5), remaining=remaining,
        p_remaining=p_left, home_prob=home_prob, games_left_frac=0.8,
        n_sims=2000, seed=1)
    return result


def test_probabilities_add_up(league):
    for conf in ("East", "West"):
        c = league[league["conference"] == conf]
        assert c["p_top6"].sum() == pytest.approx(6)
        assert c["p_playin"].sum() == pytest.approx(4)
        assert c["p_playoffs"].sum() == pytest.approx(8)
        assert c["p_second_round"].sum() == pytest.approx(4)
        assert c["p_conf_finals"].sum() == pytest.approx(2)
        assert c["p_finals"].sum() == pytest.approx(1)
    assert league["p_title"].sum() == pytest.approx(1)


def test_rounds_get_harder(league):
    for col_a, col_b in (("p_playoffs", "p_second_round"), ("p_second_round", "p_conf_finals"),
                         ("p_conf_finals", "p_finals"), ("p_finals", "p_title")):
        assert (league[col_a] >= league[col_b] - 1e-9).all()


def test_strongest_team_is_the_favorite(league):
    best = league.iloc[0]
    assert league["p_title"].idxmax() == 0
    # Compare win percentage: the random test schedule gives teams different game counts.
    win_pct = league["proj_wins"] / (league["proj_wins"] + league["proj_losses"])
    assert win_pct.idxmax() == 0
    assert best["wins"] + best["losses"] < best["proj_wins"] + best["proj_losses"]


def test_finished_season_is_certain():
    """With no games left, the standings are final and playoff spots are locked."""
    tricodes = sorted(CONFERENCE)
    n = len(tricodes)
    wins = np.arange(n) + 10
    result = simulate_season(list(range(n)), [CONFERENCE[t] for t in tricodes], wins,
                             82 - wins, remaining=[], p_remaining=[],
                             home_prob=np.full((n, n), 0.5), games_left_frac=0,
                             n_sims=200, seed=2)
    east = result[result["conference"] == "East"].sort_values("wins", ascending=False)
    assert (east["p_top6"].iloc[:6] == 1).all() and (east["p_top6"].iloc[6:] == 0).all()
    assert (result["proj_wins"] == result["wins"]).all()


def test_schedule_parsing_skips_non_regular_season_and_unknown_teams():
    team = lambda tid, tri, score: {"teamId": tid, "teamTricode": tri, "teamCity": "C",
                                    "teamName": tri, "score": score}
    data = {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [{"games": [
        {"gameId": "0022600001", "gameStatus": 3, "gameDateEst": "2026-10-21T00:00:00Z",
         "gameDateTimeUTC": "2026-10-21T23:30:00Z",
         "homeTeam": team(1, "BOS", 110), "awayTeam": team(2, "NYK", 100)},
        {"gameId": "0022600002", "gameStatus": 1, "gameDateEst": "2026-12-01T00:00:00Z",
         "gameDateTimeUTC": "2026-12-02T00:00:00Z",
         "homeTeam": team(1, "BOS", 0), "awayTeam": team(3, "MIA", 0)},
        {"gameId": "0012600003", "gameStatus": 3, "homeTeam": team(1, "BOS", 1),
         "awayTeam": team(2, "NYK", 0)},                                    # preseason
        {"gameId": "0062600004", "gameStatus": 1, "homeTeam": team(0, "", 0),
         "awayTeam": team(0, "", 0)},                                       # TBD teams
    ]}]}}
    season, rows = parse_schedule(data)
    assert season == "2026-27"
    assert [r["game_id"] for r in rows] == ["0022600001", "0022600002"]
    assert rows[0]["home_score"] == 110 and rows[1]["home_score"] is None
    assert rows[0]["game_date"] == "2026-10-21"


def test_unscheduled_cup_games_are_filled_in_conference():
    """Until December, the schedule lists 80 games per team; the simulator adds
    the missing two per team against same-conference opponents."""
    from model.simulate import SEASON_GAMES, fill_unscheduled_games
    tricodes = sorted(CONFERENCE)
    conference = [CONFERENCE[t] for t in tricodes]
    played = np.full(30, 10)
    # Everyone scheduled for 80: 70 remaining each, built as a simple rotation.
    remaining = [(i, (i + k) % 30) for k in range(1, 36) for i in range(30)][:70 * 30 // 2]
    # Trim so every team has exactly 80 scheduled.
    trimmed, per_team = [], np.array(played)
    for h, a in remaining:
        if per_team[h] < 80 and per_team[a] < 80:
            trimmed.append((h, a)); per_team[h] += 1; per_team[a] += 1
    assert (per_team <= 80).all()
    extra = fill_unscheduled_games(trimmed, played, conference, np.random.default_rng(0))
    total = per_team + np.bincount(np.ravel(extra), minlength=30)
    assert (total <= SEASON_GAMES).all() and total.sum() >= SEASON_GAMES * 30 - 4
    assert all(conference[h] == conference[a] for h, a in extra)


def test_blocked_schedule_falls_back_to_saved_copy_and_updates_results():
    """In the cloud the NBA refuses the schedule; the saved copy is used instead,
    with finished games filled in from the history table."""
    from unittest import mock

    import db
    from pipeline import schedule

    game = {"game_id": "0022600050", "season": "2026-27", "game_date": "2026-11-01",
            "start_time_utc": "2026-11-01T23:30:00Z", "status": 1, "home_team_id": 1,
            "home_tricode": "BOS", "home_team": "Boston Celtics", "home_score": None,
            "away_team_id": 2, "away_tricode": "NYK", "away_team": "New York Knicks",
            "away_score": None}
    with db.get_conn() as conn:
        db.upsert(conn, "schedule", [game], ["game_id"])
        db.upsert(conn, "historical_games", [{
            "game_id": "0022600050", "season": "2026-27", "game_date": "2026-11-01",
            "home_team_id": 1, "home_tricode": "BOS", "away_team_id": 2,
            "away_tricode": "NYK", "home_pts": 112, "away_pts": 104, "home_win": 1}],
            ["game_id"])

    def blocked():
        raise schedule.ScheduleUnavailable("403 everywhere")

    with mock.patch.object(schedule, "fetch_schedule_json", blocked), \
         mock.patch.object(schedule, "current_season", lambda: "2026-27"):
        schedule.update_schedule()
    with db.get_conn() as conn:
        row = db.fetch_all(conn, "SELECT * FROM schedule")[0]
    assert row["status"] == 3 and row["home_score"] == 112 and row["away_score"] == 104


def test_blocked_schedule_with_nothing_saved_says_what_to_do():
    from unittest import mock

    from pipeline import schedule

    def blocked():
        raise schedule.ScheduleUnavailable("403 everywhere")

    with mock.patch.object(schedule, "fetch_schedule_json", blocked):
        with pytest.raises(SystemExit, match="from your own computer"):
            schedule.update_schedule()
