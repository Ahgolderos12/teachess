"""Thread-safe access to games and Stockfish for long-lived servers (MCP, web API).

Servers run handlers in worker threads, so every call opens its own SQLite connection and
all engine calls go through one Stockfish process guarded by a lock. Stockfish is started
on first use and kept open until `close()`.
"""

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from pathlib import Path
from typing import Any

import chess

from teachess.coach.tools import LEVELS, EngineTools, GameTools, ToolInputError
from teachess.db import repository as repo
from teachess.engine.analysis import PersistentCacheEngine
from teachess.engine.models import Engine, PositionEval
from teachess.report.builder import load_game_report


class CoachBackend:
    def __init__(
        self,
        db_path: Path,
        depth: int,
        open_engine: Callable[[], AbstractContextManager[Engine]],
    ):
        self._db_path = db_path
        self._depth = depth  # default depth when no game is involved (TEACHESS_DEPTH)
        self._open_engine = open_engine
        self._lock = threading.Lock()
        self._stack = ExitStack()
        self._engine: Engine | None = None

    def close(self) -> None:
        with self._lock:
            self._stack.close()
            self._engine = None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(repo.connect(self._db_path)) as conn:
            yield conn

    # --- games -------------------------------------------------------------------

    def list_games(self, limit: int) -> dict[str, Any]:
        with self.connection() as conn:
            games = repo.list_games(conn)[: max(1, min(limit, 100))]
            rows = []
            for stored in games:
                game = stored.game
                row: dict[str, Any] = {
                    "game_id": stored.id,
                    "played_at": (game.played_at or "")[:10] or None,
                    "white": game.white,
                    "black": game.black,
                    "user": game.username,
                    "user_color": game.user_color,
                    "result": game.result,
                    "analyzed": stored.analyzed_depth is not None,
                }
                report = load_game_report(conn, stored.id)
                if report is not None:
                    row["user_mistakes"] = {level: report.counts[level] for level in LEVELS}
                rows.append(row)
        return {"games": rows}

    def game(self, game_id: int) -> GameTools:
        with self.connection() as conn:
            report = load_game_report(conn, game_id)
            if report is None:
                raise ToolInputError(f"La partida {game_id} no existe o no está analizada.")
            return GameTools(report, repo.get_move_analysis(conn, game_id))

    def depth_for(self, game_id: int | None) -> int:
        """Depth of the game's stored analysis, so new evaluations never contradict it."""
        if game_id is None:
            return self._depth
        with self.connection() as conn:
            stored = repo.get_game(conn, game_id)
        if stored is None or stored.analyzed_depth is None:
            raise ToolInputError(f"La partida {game_id} no existe o no está analizada.")
        return stored.analyzed_depth

    # --- engine ------------------------------------------------------------------

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        """Evaluate with the shared Stockfish, through the persistent (FEN, depth) cache."""
        with self.connection() as conn:
            return PersistentCacheEngine(_LockedEngine(self), conn).analyse(board, depth)

    @contextmanager
    def engine_tools(self, game_id: int | None = None) -> Iterator[EngineTools]:
        depth = self.depth_for(game_id)
        yield EngineTools(BackendEngine(self), depth)

    def _shared_engine(self) -> Engine:
        """Start Stockfish if needed. Must be called with the lock held."""
        if self._engine is None:
            self._engine = self._stack.enter_context(self._open_engine())
        return self._engine


class _LockedEngine:
    def __init__(self, backend: CoachBackend):
        self._backend = backend

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        with self._backend._lock:
            return self._backend._shared_engine().analyse(board, depth)


class BackendEngine:
    """Engine protocol over a CoachBackend: safe to call from any thread."""

    def __init__(self, backend: CoachBackend):
        self._backend = backend

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        return self._backend.analyse(board, depth)
