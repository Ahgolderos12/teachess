"""Engine-independent types, so analysis logic can be tested without Stockfish."""

from dataclasses import dataclass
from typing import Protocol

import chess


@dataclass(frozen=True)
class PositionEval:
    """Engine verdict for one position. Scores are from White's point of view."""

    cp: int | None  # centipawns; None when the position is a forced mate
    mate: int | None  # moves to mate (positive: White mates); None otherwise
    best_move: str | None  # UCI; None when the game is over
    pv: tuple[str, ...]  # principal variation in UCI
    depth: int


class Engine(Protocol):
    def analyse(self, board: chess.Board, depth: int) -> PositionEval: ...
