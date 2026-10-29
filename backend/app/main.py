"""FastAPI backend for the NBA dashboard.

Run locally from the backend/ folder:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/docs to try every endpoint.
"""
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.schemas import Game, GamesResponse, Headline, ModelInfo, Prediction, Record, Team
from db import fetch_all, fetch_value, get_conn, init_db

# The API only reads data, so it avoids importing the heavy model and NBA
# libraries. That keeps memory low and cold starts fast on Render's free tier.
METRICS_PATH = Path(__file__).resolve().parent.parent / "model" / "metrics.json"


def current_season(today=None):
    """NBA seasons start in October: Oct 2026 -> '2026-27', Mar 2027 -> '2026-27'."""
    today = today or date.today()
    start = today.year if today.month >= 10 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"

STATUS = {1: "scheduled", 2: "live", 3: "final"}
LOGO_URL = "https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"

@asynccontextmanager
async def lifespan(app):
    init_db()   # make sure tables exist, even on a fresh database
    yield


app = FastAPI(title="NBA Dashboard API", version="1.0", lifespan=lifespan)

# Which websites may call this API from the browser. Local dev servers are
# always allowed; the deployed frontend's URL comes from FRONTEND_ORIGIN.
origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
if os.getenv("FRONTEND_ORIGIN"):
    origins += [o.strip().rstrip("/") for o in os.environ["FRONTEND_ORIGIN"].split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"],
                   allow_headers=["*"])


# ---- Helpers ----------------------------------------------------------------
def winner_id(row):
    """Team id of the winner of a final game, else None."""
    if row["status"] != 3 or row["home_score"] is None or row["away_score"] is None:
        return None
    return row["home_team_id"] if row["home_score"] > row["away_score"] else row["away_team_id"]


def to_game(row):
    def team(side):
        return Team(team_id=row[f"{side}_team_id"], name=row[f"{side}_team"],
                    tricode=row[f"{side}_tricode"],
                    score=row[f"{side}_score"] if row["status"] != 1 else None,
                    logo_url=LOGO_URL.format(team_id=row[f"{side}_team_id"]))

    prediction = None
    if row["home_win_prob"] is not None:
        home_p = row["home_win_prob"]
        won = winner_id(row)
        prediction = Prediction(
            winner_team_id=row["predicted_winner_id"],
            winner_tricode=row["predicted_tricode"],
            winner_prob=round(max(home_p, 1 - home_p), 4),
            home_win_prob=round(home_p, 4),
            away_win_prob=round(1 - home_p, 4),
            correct=None if won is None else won == row["predicted_winner_id"],
        )
    return Game(game_id=row["game_id"], game_date=row["game_date"],
                start_time_utc=row["start_time_utc"],
                status=STATUS.get(row["status"], "scheduled"),
                status_text=row["status_text"] or "",
                home=team("home"), away=team("away"), prediction=prediction)


# ---- Endpoints --------------------------------------------------------------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/games", response_model=GamesResponse)
def games(day: str | None = Query(None, alias="date",
                                  description="YYYY-MM-DD; defaults to the latest game day")):
    """Games for one day, each with its prediction (if one was made)."""
    if day:
        try:
            date.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")
    with get_conn() as conn:
        day = day or fetch_value(conn, "SELECT MAX(game_date) FROM games")
        rows = fetch_all(
            conn,
            """SELECT g.*, p.home_win_prob, p.predicted_winner_id, p.predicted_tricode
               FROM games g LEFT JOIN predictions p ON p.game_id = g.game_id
               WHERE g.game_date = :day
               ORDER BY g.start_time_utc, g.game_id""", day=day)
    return GamesResponse(
        date=day,
        updated_at=max((r["updated_at"] for r in rows if r["updated_at"]), default=None),
        games=[to_game(r) for r in rows],
    )


@app.get("/api/headlines", response_model=list[Headline])
def headlines(limit: int = Query(15, ge=1, le=50)):
    """Most recent headlines first."""
    with get_conn() as conn:
        rows = fetch_all(
            conn,
            """SELECT title, link, summary, source, published_at FROM headlines
               ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT :limit""",
            limit=limit)
    return [Headline(**r) for r in rows]


@app.get("/api/model", response_model=ModelInfo)
def model_info():
    """How the model scored in testing, plus its live record this season."""
    metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}

    season_start = f"{current_season()[:4]}-10-01"
    with get_conn() as conn:
        rows = fetch_all(
            conn,
            """SELECT g.*, p.predicted_winner_id FROM predictions p
               JOIN games g ON g.game_id = p.game_id
               WHERE g.status = 3 AND g.game_date >= :start""", start=season_start)
    graded = [(winner_id(r), r["predicted_winner_id"]) for r in rows]
    graded = [(w, p) for w, p in graded if w is not None]
    correct = sum(w == p for w, p in graded)

    baselines = metrics.get("baselines", {})
    return ModelInfo(
        model=metrics.get("model"),
        test_season=metrics.get("test_season"),
        test_games=metrics.get("test_games"),
        test_accuracy=metrics.get("test", {}).get("accuracy"),
        baseline_home_accuracy=baselines.get("Always pick home team", {}).get("accuracy"),
        baseline_elo_accuracy=baselines.get("Elo favorite", {}).get("accuracy"),
        trained_at=metrics.get("trained_at"),
        season_record=Record(games=len(graded), correct=correct,
                             accuracy=correct / len(graded) if graded else None),
    )
