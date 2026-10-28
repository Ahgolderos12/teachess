"""Test doubles shared by several test modules."""

import io

import chess
import chess.pgn

from teachess.engine.models import PositionEval

SCHOLAR_PGN = "1. e4 { [%clk 0:10:00] } e5 { [%clk 0:09:58] } 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0"


def ev(cp: int | None = None, best: str | None = None, mate: int | None = None) -> PositionEval:
    return PositionEval(cp=cp, mate=mate, best_move=best, pv=(best,) if best else (), depth=10)


# Scripted evaluations indexed by the number of plies played so far.
SCRIPT = [
    ev(30, "e2e4"),
    ev(30, "e7e5"),
    ev(30, "g1f3"),
    ev(-30, "b8c6"),  # after 2. Qh5: -60 for White, an inaccuracy
    ev(-30, "f1c4"),
    ev(-30, "g7g6"),
    ev(mate=1, best="h5f7"),  # after 3... Nf6??: mate in one for White
    ev(100_000),  # checkmate on the board
]


class ScriptedEngine:
    def __init__(self) -> None:
        self.calls = 0

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        self.calls += 1
        return SCRIPT[board.ply()]


def read(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    return game
