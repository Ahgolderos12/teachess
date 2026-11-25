"""MCP server exposing the coach tools, so the coach can run inside Claude Code.

Claude Code is the client (the user's own subscription); this server only provides chess
facts from SQLite and Stockfish plus a `coach` prompt that starts a session on a game.
Sync tools run in worker threads, so each call opens its own SQLite connection and engine
calls are serialised with a lock.
"""

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, closing, contextmanager
from pathlib import Path
from typing import Any, Literal, TypeVar

import chess
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from teachess.coach.prompts import mcp_coach_prompt, mcp_missing_game_prompt
from teachess.coach.tools import (
    TOOL_DEFINITIONS,
    EngineTools,
    GameTools,
    ToolInputError,
)
from teachess.db import repository as repo
from teachess.engine.analysis import PersistentCacheEngine
from teachess.engine.models import Engine, PositionEval
from teachess.report.builder import load_game_report

DESCRIPTIONS = {tool["name"]: tool["description"] for tool in TOOL_DEFINITIONS}
GAME_ID_NOTE = " Requiere game_id (ver list_games)."
DEPTH_NOTE = (
    " Si la posición es de una partida, pasa su game_id para analizar a la misma profundidad "
    "que el análisis guardado y no contradecirlo."
)
Level = Literal["inaccuracy", "mistake", "blunder"]
Color = Literal["white", "black"]
T = TypeVar("T")


class _LockedEngine:
    def __init__(self, inner: Engine, lock: threading.Lock):
        self._inner = inner
        self._lock = lock

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        with self._lock:
            return self._inner.analyse(board, depth)


class CoachBackend:
    """Data access for the MCP tools. Stockfish is started on first use and kept open."""

    def __init__(
        self,
        db_path: Path,
        depth: int,
        open_engine: Callable[[], AbstractContextManager[Engine]],
    ):
        self._db_path = db_path
        self._depth = depth
        self._open_engine = open_engine
        self._lock = threading.Lock()
        self._stack = ExitStack()
        self._engine: Engine | None = None

    def close(self) -> None:
        self._stack.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(repo.connect(self._db_path)) as conn:
            yield conn

    def list_games(self, limit: int) -> dict[str, Any]:
        with self._connection() as conn:
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
                    row["user_mistakes"] = {
                        level: report.counts[level]
                        for level in ("inaccuracy", "mistake", "blunder")
                    }
                rows.append(row)
        return {"games": rows}

    def game(self, game_id: int) -> GameTools:
        with self._connection() as conn:
            report = load_game_report(conn, game_id)
            if report is None:
                raise ToolInputError(f"La partida {game_id} no existe o no está analizada.")
            return GameTools(report, repo.get_move_analysis(conn, game_id))

    @contextmanager
    def engine_tools(self, game_id: int | None = None) -> Iterator[EngineTools]:
        """Engine tools at the depth of the given game's analysis (default: TEACHESS_DEPTH)."""
        with self._connection() as conn:
            depth = self._depth
            if game_id is not None:
                stored = repo.get_game(conn, game_id)
                if stored is None or stored.analyzed_depth is None:
                    raise ToolInputError(f"La partida {game_id} no existe o no está analizada.")
                depth = stored.analyzed_depth
            with self._lock:
                if self._engine is None:
                    self._engine = self._stack.enter_context(self._open_engine())
                engine = _LockedEngine(self._engine, self._lock)
            yield EngineTools(PersistentCacheEngine(engine, conn), depth)


def build_server(backend: CoachBackend) -> MCPServer:
    server = MCPServer(
        "teachess",
        instructions=(
            "Herramientas de ajedrez de Teachess: partidas del jugador analizadas con Stockfish "
            "y consultas al motor. Los hechos ajedrecísticos salen de aquí, no del modelo. "
            "Usa el prompt `coach` para empezar una sesión de entrenamiento sobre una partida."
        ),
    )

    @server.tool(
        description="Partidas importadas del jugador, de la más reciente a la más antigua."
    )
    def list_games(limit: int = 20) -> dict[str, Any]:
        return _call(lambda: backend.list_games(limit))

    @server.tool(description=DESCRIPTIONS["get_game_summary"] + GAME_ID_NOTE)
    def get_game_summary(game_id: int) -> dict[str, Any]:
        return _call(lambda: backend.game(game_id).summary())

    @server.tool(description=DESCRIPTIONS["get_critical_moments"] + GAME_ID_NOTE)
    def get_critical_moments(game_id: int, min_level: Level = "inaccuracy") -> dict[str, Any]:
        return _call(lambda: backend.game(game_id).critical_moments(min_level))

    @server.tool(description=DESCRIPTIONS["get_move"] + GAME_ID_NOTE)
    def get_move(game_id: int, move_number: int, color: Color) -> dict[str, Any]:
        return _call(lambda: backend.game(game_id).move(move_number, color))

    @server.tool(description=DESCRIPTIONS["evaluate_position"] + DEPTH_NOTE)
    def evaluate_position(fen: str, game_id: int | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            with backend.engine_tools(game_id) as tools:
                return tools.evaluate_position(fen)

        return _call(run)

    @server.tool(description=DESCRIPTIONS["evaluate_move"] + DEPTH_NOTE)
    def evaluate_move(fen: str, move: str, game_id: int | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            with backend.engine_tools(game_id) as tools:
                return tools.evaluate_move(fen, move)

        return _call(run)

    @server.prompt(
        name="coach",
        description="Empieza una sesión con el coach de Teachess sobre una partida analizada.",
    )
    def coach(game_id: int) -> str:
        try:
            game = backend.game(game_id)
        except ToolInputError:
            return mcp_missing_game_prompt(game_id)
        return mcp_coach_prompt(game_id, game.summary(), game.critical_moments("inaccuracy"))

    return server


def _call(fn: Callable[[], T]) -> T:
    """Turn invalid input and setup problems into MCP tool errors the model can read."""
    try:
        return fn()
    except ToolInputError as exc:
        raise ToolError(str(exc)) from None
    except RuntimeError as exc:  # e.g. Stockfish not configured
        raise ToolError(str(exc)) from None
