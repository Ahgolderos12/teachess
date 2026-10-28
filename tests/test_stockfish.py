import chess
import pytest

from teachess.config import load_settings
from teachess.engine.stockfish import (
    CHECKMATE_CP,
    StockfishEngine,
    StockfishNotConfiguredError,
)

STOCKFISH = load_settings().stockfish_path
needs_stockfish = pytest.mark.skipif(
    STOCKFISH is None or not STOCKFISH.is_file(), reason="Stockfish not configured"
)


def test_missing_binary_raises() -> None:
    with pytest.raises(StockfishNotConfiguredError):
        StockfishEngine(None)


@needs_stockfish
def test_finds_mate_in_one() -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    with StockfishEngine(STOCKFISH) as engine:
        result = engine.analyse(board, depth=8)
    assert result.best_move == "a1a8"
    assert result.mate == 1


@needs_stockfish
def test_cache_returns_same_object() -> None:
    board = chess.Board()
    with StockfishEngine(STOCKFISH) as engine:
        first = engine.analyse(board, depth=6)
        assert engine.analyse(board, depth=6) is first


@needs_stockfish
def test_checkmated_position_needs_no_search() -> None:
    board = chess.Board("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1")
    with StockfishEngine(STOCKFISH) as engine:
        result = engine.analyse(board, depth=6)
    assert result.best_move is None
    assert result.cp == CHECKMATE_CP
