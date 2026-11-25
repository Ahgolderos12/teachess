"""Settings loaded from environment variables / .env (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Settings:
    stockfish_path: Path | None
    chesscom_user: str | None
    lichess_user: str | None
    db_path: Path
    engine_depth: int
    model: str  # Claude model used by the coach
    effort: Effort  # reasoning effort for the coach
    sync_hours: float = 6.0  # `serve` imports and analyses new games every N hours (0: off)


DEFAULT_DB_PATH = Path("data/teachess.sqlite")
DEFAULT_ENGINE_DEPTH = 16
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT: Effort = "medium"
DEFAULT_SYNC_HOURS = 6.0


class SettingsError(ValueError):
    pass


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_settings() -> Settings:
    """Read settings from the environment, loading `.env` first if present."""
    load_dotenv()
    stockfish = _optional("STOCKFISH_PATH")
    db_path = _optional("TEACHESS_DB")
    depth = _optional("TEACHESS_DEPTH")
    return Settings(
        stockfish_path=Path(stockfish) if stockfish else None,
        chesscom_user=_optional("CHESSCOM_USER"),
        lichess_user=_optional("LICHESS_USER"),
        db_path=Path(db_path) if db_path else DEFAULT_DB_PATH,
        engine_depth=int(depth) if depth else DEFAULT_ENGINE_DEPTH,
        model=_optional("TEACHESS_MODEL") or DEFAULT_MODEL,
        effort=_effort(_optional("TEACHESS_EFFORT")),
        sync_hours=_sync_hours(_optional("TEACHESS_SYNC_HOURS")),
    )


def _sync_hours(value: str | None) -> float:
    if value is None:
        return DEFAULT_SYNC_HOURS
    try:
        hours = float(value.replace(",", "."))
    except ValueError:
        hours = -1
    if hours < 0:
        raise SettingsError(
            f"TEACHESS_SYNC_HOURS debe ser un número de horas ≥ 0 (recibido: {value})."
        )
    return hours


def _effort(value: str | None) -> Effort:
    if value is None:
        return DEFAULT_EFFORT
    if value not in EFFORT_LEVELS:
        raise SettingsError(
            f"TEACHESS_EFFORT debe ser uno de: {', '.join(EFFORT_LEVELS)} (recibido: {value})."
        )
    return value
