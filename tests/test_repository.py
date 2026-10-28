import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from teachess.db import repository as repo
from teachess.db.schema import SCHEMA_VERSION
from teachess.engine.models import MoveAnalysis, PositionEval
from teachess.ingest.models import ImportedGame

GAME = ImportedGame(
    platform="lichess",
    external_id="abcd1234",
    username="Alice",
    user_color="white",
    white="Alice",
    black="Bob",
    result="1-0",
    time_control="600+0",
    played_at="2026-10-01T10:00:00+00:00",
    url="https://lichess.org/abcd1234",
    pgn='[White "Alice"]\n[Black "Bob"]\n\n1. e4 e5 1-0\n',
)

START_EVAL = PositionEval(cp=30, mate=None, best_move="e2e4", pv=("e2e4", "e7e5"), depth=12)
AFTER_EVAL = PositionEval(cp=None, mate=-3, best_move=None, pv=(), depth=0)

MOVE = MoveAnalysis(
    ply=1,
    san="e4",
    uci="e2e4",
    fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    eval_before=START_EVAL,
    eval_after=AFTER_EVAL,
    best_move_san="e4",
    cp_loss=0,
    classification="ok",
    phase="opening",
    clock_seconds=598.5,
)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = repo.connect(":memory:")
    yield connection
    connection.close()


def test_connect_creates_file_and_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "teachess.sqlite"
    connection = repo.connect(db_path)
    assert db_path.is_file()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    connection.close()
    # Reopening an up-to-date database must not try to recreate tables.
    repo.connect(db_path).close()


def test_insert_game_is_idempotent(conn: sqlite3.Connection) -> None:
    assert repo.insert_game(conn, GAME) is True
    assert repo.insert_game(conn, GAME) is False
    games = repo.list_games(conn)
    assert len(games) == 1
    assert games[0].game == GAME
    assert games[0].analyzed_depth is None


def test_list_games_filters_case_insensitive_user_and_pending(conn: sqlite3.Connection) -> None:
    repo.insert_game(conn, GAME)
    other = replace(GAME, external_id="zzz", username="carol", played_at="2026-10-02")
    repo.insert_game(conn, other)

    assert [g.game.external_id for g in repo.list_games(conn)] == ["zzz", "abcd1234"]
    assert [g.game.external_id for g in repo.list_games(conn, username="alice")] == ["abcd1234"]

    alice_id = repo.list_games(conn, username="alice")[0].id
    repo.save_move_analysis(conn, alice_id, [MOVE], depth=12)
    pending = repo.list_games(conn, pending_only=True)
    assert [g.game.external_id for g in pending] == ["zzz"]


def test_move_analysis_roundtrip_and_replace(conn: sqlite3.Connection) -> None:
    repo.insert_game(conn, GAME)
    game_id = repo.list_games(conn)[0].id

    repo.save_move_analysis(conn, game_id, [MOVE], depth=12)
    assert repo.get_move_analysis(conn, game_id) == [MOVE]

    second = replace(MOVE, ply=2, san="e5", uci="e7e5", clock_seconds=None)
    repo.save_move_analysis(conn, game_id, [second], depth=14)
    assert repo.get_move_analysis(conn, game_id) == [second]
    stored = repo.get_game(conn, game_id)
    assert stored is not None and stored.analyzed_depth == 14


def test_get_game_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert repo.get_game(conn, 999) is None


def test_position_eval_cache(conn: sqlite3.Connection) -> None:
    fen = MOVE.fen_before
    assert repo.get_position_eval(conn, fen, 12) is None
    repo.put_position_eval(conn, fen, 12, START_EVAL)
    assert repo.get_position_eval(conn, fen, 12) == START_EVAL
    assert repo.get_position_eval(conn, fen, 14) is None
