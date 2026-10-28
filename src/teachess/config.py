"""Settings loaded from environment variables / .env (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    stockfish_path: Path | None
    chesscom_user: str | None
    lichess_user: str | None


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_settings() -> Settings:
    """Read settings from the environment, loading `.env` first if present."""
    load_dotenv()
    stockfish = _optional("STOCKFISH_PATH")
    return Settings(
        stockfish_path=Path(stockfish) if stockfish else None,
        chesscom_user=_optional("CHESSCOM_USER"),
        lichess_user=_optional("LICHESS_USER"),
    )
