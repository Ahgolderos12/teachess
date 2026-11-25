import json
import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from teachess.coach.tools import TOOL_DEFINITIONS, CoachToolbox
from teachess.db import repository as repo
from teachess.engine.analysis import analyse_game
from teachess.ingest.models import ImportedGame
from teachess.report.builder import load_game_report
from tests.fakes import SCHOLAR_PGN, ScriptedEngine, read

GAME = ImportedGame(
    platform="chesscom",
    external_id="g1",
    username="alice",
    user_color="black",
    white="Bob",
    black="alice",
    result="1-0",
    time_control="600",
    played_at="2026-10-01T10:00:00+00:00",
    url=None,
    pgn='[ECOUrl "https://www.chess.com/openings/Kings-Pawn-Opening"]\n\n' + SCHOLAR_PGN,
)
FEN_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
MATED_FEN = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"


@pytest.fixture
def toolbox() -> Iterator[CoachToolbox]:
    conn: sqlite3.Connection = repo.connect(":memory:")
    repo.insert_game(conn, GAME)
    stored = repo.list_games(conn)[0]
    moves = analyse_game(read(SCHOLAR_PGN), ScriptedEngine(), depth=10)
    repo.save_move_analysis(conn, stored.id, moves, depth=10)
    report = load_game_report(conn, stored.id)
    assert report is not None
    yield CoachToolbox(report, repo.get_move_analysis(conn, stored.id), ScriptedEngine(), 10)
    conn.close()


def call(toolbox: CoachToolbox, name: str, **arguments: Any) -> dict[str, Any]:
    result = toolbox.run(name, arguments)
    assert not result.is_error, result.content
    data: dict[str, Any] = json.loads(result.content)
    return data


def error(toolbox: CoachToolbox, name: str, arguments: object) -> str:
    result = toolbox.run(name, arguments)
    assert result.is_error
    message: str = json.loads(result.content)["error"]
    return message


def test_definitions_are_strict_and_match_handlers(toolbox: CoachToolbox) -> None:
    for tool in TOOL_DEFINITIONS:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
        assert "Herramienta desconocida" not in toolbox.run(tool["name"], {}).content


def test_game_summary(toolbox: CoachToolbox) -> None:
    summary = call(toolbox, "get_game_summary")
    assert summary["user_color"] == "black"
    assert summary["opening"] == "Kings Pawn Opening"
    assert summary["user_mistakes"] == {"inaccuracy": 0, "mistake": 0, "blunder": 1}
    assert summary["user_moves"] == 3


def test_critical_moments_filters_by_level(toolbox: CoachToolbox) -> None:
    moments = call(toolbox, "get_critical_moments", min_level="blunder")["moments"]
    assert len(moments) == 1
    nf6 = moments[0]
    assert nf6["move"] == "3...Nf6"
    assert nf6["best_move"] == "g6"
    assert nf6["eval_after"] == "#1"
    assert nf6["classification"] == "blunder"
    assert nf6["played_by"] == "user"
    assert nf6["engine_line"] == "3...g6"
    # The opponent's inaccuracy (2.Qh5) is not one of the user's critical moments.
    assert len(call(toolbox, "get_critical_moments", min_level="inaccuracy")["moments"]) == 1


def test_get_move_covers_both_sides(toolbox: CoachToolbox) -> None:
    qh5 = call(toolbox, "get_move", move_number=2, color="white")
    assert (qh5["move"], qh5["played_by"], qh5["classification"]) == (
        "2.Qh5",
        "opponent",
        "inaccuracy",
    )
    assert "no existe" in error(toolbox, "get_move", {"move_number": 9, "color": "black"})
    assert "4.Qxf7#" in error(toolbox, "get_move", {"move_number": 9, "color": "black"})


def test_evaluate_position(toolbox: CoachToolbox) -> None:
    result = call(toolbox, "evaluate_position", fen=FEN_BEFORE_NF6)
    assert result["eval"] == "-1.00"
    assert result["best_move"] == "g6"
    assert result["side_to_move"] == "black"
    over = call(toolbox, "evaluate_position", fen=MATED_FEN)
    assert over == {"fen": MATED_FEN, "side_to_move": "black", "game_over": True, "result": "1-0"}


def test_evaluate_move_answers_what_if(toolbox: CoachToolbox) -> None:
    bad = call(toolbox, "evaluate_move", fen=FEN_BEFORE_NF6, move="Nf6")
    assert bad["classification"] == "blunder"
    assert bad["eval_after"] == "#1"
    assert bad["best_reply_line"] == "4. Qxf7#"
    best = call(toolbox, "evaluate_move", fen=FEN_BEFORE_NF6, move="g7g6")  # UCI also works
    assert (best["move"], best["is_best"], best["win_loss_pct"]) == ("g6", True, 0.0)


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("evaluate_position", {"fen": "not a fen"}, "FEN no válido"),
        ("evaluate_position", {"fen": "8/8/8/8/8/8/8/8 w - - 0 1"}, "no es legal"),
        ("evaluate_move", {"fen": FEN_BEFORE_NF6, "move": "Qxf7"}, "Jugadas legales:"),
        ("evaluate_move", {"fen": MATED_FEN, "move": "Ke7"}, "ya ha terminado"),
        ("evaluate_move", {"fen": FEN_BEFORE_NF6}, "Falta el campo"),
        ("get_critical_moments", {"min_level": "huge"}, "min_level"),
        ("get_move", {"move_number": 0, "color": "white"}, "entero positivo"),
        ("delete_everything", {}, "desconocida"),
        ("get_game_summary", ["not", "an", "object"], "objeto JSON"),
    ],
)
def test_invalid_input_returns_error_result(
    toolbox: CoachToolbox, name: str, arguments: object, expected: str
) -> None:
    assert expected in error(toolbox, name, arguments)
