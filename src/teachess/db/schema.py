"""SQLite schema, versioned with PRAGMA user_version."""

import sqlite3

SCHEMA_VERSION = 1

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
    """Bring the database up to SCHEMA_VERSION."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"La base de datos tiene la versión {version}, más nueva que la soportada "
            f"({SCHEMA_VERSION})."
        )
    if version == 0:
        conn.executescript(_SCHEMA_V1)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
