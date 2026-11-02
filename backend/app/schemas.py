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


class Market(BaseModel):
    """The betting market's view of a game, saved before tip-off."""
    home_win_prob: float
    away_win_prob: float
    favorite_tricode: str
    favorite_prob: float
    bookmakers: Optional[int] = None
    agrees_with_model: Optional[bool] = None   # same pick as the model?


class Game(BaseModel):
    game_id: str
    game_date: str
    start_time_utc: Optional[str] = None
    status: Literal["scheduled", "live", "final"]
    status_text: str
    home: Team
    away: Team
    prediction: Optional[Prediction] = None
    market: Optional[Market] = None


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


class MarketComparison(BaseModel):
    """Model vs betting market on finished games where both made a call.
    Lower log loss and Brier score mean better probabilities."""
    games: int
    model_accuracy: float
    market_accuracy: float
    model_log_loss: float
    market_log_loss: float
    model_brier: float
    market_brier: float
    disagreements: int          # games where they picked different winners
    model_won_disagreements: int


class ModelInfo(BaseModel):
    model: Optional[str] = None
    test_season: Optional[str] = None
    test_games: Optional[int] = None
    test_accuracy: Optional[float] = None
    baseline_home_accuracy: Optional[float] = None
    baseline_elo_accuracy: Optional[float] = None
    trained_at: Optional[str] = None
    season_record: Record      # live predictions this season
    vs_market: Optional[MarketComparison] = None
