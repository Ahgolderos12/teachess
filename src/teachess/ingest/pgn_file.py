"""PGN parsing/validation shared by all sources, plus import from a local file."""

import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import chess.pgn

from teachess.ingest.models import Color, ImportedGame


@dataclass
class FetchResult:
    games: list[ImportedGame] = field(default_factory=list)
    skipped: int = 0  # unparseable, illegal, empty, variant or not involving the user


def parse_games(text: str) -> Iterator[chess.pgn.Game | None]:
    """Yield each game in a PGN text; None for games that are not usable standard chess."""
    stream = io.StringIO(text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            return
        yield game if _is_usable(game) else None


def _is_usable(game: chess.pgn.Game) -> bool:
    variant = game.headers.get("Variant", "Standard").lower()
    return (
        not game.errors
        and variant in ("standard", "chess", "from position")
        and game.next() is not None
    )


def user_color(game: chess.pgn.Game, username: str) -> Color | None:
    name = username.casefold()
    if game.headers.get("White", "").casefold() == name:
        return "white"
    if game.headers.get("Black", "").casefold() == name:
        return "black"
    return None


def pgn_date(game: chess.pgn.Game) -> str | None:
    """PGN Date header as ISO date, or None if unknown/partial."""
    date = game.headers.get("UTCDate") or game.headers.get("Date", "")
    if len(date) != 10 or "?" in date:
        return None
    return date.replace(".", "-")


def load_pgn_file(path: Path, username: str, color: Color | None = None) -> FetchResult:
    """Read OTB/other-platform games. `color` forces the user's side when names don't match."""
    result = FetchResult()
    for game in parse_games(path.read_text(encoding="utf-8-sig")):
        side = color or (user_color(game, username) if game else None)
        if game is None or side is None:
            result.skipped += 1
            continue
        pgn = str(game)
        result.games.append(
            ImportedGame(
                platform="pgn",
                external_id=hashlib.sha256(pgn.encode()).hexdigest()[:16],
                username=username,
                user_color=side,
                white=game.headers.get("White", "?"),
                black=game.headers.get("Black", "?"),
                result=game.headers.get("Result", "*"),
                time_control=game.headers.get("TimeControl"),
                played_at=pgn_date(game),
                url=None,
                pgn=pgn,
            )
        )
    return result
