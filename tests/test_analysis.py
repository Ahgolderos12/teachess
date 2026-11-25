import chess
import pytest

from teachess.db import repository as repo
from teachess.engine.analysis import PersistentCacheEngine, analyse_game, game_phase
from teachess.engine.models import CHECKMATE_CP
from teachess.engine.scoring import (
    EVAL_CLAMP_CP,
    classify,
    cp_loss,
    white_cp,
    win_loss,
    win_percent,
)
from tests.fakes import SCHOLAR_PGN, SCRIPT, ScriptedEngine, ev, read


def test_analyse_game_scores_and_classifies_each_move() -> None:
    engine = ScriptedEngine()
    moves = analyse_game(read(SCHOLAR_PGN), engine, depth=10)

    assert engine.calls == len(SCRIPT)  # each position evaluated once
    assert [m.san for m in moves] == ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"]
    assert [m.cp_loss for m in moves] == [0, 0, 130, 0, 0, EVAL_CLAMP_CP + 100, 0]
    assert moves[2].win_loss == pytest.approx(11.9, abs=0.1)
    assert moves[5].win_loss == pytest.approx(59.1, abs=0.1)
    assert [m.win_loss for m in moves[:2]] == [0.0, 0.0]
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


def test_win_percent_follows_lichess_model() -> None:
    assert win_percent(ev(0)) == 50.0
    assert win_percent(ev(100)) == pytest.approx(59.1, abs=0.1)
    assert win_percent(ev(-100)) == pytest.approx(40.9, abs=0.1)
    assert win_percent(ev(5000)) == win_percent(ev(EVAL_CLAMP_CP))  # clamped
    assert win_percent(ev(mate=7)) == 100.0
    assert win_percent(ev(mate=-1)) == 0.0
    assert win_percent(ev(CHECKMATE_CP)) == 100.0
    assert win_percent(ev(-CHECKMATE_CP)) == 0.0


def test_win_loss_is_from_movers_point_of_view() -> None:
    assert win_loss(ev(100), ev(-100), chess.WHITE) == pytest.approx(18.2, abs=0.1)
    assert win_loss(ev(100), ev(-100), chess.BLACK) == 0.0
    assert win_loss(ev(100), ev(-100), chess.BLACK) == win_loss(ev(-100), ev(100), chess.WHITE)


def test_dropping_eval_in_won_position_is_not_a_blunder() -> None:
    # +8 -> +4: 400 cp lost (a blunder by centipawns), but White is still clearly winning.
    loss = win_loss(ev(800), ev(400), chess.WHITE)
    assert cp_loss(ev(800), ev(400), chess.WHITE) == 400
    assert loss == pytest.approx(13.7, abs=0.1)
    assert classify(loss) == "inaccuracy"
    # Already completely winning: giving back material that keeps +10 costs nothing.
    assert classify(win_loss(ev(3000), ev(1200), chess.WHITE)) == "ok"


def test_allowing_mate_is_penalised_by_how_much_was_left_to_lose() -> None:
    # From equal to mated: the whole game is thrown away.
    assert classify(win_loss(ev(0), ev(mate=-3), chess.WHITE)) == "blunder"
    # From clearly worse (-3) to mated: still a real error, but less is lost.
    loss = win_loss(ev(-300), ev(mate=-3), chess.WHITE)
    assert loss == pytest.approx(24.9, abs=0.1)
    assert classify(loss) == "mistake"
    # Missing a mate while staying totally winning is not an error.
    assert classify(win_loss(ev(mate=2), ev(1500), chess.WHITE)) == "ok"


def test_classify_thresholds() -> None:
    assert [classify(x) for x in (9.9, 10, 19.9, 20, 29.9, 30)] == [
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
