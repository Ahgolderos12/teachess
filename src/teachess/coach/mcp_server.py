"""MCP server exposing the coach tools, so the coach can run inside Claude Code.

Claude Code is the client (the user's own subscription); this server only provides chess
facts from SQLite and Stockfish plus a `coach` prompt that starts a session on a game.
"""

from collections.abc import Callable
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from teachess.coach.backend import CoachBackend
from teachess.coach.prompts import (
    mcp_coach_prompt,
    mcp_missing_game_prompt,
    mcp_teacher_prompt,
    mcp_teacher_unavailable_prompt,
)
from teachess.coach.tools import TOOL_DEFINITIONS, ToolInputError, show_position

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
            "Usa el prompt `teacher` para una clase guiada por el diagnóstico del jugador, o "
            "`coach` para revisar una partida concreta."
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

    @server.tool(
        name="show_position",
        description=(
            "Diagrama en texto de una posición (FEN), para enseñarla en una terminal. "
            "orientation: el color del jugador, para verla desde su lado."
        ),
    )
    def show_position_tool(fen: str, orientation: Color = "white") -> dict[str, Any]:
        return _call(lambda: show_position(fen, orientation))

    @server.tool(
        description=(
            "Diagnóstico del jugador sobre sus últimas partidas analizadas: resultados y "
            "patrones medidos (derrotas en la apertura, apuros de tiempo, errores por jugar "
            "rápido, ventajas que se escapan, fase más débil, aperturas con mal resultado), "
            "con cifras y posiciones de ejemplo. window: número de partidas recientes (5-100). "
            "user: jugador (por defecto, el de las partidas más recientes)."
        )
    )
    def get_player_diagnosis(window: int = 20, user: str | None = None) -> dict[str, Any]:
        return _call(lambda: backend.diagnosis(user, window))

    @server.prompt(
        name="teacher",
        description=(
            "Clase con el profesor de Teachess: estudia tus últimas partidas y empieza la "
            "lección por lo que más te conviene trabajar."
        ),
    )
    def teacher(user: str | None = None) -> str:
        try:
            diagnosis = backend.diagnosis(user)
        except ToolInputError as exc:
            return mcp_teacher_unavailable_prompt(str(exc))
        if diagnosis["window"]["games"] == 0:
            return mcp_teacher_unavailable_prompt("no hay partidas analizadas.")
        return mcp_teacher_prompt(diagnosis)

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
