"""Stockfish UCI wrapper with a (FEN, depth) cache."""

from pathlib import Path
from types import TracebackType
from typing import Self

import chess
import chess.engine

from teachess.engine.models import PositionEval

CHECKMATE_CP = 100_000


class StockfishNotConfiguredError(RuntimeError):
    pass


class StockfishEngine:
    """Serialized access to one Stockfish process. Use as a context manager."""

    def __init__(self, path: Path | None, *, soft_time_limit: float = 10.0, timeout: float = 60.0):
        if path is None or not path.is_file():
            raise StockfishNotConfiguredError(
                "STOCKFISH_PATH no está configurado o no apunta a un binario válido."
            )
        self._path = path
        self._soft_time_limit = soft_time_limit
        self._timeout = timeout
        self._engine: chess.engine.SimpleEngine | None = None
        self._cache: dict[tuple[str, int], PositionEval] = {}

    def __enter__(self) -> Self:
        self._engine = chess.engine.SimpleEngine.popen_uci(str(self._path), timeout=self._timeout)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        if self._engine is None:
            raise RuntimeError("StockfishEngine must be used as a context manager.")
        key = (board.fen(), depth)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if board.is_game_over():
            result = PositionEval(*_terminal_score(board), best_move=None, pv=(), depth=0)
        else:
            limit = chess.engine.Limit(depth=depth, time=self._soft_time_limit)
            info = self._engine.analyse(board, limit)
            score = info["score"].white()
            pv = tuple(m.uci() for m in info.get("pv", ()))
            result = PositionEval(
                cp=score.score(),
                mate=score.mate(),
                best_move=pv[0] if pv else None,
                pv=pv,
                depth=info.get("depth", depth),
            )
        self._cache[key] = result
        return result


def _terminal_score(board: chess.Board) -> tuple[int | None, int | None]:
    outcome = board.outcome()
    if outcome is None or outcome.winner is None:
        return 0, None
    # Checkmate on the board: no "mate in N" remains, so use a fixed winning score.
    return (CHECKMATE_CP if outcome.winner == chess.WHITE else -CHECKMATE_CP), None
