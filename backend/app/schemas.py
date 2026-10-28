"""Shapes of the data the API returns. FastAPI uses these to validate
responses and to build the interactive docs page at /docs."""
from typing import Literal, Optional

from pydantic import BaseModel


class Team(BaseModel):
    team_id: int
    name: str
    tricode: str
    score: Optional[int] = None
    logo_url: str


class Prediction(BaseModel):
    winner_team_id: int
    winner_tricode: str
    winner_prob: float          # chance the predicted winner wins (0.5 to 1)
    home_win_prob: float
    away_win_prob: float
    correct: Optional[bool] = None   # filled in once the game is final


class Game(BaseModel):
    game_id: str
    game_date: str
    start_time_utc: Optional[str] = None
    status: Literal["scheduled", "live", "final"]
    status_text: str
    home: Team
    away: Team
    prediction: Optional[Prediction] = None


class GamesResponse(BaseModel):
    date: Optional[str]
    updated_at: Optional[str]
    games: list[Game]


class Headline(BaseModel):
    title: str
    link: str
    summary: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[str] = None


class Record(BaseModel):
    games: int
    correct: int
    accuracy: Optional[float] = None


class ModelInfo(BaseModel):
    model: Optional[str] = None
    test_season: Optional[str] = None
    test_games: Optional[int] = None
    test_accuracy: Optional[float] = None
    baseline_home_accuracy: Optional[float] = None
    baseline_elo_accuracy: Optional[float] = None
    trained_at: Optional[str] = None
    season_record: Record      # live predictions this season
