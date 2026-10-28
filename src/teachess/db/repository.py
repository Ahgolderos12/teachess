"""Data access for games, per-move analysis and the persistent engine cache."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from teachess.db.schema import migrate
from teachess.engine.models import MoveAnalysis, PositionEval
from teachess.ingest.models import ImportedGame


@dataclass(frozen=True)
class StoredGame:
    id: int
    game: ImportedGame
    imported_at: str
    analyzed_depth: int | None  # None until the game has been analysed


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the database and apply pending migrations."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


# --- games -----------------------------------------------------------------

_GAME_FIELDS = (
    "platform, external_id, username, user_color, white, black, result, "
    "time_control, played_at, url, pgn"
)


def insert_game(conn: sqlite3.Connection, game: ImportedGame) -> bool:
    """Store a game unless it was already imported. Returns True if it is new."""
    with conn:
        cursor = conn.execute(
            f"INSERT INTO games ({_GAME_FIELDS}, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (platform, external_id) DO NOTHING",
            (
                game.platform,
                game.external_id,
                game.username,
                game.user_color,
                game.white,
                game.black,
                game.result,
                game.time_control,
                game.played_at,
                game.url,
                game.pgn,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
    return cursor.rowcount == 1


def get_game(conn: sqlite3.Connection, game_id: int) -> StoredGame | None:
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    return _row_to_game(row) if row else None


def list_games(
    conn: sqlite3.Connection, *, username: str | None = None, pending_only: bool = False
) -> list[StoredGame]:
    """Games newest first, optionally for one user and/or not yet analysed."""
    clauses: list[str] = []
    params: list[Any] = []
    if username is not None:
        clauses.append("username = ?")
        params.append(username)
    if pending_only:
        clauses.append("analyzed_depth IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM games {where} ORDER BY played_at DESC, id DESC", params
    ).fetchall()
    return [_row_to_game(row) for row in rows]


def _row_to_game(row: sqlite3.Row) -> StoredGame:
    game = ImportedGame(
        platform=row["platform"],
        external_id=row["external_id"],
        username=row["username"],
        user_color=row["user_color"],
        white=row["white"],
        black=row["black"],
        result=row["result"],
        time_control=row["time_control"],
        played_at=row["played_at"],
        url=row["url"],
        pgn=row["pgn"],
    )
    return StoredGame(
        id=row["id"],
        game=game,
        imported_at=row["imported_at"],
        analyzed_depth=row["analyzed_depth"],
    )


# --- move analysis -----------------------------------------------------------


def save_move_analysis(
    conn: sqlite3.Connection, game_id: int, moves: list[MoveAnalysis], depth: int
) -> None:
    """Replace any previous analysis of the game and mark it as analysed."""
    with conn:
        conn.execute("DELETE FROM move_analysis WHERE game_id = ?", (game_id,))
        conn.executemany(
            "INSERT INTO move_analysis VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_move_to_row(game_id, m) for m in moves],
        )
        conn.execute("UPDATE games SET analyzed_depth = ? WHERE id = ?", (depth, game_id))


def get_move_analysis(conn: sqlite3.Connection, game_id: int) -> list[MoveAnalysis]:
    rows = conn.execute(
        "SELECT * FROM move_analysis WHERE game_id = ? ORDER BY ply", (game_id,)
    ).fetchall()
    return [_row_to_move(row) for row in rows]


def _move_to_row(game_id: int, m: MoveAnalysis) -> tuple[Any, ...]:
    return (
        game_id,
        m.ply,
        m.san,
        m.uci,
        m.fen_before,
        *_eval_to_columns(m.eval_before),
        *_eval_to_columns(m.eval_after),
        m.best_move_san,
        m.cp_loss,
        m.classification,
        m.phase,
        m.clock_seconds,
    )


def _row_to_move(row: sqlite3.Row) -> MoveAnalysis:
    return MoveAnalysis(
        ply=row["ply"],
        san=row["san"],
        uci=row["uci"],
        fen_before=row["fen_before"],
        eval_before=_columns_to_eval(row, "before"),
        eval_after=_columns_to_eval(row, "after"),
        best_move_san=row["best_move_san"],
        cp_loss=row["cp_loss"],
        classification=row["classification"],
        phase=row["phase"],
        clock_seconds=row["clock_seconds"],
    )


def _eval_to_columns(e: PositionEval) -> tuple[Any, ...]:
    return (e.cp, e.mate, e.best_move, " ".join(e.pv), e.depth)


def _columns_to_eval(row: sqlite3.Row, prefix: str) -> PositionEval:
    return PositionEval(
        cp=row[f"{prefix}_cp"],
        mate=row[f"{prefix}_mate"],
        best_move=row[f"{prefix}_best"],
        pv=tuple(row[f"{prefix}_pv"].split()),
        depth=row[f"{prefix}_depth"],
    )


# --- persistent engine cache ---------------------------------------------------


def get_position_eval(conn: sqlite3.Connection, fen: str, depth: int) -> PositionEval | None:
    row = conn.execute(
        "SELECT * FROM position_evals WHERE fen = ? AND depth = ?", (fen, depth)
    ).fetchone()
    if row is None:
        return None
    return PositionEval(
        cp=row["cp"],
        mate=row["mate"],
        best_move=row["best_move"],
        pv=tuple(row["pv"].split()),
        depth=row["reached_depth"],
    )


def put_position_eval(
    conn: sqlite3.Connection, fen: str, depth: int, evaluation: PositionEval
) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO position_evals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                fen,
                depth,
                evaluation.cp,
                evaluation.mate,
                evaluation.best_move,
                " ".join(evaluation.pv),
                evaluation.depth,
            ),
        )
