"""Simulate the rest of the regular season and the playoffs, many times over.

Each simulation:
  1. Draws a random "true strength" adjustment for every team, because a team's
     current numbers are only an estimate of how good it really is. The spread
     shrinks as the season goes on and there's less left to learn.
  2. Plays every remaining regular-season game, using the model's win
     probability for that matchup (adjusted by the strength draws).
  3. Seeds each conference, plays the play-in tournament (7th-10th), and plays
     out a best-of-seven bracket through the Finals.
Counting how often each outcome happens across all simulations gives each
team's projected record and its odds of reaching each round.

Simplifications, worth knowing: ties in the standings are broken randomly
(the real NBA tiebreakers are more involved), and team strength stays fixed
within a simulated season instead of drifting week to week.
"""
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from db import get_conn, read_df, records, upsert
from model.features import (MAX_REST, TEAM_COLS, add_advanced_stats, add_matchup_features,
                            compute_elo, latest_team_state, load_team_games, pregame_elo)
from model.train import MODEL_PATH
from pipeline.history import current_season

N_SIMS = 10_000
SEASON_GAMES = 82
# Spread (in log-odds) of each team's random strength adjustment at the start
# of a season; it shrinks with the square root of the share of games left.
STRENGTH_SD_FULL = 0.35

CONFERENCE = {
    "ATL": "East", "BOS": "East", "BKN": "East", "CHA": "East", "CHI": "East",
    "CLE": "East", "DET": "East", "IND": "East", "MIA": "East", "MIL": "East",
    "NYK": "East", "ORL": "East", "PHI": "East", "TOR": "East", "WAS": "East",
    "DAL": "West", "DEN": "West", "GSW": "West", "HOU": "West", "LAC": "West",
    "LAL": "West", "MEM": "West", "MIN": "West", "NOP": "West", "OKC": "West",
    "PHX": "West", "POR": "West", "SAC": "West", "SAS": "West", "UTA": "West",
}

# Best-of-seven: games 1, 2, 5, 7 at the higher seed's arena (True = higher seed home).
SERIES_HOME = [True, True, False, False, True, False, True]


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def series_win_prob(p_home, p_away):
    """Chance the higher seed wins a best-of-seven, given its chance to win
    each home game and each road game."""
    states = {(0, 0): 1.0}   # (higher seed wins, losses) -> probability
    won = 0.0
    for at_home in SERIES_HOME:
        p = p_home if at_home else p_away
        nxt = {}
        for (w, l), prob in states.items():
            for dw, dl, q in ((1, 0, p), (0, 1, 1 - p)):
                key = (w + dw, l + dl)
                if key[0] == 4:
                    won += prob * q
                elif key[1] < 4:
                    nxt[key] = nxt.get(key, 0) + prob * q
        states = nxt
    return won


class Sim:
    """Playoff helpers for one simulated season."""

    def __init__(self, home_prob, strength, rng):
        self.home_prob, self.strength, self.rng = home_prob, strength, rng

    def p_game(self, home, away):
        """Chance `home` beats `away` at home, after this simulation's strength draws."""
        x = _logit(self.home_prob[home, away]) + self.strength[home] - self.strength[away]
        return float(_sigmoid(x))

    def game(self, home, away):
        return home if self.rng.random() < self.p_game(home, away) else away

    def series(self, high, low):
        p = series_win_prob(self.p_game(high, low), 1 - self.p_game(low, high))
        return high if self.rng.random() < p else low


def simulate_season(team_ids, conference, wins, losses, remaining, p_remaining,
                    home_prob, games_left_frac, n_sims=N_SIMS, seed=None):
    """Core simulation, separate from the database so it can be tested directly.

    team_ids:     list of team ids; position i in every array refers to team_ids[i]
    conference:   "East"/"West" for each team
    wins, losses: current records (arrays)
    remaining:    (home_index, away_index) for each remaining game
    p_remaining:  model's home win probability for each remaining game
    home_prob:    [i, j] = chance team i beats team j at i's arena (for the playoffs)
    """
    rng = np.random.default_rng(seed)
    n = len(team_ids)
    remaining = np.asarray(remaining, dtype=int).reshape(-1, 2)
    sd = STRENGTH_SD_FULL * np.sqrt(max(games_left_frac, 0.0))
    strength = rng.normal(0, sd, size=(n_sims, n))

    # ---- Regular season, all simulations at once ---------------------------
    sim_wins = np.tile(np.asarray(wins, dtype=float), (n_sims, 1))
    if len(remaining):
        home, away = remaining[:, 0], remaining[:, 1]
        logits = _logit(np.asarray(p_remaining))[None, :] + strength[:, home] - strength[:, away]
        home_won = rng.random(logits.shape) < _sigmoid(logits)
        np.add.at(sim_wins, (slice(None), home), home_won)
        np.add.at(sim_wins, (slice(None), away), ~home_won)
    games_played = np.asarray(wins) + np.asarray(losses) + np.bincount(
        remaining.ravel(), minlength=n)

    # ---- Playoffs, one simulation at a time --------------------------------
    counts = {k: np.zeros(n) for k in
              ("top6", "playin", "playoffs", "second_round", "conf_finals", "finals", "title")}
    conf = np.asarray(conference)
    for s in range(n_sims):
        sim = Sim(home_prob, strength[s], rng)
        order_key = sim_wins[s] + rng.random(n) * 0.5        # random tiebreaks
        champs = []
        for c in ("East", "West"):
            members = np.flatnonzero(conf == c)
            ranked = list(members[np.argsort(-order_key[members])])
            counts["top6"][ranked[:6]] += 1
            counts["playin"][ranked[6:10]] += 1

            # Play-in: 7 hosts 8 (winner is the 7 seed); 9 hosts 10; the 7/8
            # loser hosts the 9/10 winner for the 8 seed.
            s7, s8, s9, s10 = ranked[6:10]
            seven = sim.game(s7, s8)
            survivor = sim.game(s9, s10)
            eight = sim.game(s7 + s8 - seven, survivor)
            seeds = ranked[:6] + [seven, eight]                 # index 0 = 1 seed
            counts["playoffs"][seeds] += 1

            # Bracket: 1v8, 4v5, 3v6, 2v7; higher seed has home court.
            r1 = [sim.series(seeds[a], seeds[b]) for a, b in ((0, 7), (3, 4), (2, 5), (1, 6))]
            counts["second_round"][r1] += 1
            seed_of = {t: i for i, t in enumerate(seeds)}
            def best_of(a, b):
                hi, lo = (a, b) if seed_of[a] < seed_of[b] else (b, a)
                return sim.series(hi, lo)
            r2 = [best_of(r1[0], r1[1]), best_of(r1[2], r1[3])]
            counts["conf_finals"][r2] += 1
            champ = best_of(*r2)
            counts["finals"][champ] += 1
            champs.append(champ)

        east, west = champs   # better regular-season record gets home court
        hi, lo = (east, west) if order_key[east] > order_key[west] else (west, east)
        counts["title"][sim.series(hi, lo)] += 1

    proj_wins = sim_wins.mean(axis=0)
    return pd.DataFrame({
        "team_id": team_ids,
        "conference": conference,
        "wins": np.asarray(wins, dtype=int),
        "losses": np.asarray(losses, dtype=int),
        "proj_wins": proj_wins.round(1),
        "proj_losses": (games_played - proj_wins).round(1),
        **{f"p_{k}": (v / n_sims).round(4) for k, v in counts.items()},
    })


# ---- Glue: load data, get model probabilities, store results ----------------
def _rest_days(schedule, today):
    """Days of rest before each remaining game, from the schedule itself."""
    games = []
    for side in ("home", "away"):
        part = schedule[["game_id", "game_date", f"{side}_team_id"]].rename(
            columns={f"{side}_team_id": "team_id"})
        part["side"] = side
        games.append(part)
    tg = pd.concat(games).sort_values(["team_id", "game_date", "game_id"])
    tg["rest"] = (tg.groupby("team_id")["game_date"].diff().dt.days
                  .clip(upper=MAX_REST).fillna(MAX_REST))
    return tg.pivot_table(index="game_id", columns="side", values="rest")


def fill_unscheduled_games(remaining, played, conference, rng):
    """Add placeholder games for any team scheduled for fewer than 82.

    The NBA Cup leaves each team's last two games unscheduled until the group
    stage ends in early December, so the schedule only lists 80 games per team
    until then. Without placeholders, every projected record would add up to 80.
    Each placeholder is against a random opponent from the same conference
    (as those games are), at a random team's arena.
    """
    scheduled = played + np.bincount(np.asarray(remaining, dtype=int).ravel(),
                                     minlength=len(played)) if remaining else played.copy()
    extra = []
    for conf in sorted(set(conference)):
        slots = [i for i in range(len(played)) if conference[i] == conf
                 for _ in range(max(0, SEASON_GAMES - int(scheduled[i])))]
        rng.shuffle(slots)
        for a, b in zip(slots[::2], slots[1::2]):
            if a != b:
                extra.append((a, b) if rng.random() < 0.5 else (b, a))
    return extra


def run_simulation(n_sims=N_SIMS, seed=None):
    season = current_season()
    with get_conn() as conn:
        schedule = read_df(conn, "SELECT * FROM schedule WHERE season = :s", s=season)
        history = read_df(conn, "SELECT * FROM historical_games")
    if schedule.empty:
        raise SystemExit("No schedule saved yet. Run: python run_pipeline.py schedule")

    bundle = joblib.load(MODEL_PATH)
    model, features = bundle["model"], bundle["features"]
    schedule["game_date"] = pd.to_datetime(schedule["game_date"])
    today = pd.Timestamp(datetime.now(timezone.utc).date())

    # Teams, indexed 0..29
    teams = (pd.concat([
        schedule[["home_team_id", "home_tricode", "home_team"]].set_axis(["team_id", "tricode", "name"], axis=1),
        schedule[["away_team_id", "away_tricode", "away_team"]].set_axis(["team_id", "tricode", "name"], axis=1)])
        .drop_duplicates("team_id").sort_values("tricode").reset_index(drop=True))
    idx = {tid: i for i, tid in enumerate(teams["team_id"])}
    conference = [CONFERENCE.get(t, "East") for t in teams["tricode"]]

    # Current standings from finished schedule games.
    done = schedule[schedule["status"] == 3]
    home_won = done["home_score"] > done["away_score"]
    wins = np.zeros(len(teams), dtype=int)
    losses = np.zeros(len(teams), dtype=int)
    for h, a, hw in zip(done["home_team_id"], done["away_team_id"], home_won):
        winner, loser = (h, a) if hw else (a, h)
        wins[idx[winner]] += 1
        losses[idx[loser]] += 1

    # Each team's current state, the same inputs the daily predictions use.
    history["game_date"] = pd.to_datetime(history["game_date"])
    _, ratings, last_season = compute_elo(history)
    state = latest_team_state(add_advanced_stats(load_team_games()), today, season)
    league_avg = pd.DataFrame(state.values()).mean().to_dict()

    def team_cols(tid, rest):
        st = dict(state.get(tid, league_avg))
        st["rest"], st["b2b"] = rest, int(rest == 1)
        return st

    def predict(pairs):
        """Home win probability for (home_id, away_id, home_rest, away_rest) tuples."""
        rows = []
        for h, a, hr, ar in pairs:
            row = {"home_elo": pregame_elo(ratings, last_season, h, season),
                   "away_elo": pregame_elo(ratings, last_season, a, season)}
            for side, tid, rest in (("home", h, hr), ("away", a, ar)):
                row.update({f"{side}_{c}": v for c, v in team_cols(tid, rest).items() if c in TEAM_COLS})
            rows.append(row)
        df = add_matchup_features(pd.DataFrame(rows))
        return model.predict_proba(df[features])[:, 1]

    # Remaining games, with real rest days from the schedule.
    left = schedule[schedule["status"] != 3].copy()
    rest = _rest_days(schedule, today)
    left = left.join(rest, on="game_id")
    p_left = predict(zip(left["home_team_id"], left["away_team_id"],
                         left["home"].fillna(2), left["away"].fillna(2)))
    remaining = [(idx[h], idx[a]) for h, a in zip(left["home_team_id"], left["away_team_id"])]

    # Every possible matchup with normal rest (2 days), for the playoffs and
    # for any games the NBA hasn't scheduled yet.
    ids = list(teams["team_id"])
    pairs = [(h, a, 2, 2) for h in ids for a in ids if h != a]
    home_prob = np.full((len(ids), len(ids)), 0.5)
    for (h, a, _, _), p in zip(pairs, predict(pairs)):
        home_prob[idx[h], idx[a]] = p

    placeholders = fill_unscheduled_games(remaining, wins + losses, conference,
                                          np.random.default_rng(0))
    if placeholders:
        print(f"[simulate] added {len(placeholders)} not-yet-scheduled games "
              f"so every team plays {SEASON_GAMES}")
        remaining += placeholders
        p_left = np.concatenate([p_left, [home_prob[h, a] for h, a in placeholders]])

    total = len(schedule)
    result = simulate_season(ids, conference, wins, losses, remaining, p_left, home_prob,
                             games_left_frac=len(remaining) / (len(remaining) + len(done)) if total else 0,
                             n_sims=n_sims, seed=seed)
    result = result.merge(teams, on="team_id")
    result["sims"] = n_sims
    result["games_left"] = len(remaining)
    result["simulated_at"] = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        upsert(conn, "projections", records(result), keys=["team_id"])

    print(f"[simulate] {n_sims:,} simulations of {len(remaining)} remaining games")
    top = result.sort_values("p_title", ascending=False).head(5)
    for r in top.itertuples():
        print(f"  {r.tricode}: {r.proj_wins:.1f}-{r.proj_losses:.1f}, "
              f"playoffs {r.p_playoffs:.0%}, title {r.p_title:.1%}")
    return result
