"""Engine-independent types, so analysis logic can be tested without Stockfish."""

from dataclasses import dataclass
from typing import Literal, Protocol

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


Classification = Literal["ok", "inaccuracy", "mistake", "blunder"]
Phase = Literal["opening", "middlegame", "endgame"]


@dataclass(frozen=True)
class MoveAnalysis:
    """Engine verdict on one move actually played in a game."""

    ply: int  # 1-based half-move index
    san: str
    uci: str
    fen_before: str
    eval_before: PositionEval  # holds the engine's best move for the position
    eval_after: PositionEval
    best_move_san: str | None
    cp_loss: int  # from the mover's point of view, never negative
    classification: Classification
    phase: Phase
    clock_seconds: float | None  # mover's remaining time after the move, from %clk
