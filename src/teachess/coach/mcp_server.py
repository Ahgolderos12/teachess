"""MCP server exposing the coach tools, so the coach can run inside Claude Code.

Claude Code is the client (the user's own subscription); this server only provides chess
facts from SQLite and Stockfish plus a `coach` prompt that starts a session on a game.
"""

from collections.abc import Callable
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from teachess.coach.backend import CoachBackend
from teachess.coach.prompts import mcp_coach_prompt, mcp_missing_game_prompt
from teachess.coach.tools import TOOL_DEFINITIONS, ToolInputError

DESCRIPTIONS = {tool["name"]: tool["description"] for tool in TOOL_DEFINITIONS}
GAME_ID_NOTE = " Requiere game_id (ver list_games)."
DEPTH_NOTE = (
    " Si la posición es de una partida, pasa su game_id para analizar a la misma profundidad "
    "que el análisis guardado y no contradecirlo."
)
Level = Literal["inaccuracy", "mistake", "blunder"]
Color = Literal["white", "black"]
T = TypeVar("T")


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
