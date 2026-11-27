"""Platform-independent representation of an imported game."""

from dataclasses import dataclass
from typing import Literal

Platform = Literal["chesscom", "lichess", "pgn"]
Color = Literal["white", "black"]


@dataclass(frozen=True)
class ImportedGame:
    platform: Platform
    external_id: str  # unique within the platform
    username: str  # the player whose games these are
    user_color: Color
    white: str
    black: str
    result: str  # PGN result: "1-0", "0-1", "1/2-1/2" or "*"
    time_control: str | None
    played_at: str | None  # ISO 8601, UTC when the source says so
    url: str | None
    pgn: str
