"""Train, compare, and save the game-prediction model.

Time-based evaluation (never random splits — that would let the model learn
from the future):
  * warm-up season: dropped, because Elo ratings all start at 1500 and are noisy
  * training seasons: used to fit models
  * validation season: the last training season, used to pick settings
  * test season: the most recent completed season, used ONCE for the final score
The chosen model is then refit on every completed season and saved.
"""
import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from model.features import FEATURE_COLUMNS, build_game_features
from pipeline.history import current_season

MODEL_DIR = Path(__file__).resolve().parent
MODEL_PATH = MODEL_DIR / "model.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"
WARMUP_SEASONS = 1


# ---- Candidate models and the settings to try for each ----------------------
def logistic(C):
    return make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=1000))


def boosted(max_depth, learning_rate, max_iter):
    # Same family as XGBoost/LightGBM, built into scikit-learn (no extra installs).
    return HistGradientBoostingClassifier(
        max_depth=max_depth, learning_rate=learning_rate, max_iter=max_iter,
        l2_regularization=1.0, min_samples_leaf=40, random_state=42)


CANDIDATES = {
    "Logistic regression": (logistic, {"C": [0.01, 0.1, 1.0]}),
    "Gradient boosting": (boosted, {"max_depth": [2, 3],
                                    "learning_rate": [0.03, 0.1],
                                    "max_iter": [100, 300]}),
}


# ---- Helpers ----------------------------------------------------------------
def score(y_true, prob):
    prob = np.clip(prob, 1e-6, 1 - 1e-6)
    return {
        "accuracy": accuracy_score(y_true, prob > 0.5),
        "log_loss": log_loss(y_true, prob, labels=[0, 1]),
        "brier": brier_score_loss(y_true, prob),
    }


def split_seasons(games):
    """Return (train seasons, test season, every completed season)."""
    completed = sorted(s for s in games["season"].unique() if s != current_season())
    usable = completed[WARMUP_SEASONS:]
    if len(usable) < 3:
        raise SystemExit(f"Need at least {WARMUP_SEASONS + 3} completed seasons, have {completed}")
    return usable[:-1], usable[-1], usable


def tune(build, grid, X_fit, y_fit, X_val, y_val):
    """Try every setting combination; keep the one with the best validation log loss."""
    best = None
    for values in product(*grid.values()):
        params = dict(zip(grid.keys(), values))
        model = build(**params).fit(X_fit, y_fit)
        loss = log_loss(y_val, model.predict_proba(X_val)[:, 1])
        if best is None or loss < best[1]:
            best = (params, loss)
    return best


# ---- Main training routine --------------------------------------------------
def train():
    games = build_game_features()
    train_seasons, test_season, all_seasons = split_seasons(games)
    val_season = train_seasons[-1]

    def xy(seasons):
        part = games[games["season"].isin(seasons)]
        return part[FEATURE_COLUMNS], part["home_win"]

    X_fit, y_fit = xy(train_seasons[:-1])
    X_val, y_val = xy([val_season])
    X_train, y_train = xy(train_seasons)
    X_test, y_test = xy([test_season])

    print(f"[train] fit on {train_seasons[:-1]}, tune on {val_season}, "
          f"test on {test_season} ({len(X_test)} games)")

    results = {
        "Always pick home team": score(y_test, np.full(len(y_test), y_train.mean())),
        "Elo favorite": score(y_test, X_test["elo_prob"].to_numpy()),
    }
    chosen = {}
    for name, (build, grid) in CANDIDATES.items():
        params, val_loss = tune(build, grid, X_fit, y_fit, X_val, y_val)
        model = build(**params).fit(X_train, y_train)
        results[name] = score(y_test, model.predict_proba(X_test)[:, 1])
        chosen[name] = {"params": params, "val_log_loss": val_loss}

    print(f"\n  {'model':<24}{'accuracy':>9}{'log loss':>10}{'brier':>8}")
    for name, m in results.items():
        print(f"  {name:<24}{m['accuracy']:>9.1%}{m['log_loss']:>10.4f}{m['brier']:>8.4f}")

    # Pick the winner using VALIDATION results, so the test score stays honest.
    best_name = min(chosen, key=lambda n: chosen[n]["val_log_loss"])
    build = CANDIDATES[best_name][0]
    print(f"\n[train] chosen: {best_name} {chosen[best_name]['params']}")

    if best_name == "Logistic regression":
        refit = build(**chosen[best_name]["params"]).fit(X_train, y_train)
        coefs = refit[-1].coef_[0]
        print("[train] feature weights (scaled; + favors home team):")
        for feat, w in sorted(zip(FEATURE_COLUMNS, coefs), key=lambda t: -abs(t[1])):
            print(f"  {feat:<22}{w:+.3f}")

    # Final model: same settings, trained on every completed season.
    X_all, y_all = xy(all_seasons)
    final = build(**chosen[best_name]["params"]).fit(X_all, y_all)

    metrics = {
        "model": best_name,
        "params": chosen[best_name]["params"],
        "test_season": test_season,
        "test_games": int(len(y_test)),
        "test": results[best_name],
        "baselines": {k: results[k] for k in ("Always pick home team", "Elo favorite")},
        "trained_on": all_seasons,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump({"model": final, "features": FEATURE_COLUMNS, "metrics": metrics}, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    print(f"[train] saved model to {MODEL_PATH}")
    return metrics
