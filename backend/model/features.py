"""Build pre-game features for every historical game.

Golden rule: every feature for a game uses ONLY information available before
tip-off. Rolling stats are shifted by one game and Elo ratings are recorded
before each game updates them, so the model never peeks at the result.
"""
import pandas as pd

from db import get_conn, read_df

# ---- Settings ---------------------------------------------------------------
ROLL_WINDOW = 10        # "recent form" = a team's last 10 games
MIN_GAMES = 3           # need at least this many past games for a rolling value
MAX_REST = 7            # cap rest days (long breaks all count the same)

ELO_START = 1500        # every team starts here
ELO_K = 20              # how fast ratings react to results
ELO_HOME_ADV = 100      # Elo points of home-court advantage
ELO_CARRYOVER = 0.75    # keep 75% of last season's rating; regress 25% to the mean

# Per-game stats that get averaged over each team's recent games.
ROLLING_STATS = [
    "off_rtg",    # points scored per 100 possessions
    "def_rtg",    # points allowed per 100 possessions
    "net_rtg",    # off_rtg - def_rtg (best single measure of team quality)
    "pace",       # possessions per game
    "efg",        # effective FG%: rewards 3-pointers
    "tov_pct",    # turnovers per possession
    "oreb_pct",   # share of own missed shots rebounded
    "ft_rate",    # free throw attempts per FG attempt
    "won",        # recent win rate
]

# The columns the model trains on (home-minus-away differences + context).
FEATURE_COLUMNS = (
    ["elo_diff", "elo_prob"]
    + [f"diff_{s}" for s in ROLLING_STATS]
    + ["diff_season_win_pct", "home_rest", "away_rest", "home_b2b", "away_b2b"]
)


# ---- Team-level stats -------------------------------------------------------
def load_team_games():
    """One row per team per game, with the opponent's stats alongside."""
    with get_conn() as conn:
        tg = read_df(conn, "SELECT * FROM team_game_stats")
    tg["game_date"] = pd.to_datetime(tg["game_date"])

    opp = tg[["game_id", "team_id", "fga", "oreb", "dreb", "tov", "fta"]].rename(
        columns={"team_id": "o_team_id", "fga": "o_fga", "oreb": "o_oreb",
                 "dreb": "o_dreb", "tov": "o_tov", "fta": "o_fta"})
    tg = tg.merge(opp, left_on=["game_id", "opp_team_id"],
                  right_on=["game_id", "o_team_id"])
    return tg


def add_advanced_stats(tg):
    """Possession-based stats (the "Four Factors") for each team-game."""
    own_poss = tg["fga"] - tg["oreb"] + tg["tov"] + 0.44 * tg["fta"]
    opp_poss = tg["o_fga"] - tg["o_oreb"] + tg["o_tov"] + 0.44 * tg["o_fta"]
    tg["pace"] = (own_poss + opp_poss) / 2

    tg["off_rtg"] = 100 * tg["pts"] / tg["pace"]
    tg["def_rtg"] = 100 * tg["opp_pts"] / tg["pace"]
    tg["net_rtg"] = tg["off_rtg"] - tg["def_rtg"]
    tg["efg"] = (tg["fgm"] + 0.5 * tg["fg3m"]) / tg["fga"]
    tg["tov_pct"] = tg["tov"] / tg["pace"]
    tg["oreb_pct"] = tg["oreb"] / (tg["oreb"] + tg["o_dreb"])
    tg["ft_rate"] = tg["fta"] / tg["fga"]
    return tg


def add_pregame_team_features(tg):
    """Rolling form, season record, and rest — all as of BEFORE each game."""
    tg = tg.sort_values(["team_id", "game_date", "game_id"]).reset_index(drop=True)
    by_team = tg.groupby("team_id")

    # shift(1) drops the current game, so each value only uses earlier games.
    for s in ROLLING_STATS:
        tg[f"r_{s}"] = by_team[s].transform(
            lambda x: x.shift(1).rolling(ROLL_WINDOW, min_periods=MIN_GAMES).mean())

    by_season = tg.groupby(["team_id", "season"])
    tg["season_win_pct"] = by_season["won"].transform(
        lambda x: x.shift(1).expanding().mean()).fillna(0.5)

    tg["rest"] = by_team["game_date"].diff().dt.days.clip(upper=MAX_REST).fillna(MAX_REST)
    tg["b2b"] = (tg["rest"] == 1).astype(int)
    return tg


# ---- Elo ratings ------------------------------------------------------------
def elo_win_prob(home_elo, away_elo):
    """Chance the home team wins, given both ratings and home-court advantage."""
    return 1 / (1 + 10 ** ((away_elo - (home_elo + ELO_HOME_ADV)) / 400))


def compute_elo(games):
    """Walk through games in date order, recording each team's PRE-game Elo.

    Returns the games with home_elo/away_elo columns, plus each team's latest
    rating and the season it was last updated (used for today's predictions).
    """
    games = games.sort_values(["game_date", "game_id"]).reset_index(drop=True)
    ratings, last_season = {}, {}
    home_pre, away_pre = [], []

    for g in games.itertuples():
        for tid in (g.home_team_id, g.away_team_id):
            if tid not in ratings:
                ratings[tid] = ELO_START
            elif last_season[tid] != g.season:   # new season: regress to the mean
                ratings[tid] = ELO_CARRYOVER * ratings[tid] + (1 - ELO_CARRYOVER) * ELO_START
            last_season[tid] = g.season

        h, a = ratings[g.home_team_id], ratings[g.away_team_id]
        home_pre.append(h)
        away_pre.append(a)

        expected = elo_win_prob(h, a)
        # Bigger wins move ratings more, but less so when a strong team beats a weak one.
        margin = abs(g.home_pts - g.away_pts)
        winner_edge = (h + ELO_HOME_ADV - a) if g.home_win else (a - h - ELO_HOME_ADV)
        mov_mult = ((margin + 3) ** 0.8) / (7.5 + 0.006 * winner_edge)

        change = ELO_K * mov_mult * (g.home_win - expected)
        ratings[g.home_team_id] += change
        ratings[g.away_team_id] -= change

    games["home_elo"] = home_pre
    games["away_elo"] = away_pre
    return games, ratings, last_season


# ---- Turning two teams' numbers into model features ------------------------
TEAM_COLS = [f"r_{s}" for s in ROLLING_STATS] + ["season_win_pct", "rest", "b2b"]


def add_matchup_features(df):
    """Compute FEATURE_COLUMNS from home_*/away_* team columns and Elo ratings.

    Used for BOTH training and live predictions, so the model always sees
    features calculated exactly the same way.
    """
    df["elo_diff"] = df["home_elo"] - df["away_elo"]
    df["elo_prob"] = elo_win_prob(df["home_elo"], df["away_elo"])
    for s in ROLLING_STATS:
        df[f"diff_{s}"] = df[f"home_r_{s}"] - df[f"away_r_{s}"]
    df["diff_season_win_pct"] = df["home_season_win_pct"] - df["away_season_win_pct"]
    return df


# ---- Training data: every historical game -----------------------------------
def build_game_features():
    """One row per historical game: model features + the home_win label."""
    with get_conn() as conn:
        games = read_df(conn, "SELECT * FROM historical_games")
    games["game_date"] = pd.to_datetime(games["game_date"])
    games, _, _ = compute_elo(games)

    team = add_pregame_team_features(add_advanced_stats(load_team_games()))
    for side in ("home", "away"):
        side_feats = team[["game_id", "team_id"] + TEAM_COLS].rename(
            columns={"team_id": f"{side}_team_id",
                     **{c: f"{side}_{c}" for c in TEAM_COLS}})
        games = games.merge(side_feats, on=["game_id", f"{side}_team_id"], how="left")

    games = add_matchup_features(games)
    # Drop games where a team didn't have enough history yet (start of the data).
    games = games.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    return games


# ---- Live data: each team's numbers going into an upcoming game -------------
def pregame_elo(ratings, last_season, team_id, season):
    """A team's Elo heading into a game, applying the new-season regression if needed."""
    if team_id not in ratings:
        return ELO_START
    if last_season[team_id] != season:
        return ELO_CARRYOVER * ratings[team_id] + (1 - ELO_CARRYOVER) * ELO_START
    return ratings[team_id]


def latest_team_state(team_games, as_of, season):
    """Each team's pre-game numbers for a game on `as_of`, using only earlier games.

    Mirrors add_pregame_team_features: the mean of the last ROLL_WINDOW games,
    season-to-date win %, and days of rest.
    """
    past = team_games[team_games["game_date"] < as_of]
    past = past.sort_values(["team_id", "game_date", "game_id"])
    state = {}
    for team_id, g in past.groupby("team_id"):
        if len(g) < MIN_GAMES:
            continue
        recent = g.tail(ROLL_WINDOW)
        this_season = g[g["season"] == season]
        rest = min((as_of - g["game_date"].max()).days, MAX_REST)
        state[team_id] = {
            **{f"r_{s}": recent[s].mean() for s in ROLLING_STATS},
            "season_win_pct": this_season["won"].mean() if len(this_season) else 0.5,
            "rest": rest,
            "b2b": int(rest == 1),
        }
    return state


def summarize(games):
    """Quick sanity check printed after building features."""
    print(f"[features] {len(games)} games with complete features")
    print(f"[features] home teams won {games['home_win'].mean():.1%} of games")
    print("[features] accuracy of simple rules, by season:")
    print(f"  {'season':<9}{'games':>6}{'pick home':>11}{'pick Elo fav':>14}")
    for season, s in games.groupby("season"):
        elo_acc = ((s["elo_prob"] > 0.5).astype(int) == s["home_win"]).mean()
        print(f"  {season:<9}{len(s):>6}{s['home_win'].mean():>11.1%}{elo_acc:>14.1%}")
