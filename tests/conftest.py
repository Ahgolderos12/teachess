"""Shared fixtures."""

import sqlite3
from collections.abc import Iterator

import pytest

from teachess.coach.tools import CoachToolbox
from teachess.db import repository as repo
from teachess.engine.analysis import analyse_game
from teachess.ingest.models import ImportedGame
from teachess.report.builder import load_game_report
from tests.fakes import SCHOLAR_PGN, ScriptedEngine, read

COACH_GAME = ImportedGame(
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


@pytest.fixture
def toolbox() -> Iterator[CoachToolbox]:
    """Coach tools over the analysed Scholar's mate game, with the user playing Black."""
    conn: sqlite3.Connection = repo.connect(":memory:")
    repo.insert_game(conn, COACH_GAME)
    stored = repo.list_games(conn)[0]
    moves = analyse_game(read(SCHOLAR_PGN), ScriptedEngine(), depth=10)
    repo.save_move_analysis(conn, stored.id, moves, depth=10)
    report = load_game_report(conn, stored.id)
    assert report is not None
    yield CoachToolbox(report, repo.get_move_analysis(conn, stored.id), ScriptedEngine(), 10)
    conn.close()
