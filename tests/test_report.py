import sqlite3
from collections.abc import Iterator
from dataclasses import replace

import pytest
from rich.console import Console

from teachess.db import repository as repo
from teachess.engine.analysis import analyse_game
from teachess.ingest.models import ImportedGame
from teachess.report.builder import best_line_san, load_game_report, load_user_report, move_label
from teachess.report.render import format_eval, render_game_report, render_user_report
from tests.fakes import SCHOLAR_PGN, ScriptedEngine, ev, read

GAME = ImportedGame(
    platform="lichess",
    external_id="g1",
    username="alice",
    user_color="black",
    white="Bob",
    black="alice",
    result="1-0",
    time_control="600+0",
    played_at="2026-10-01T10:00:00+00:00",
    url="https://lichess.org/g1",
    pgn=SCHOLAR_PGN,
)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = repo.connect(":memory:")
    repo.insert_game(connection, GAME)
    repo.insert_game(connection, replace(GAME, external_id="g2", user_color="white"))
    repo.insert_game(connection, replace(GAME, external_id="pending"))
    for stored in repo.list_games(connection):
        if stored.game.external_id != "pending":
            moves = analyse_game(read(stored.game.pgn), ScriptedEngine(), depth=10)
            repo.save_move_analysis(connection, stored.id, moves, depth=10)
    yield connection
    connection.close()


def game_id(conn: sqlite3.Connection, external_id: str) -> int:
    return next(g.id for g in repo.list_games(conn) if g.game.external_id == external_id)


def test_game_report_only_counts_user_moves(conn: sqlite3.Connection) -> None:
    as_black = load_game_report(conn, game_id(conn, "g1"))
    assert as_black is not None
    assert [m.san for m in as_black.mistakes] == ["Nf6"]
    assert as_black.counts["blunder"] == 1
    assert as_black.acpl == pytest.approx(1030 / 3)

    as_white = load_game_report(conn, game_id(conn, "g2"))
    assert as_white is not None
    assert [m.san for m in as_white.mistakes] == ["Qh5"]
    assert as_white.acpl == pytest.approx(60 / 4)


def test_game_report_missing_or_unanalysed(conn: sqlite3.Connection) -> None:
    assert load_game_report(conn, 999) is None
    assert load_game_report(conn, game_id(conn, "pending")) is None


def test_user_report_aggregates(conn: sqlite3.Connection) -> None:
    report = load_user_report(conn, "ALICE")
    assert len(report.games) == 2
    assert report.pending == 1
    assert report.counts == {"blunder": 1, "inaccuracy": 1}
    assert report.by_phase["opening"] == {"blunder": 1, "inaccuracy": 1}
    assert [g.stored.game.external_id for g in report.worst_games()] == ["g1", "g2"]


def test_move_label_and_best_line(conn: sqlite3.Connection) -> None:
    report = load_game_report(conn, game_id(conn, "g1"))
    assert report is not None
    blunder = report.mistakes[0]
    assert move_label(blunder) == "3..."
    assert best_line_san(blunder) == "3...g6"


def test_format_eval() -> None:
    assert format_eval(ev(35)) == "+0.35"
    assert format_eval(ev(-120)) == "-1.20"
    assert format_eval(ev(mate=-2)) == "#-2"
    assert format_eval(ev(100_000)) == "1-0"


def test_render_reports_in_spanish(conn: sqlite3.Connection) -> None:
    console = Console(record=True, width=160)
    game_report = load_game_report(conn, game_id(conn, "g1"))
    assert game_report is not None
    render_game_report(game_report, console)
    render_user_report(load_user_report(conn, "alice"), console)
    text = console.export_text()
    assert "juegas con negras" in text
    assert "error grave" in text
    assert "Nf6" in text and "g6" in text
    assert "pendientes de analizar: 1" in text
    assert "Errores por fase" in text
    assert "derrota" in text


def test_render_user_report_without_games() -> None:
    conn = repo.connect(":memory:")
    console = Console(record=True, width=120)
    render_user_report(load_user_report(conn, "nobody"), console)
    assert "teachess analyze" in console.export_text()
