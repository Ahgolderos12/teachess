"""SQLite schema, versioned with PRAGMA user_version."""

import sqlite3
from typing import Any

import chess

from teachess.engine.models import PositionEval
from teachess.engine.scoring import classify, win_loss

SCHEMA_VERSION = 2

_SCHEMA_V1 = """
CREATE TABLE games (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    user_color TEXT NOT NULL CHECK (user_color IN ('white', 'black')),
    white TEXT NOT NULL,
    black TEXT NOT NULL,
    result TEXT NOT NULL,
    time_control TEXT,
    played_at TEXT,
    url TEXT,
    pgn TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    analyzed_depth INTEGER,
    UNIQUE (platform, external_id)
);
CREATE INDEX games_username ON games (username);

CREATE TABLE move_analysis (
    game_id INTEGER NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    ply INTEGER NOT NULL,
    san TEXT NOT NULL,
    uci TEXT NOT NULL,
    fen_before TEXT NOT NULL,
    before_cp INTEGER,
    before_mate INTEGER,
    before_best TEXT,
    before_pv TEXT NOT NULL,
    before_depth INTEGER NOT NULL,
    after_cp INTEGER,
    after_mate INTEGER,
    after_best TEXT,
    after_pv TEXT NOT NULL,
    after_depth INTEGER NOT NULL,
    best_move_san TEXT,
    cp_loss INTEGER NOT NULL,
    classification TEXT NOT NULL,
    phase TEXT NOT NULL,
    clock_seconds REAL,
    PRIMARY KEY (game_id, ply)
);

CREATE TABLE position_evals (
    fen TEXT NOT NULL,
    depth INTEGER NOT NULL,  -- requested depth (cache key)
    cp INTEGER,
    mate INTEGER,
    best_move TEXT,
    pv TEXT NOT NULL,
    reached_depth INTEGER NOT NULL,
    PRIMARY KEY (fen, depth)
);
"""


class SchemaVersionError(RuntimeError):
    pass


def migrate(conn: sqlite3.Connection) -> None:
    """Bring the database up to SCHEMA_VERSION, one version at a time."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"La base de datos tiene la versión {version}, más nueva que la soportada "
            f"({SCHEMA_VERSION})."
        )
    if version < 1:
        conn.executescript(_SCHEMA_V1)
        conn.execute("PRAGMA user_version = 1")
    if version < 2:
        _migrate_to_v2(conn)


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    """Add win_loss and reclassify stored moves by win probability instead of centipawns."""
    with conn:
        conn.execute("ALTER TABLE move_analysis ADD COLUMN win_loss REAL NOT NULL DEFAULT 0")
        rows = conn.execute(
            "SELECT game_id, ply, uci, fen_before, before_cp, before_mate, before_best, "
            "after_cp, after_mate FROM move_analysis"
        ).fetchall()
        conn.executemany(
            "UPDATE move_analysis SET win_loss = ?, classification = ? "
            "WHERE game_id = ? AND ply = ?",
            [_rescore(row) for row in rows],
        )
        conn.execute("PRAGMA user_version = 2")


def _rescore(row: tuple[Any, ...]) -> tuple[Any, ...]:
    game_id, ply, uci, fen_before, b_cp, b_mate, b_best, a_cp, a_mate = row
    before = PositionEval(cp=b_cp, mate=b_mate, best_move=b_best, pv=(), depth=0)
    after = PositionEval(cp=a_cp, mate=a_mate, best_move=None, pv=(), depth=0)
    mover = chess.Board(fen_before).turn
    loss = 0.0 if uci == b_best else win_loss(before, after, mover)
    return (loss, classify(loss), game_id, ply)
