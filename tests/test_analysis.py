import chess

from teachess.db import repository as repo
from teachess.engine.analysis import (
    EVAL_CLAMP_CP,
    PersistentCacheEngine,
    analyse_game,
    classify,
    cp_loss,
    game_phase,
    white_cp,
)
from tests.fakes import SCHOLAR_PGN, SCRIPT, ScriptedEngine, ev, read


def test_analyse_game_scores_and_classifies_each_move() -> None:
    engine = ScriptedEngine()
    moves = analyse_game(read(SCHOLAR_PGN), engine, depth=10)

    assert engine.calls == len(SCRIPT)  # each position evaluated once
    assert [m.san for m in moves] == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    assert [m.cp_loss for m in moves] == [0, 0, 60, 0, 0, EVAL_CLAMP_CP + 30, 0]
    assert [m.classification for m in moves] == [
        "ok",
        "ok",
        "inaccuracy",
        "ok",
        "ok",
        "blunder",
        "ok",
    ]
    blunder = moves[5]
    assert blunder.best_move_san == "g6"
    assert blunder.uci == "g8f6"
    assert blunder.fen_before == SCRIPT_FEN_BEFORE_NF6
    assert {m.phase for m in moves} == {"opening"}
    assert [m.clock_seconds for m in moves[:3]] == [600.0, 598.0, None]


SCRIPT_FEN_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def test_white_cp_clamps_and_converts_mates() -> None:
    assert white_cp(ev(5000)) == EVAL_CLAMP_CP
    assert white_cp(ev(-5000)) == -EVAL_CLAMP_CP
    assert white_cp(ev(mate=3)) == EVAL_CLAMP_CP
    assert white_cp(ev(mate=-2)) == -EVAL_CLAMP_CP
    assert white_cp(ev(42)) == 42


def test_cp_loss_is_from_movers_point_of_view() -> None:
    assert cp_loss(ev(100), ev(-50), chess.WHITE) == 150
    assert cp_loss(ev(100), ev(-50), chess.BLACK) == 0
    assert cp_loss(ev(-100), ev(200), chess.BLACK) == 300


def test_classify_thresholds() -> None:
    assert [classify(x) for x in (49, 50, 99, 100, 299, 300)] == [
        "ok",
        "inaccuracy",
        "inaccuracy",
        "mistake",
        "mistake",
        "blunder",
    ]


def test_game_phase() -> None:
    assert game_phase(chess.Board()) == "opening"
    middlegame = chess.Board()
    middlegame.fullmove_number = 20
    assert game_phase(middlegame) == "middlegame"
    # Rook and bishop each (8 points per side): endgame regardless of move number.
    assert game_phase(chess.Board("4k3/3b1r2/8/8/8/8/3B1R2/4K3 w - - 0 5")) == "endgame"


def test_persistent_cache_survives_new_engine_instances() -> None:
    conn = repo.connect(":memory:")
    board = chess.Board()

    first = ScriptedEngine()
    assert PersistentCacheEngine(first, conn).analyse(board, 10) == SCRIPT[0]
    second = ScriptedEngine()
    assert PersistentCacheEngine(second, conn).analyse(board, 10) == SCRIPT[0]
    assert (first.calls, second.calls) == (1, 0)
    conn.close()
