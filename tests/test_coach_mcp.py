import asyncio
from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import chess
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from teachess.coach.backend import CoachBackend
from teachess.coach.mcp_server import build_server
from teachess.db import repository as repo
from teachess.engine.analysis import analyse_game
from teachess.engine.models import Engine, PositionEval
from teachess.engine.stockfish import StockfishNotConfiguredError
from tests.conftest import COACH_GAME
from tests.fakes import SCHOLAR_PGN, ScriptedEngine, read

FEN_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "coach.sqlite"
    conn = repo.connect(path)
    repo.insert_game(conn, COACH_GAME)
    repo.insert_game(conn, COACH_GAME.__class__(**{**COACH_GAME.__dict__, "external_id": "g2"}))
    analysed = repo.list_games(conn)[-1].id
    moves = analyse_game(read(SCHOLAR_PGN), ScriptedEngine(), depth=10)
    repo.save_move_analysis(conn, analysed, moves, depth=10)
    conn.close()
    return path


class DepthRecordingEngine(ScriptedEngine):
    def __init__(self) -> None:
        super().__init__()
        self.depths: list[int] = []

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        self.depths.append(depth)
        return super().analyse(board, depth)


class EngineOpener:
    def __init__(self) -> None:
        self.opened = 0
        self.engine = DepthRecordingEngine()

    def __call__(self) -> AbstractContextManager[Engine]:
        self.opened += 1
        return nullcontext(self.engine)


@pytest.fixture
def opener() -> EngineOpener:
    return EngineOpener()


@pytest.fixture
def server(db_path: Path, opener: EngineOpener) -> Iterator[MCPServer]:
    backend = CoachBackend(db_path, 16, opener)  # TEACHESS_DEPTH 16; the game was analysed at 10
    yield build_server(backend)
    backend.close()


def call(server: MCPServer, name: str, **arguments: Any) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, arguments))
    assert not result.is_error
    data: dict[str, Any] = result.structured_content
    return data


def test_lists_tools_and_games(server: MCPServer) -> None:
    names = [t.name for t in asyncio.run(server.list_tools())]
    assert names == [
        "list_games",
        "get_game_summary",
        "get_critical_moments",
        "get_move",
        "evaluate_position",
        "evaluate_move",
    ]
    games = call(server, "list_games")["games"]
    assert [g["analyzed"] for g in games] == [False, True]  # newest first (same date: by id)
    assert games[1]["user_mistakes"] == {"inaccuracy": 0, "mistake": 0, "blunder": 1}
    assert "user_mistakes" not in games[0]


def test_game_tools_take_a_game_id(server: MCPServer) -> None:
    assert call(server, "get_game_summary", game_id=1)["user_color"] == "black"
    moments = call(server, "get_critical_moments", game_id=1, min_level="blunder")["moments"]
    assert [m["move"] for m in moments] == ["3...Nf6"]
    assert call(server, "get_move", game_id=1, move_number=2, color="white")["move"] == "2.Qh5"


def test_engine_tools_start_stockfish_once(server: MCPServer, opener: EngineOpener) -> None:
    assert opener.opened == 0  # not started until needed
    assert call(server, "evaluate_position", fen=FEN_BEFORE_NF6)["best_move"] == "g6"
    result = call(server, "evaluate_move", fen=FEN_BEFORE_NF6, move="Nf6")
    assert result["classification"] == "blunder"
    assert opener.opened == 1
    # No game_id: TEACHESS_DEPTH. The position before Nf6 comes from the persistent cache.
    assert opener.engine.depths == [16, 16]


def test_engine_tools_use_the_games_analysis_depth(server: MCPServer, opener: EngineOpener) -> None:
    call(server, "evaluate_move", fen=FEN_BEFORE_NF6, move="Nf6", game_id=1)
    assert set(opener.engine.depths) == {10}
    with pytest.raises(ToolError, match="no está analizada"):
        asyncio.run(server.call_tool("evaluate_position", {"fen": FEN_BEFORE_NF6, "game_id": 2}))


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("get_move", {"game_id": 2, "move_number": 1, "color": "white"}, "no está analizada"),
        ("get_move", {"game_id": 1, "move_number": 30, "color": "white"}, "no existe"),
        ("evaluate_move", {"fen": FEN_BEFORE_NF6, "move": "Ke2"}, "Jugadas legales"),
        ("evaluate_position", {"fen": "x"}, "FEN no válido"),
    ],
)
def test_errors_reach_the_model(
    server: MCPServer, name: str, arguments: dict[str, Any], expected: str
) -> None:
    with pytest.raises(ToolError, match=expected):
        asyncio.run(server.call_tool(name, arguments))


def test_missing_stockfish_is_a_tool_error(db_path: Path) -> None:
    def no_stockfish() -> AbstractContextManager[Engine]:
        raise StockfishNotConfiguredError("STOCKFISH_PATH no está configurado")

    server = build_server(CoachBackend(db_path, 16, no_stockfish))
    with pytest.raises(ToolError, match="STOCKFISH_PATH"):
        asyncio.run(server.call_tool("evaluate_position", {"fen": FEN_BEFORE_NF6}))
    assert call(server, "get_game_summary", game_id=1)["result"] == "1-0"  # rest still works


def test_coach_prompt_starts_a_session(server: MCPServer) -> None:
    result = asyncio.run(server.get_prompt("coach", {"game_id": "1"}))
    text = result.messages[0].content.text
    assert text.startswith("Eres Teachess")
    assert "`game_id` = 1" in text
    assert "3...Nf6" in text and "<datos_partida>" in text
    missing = asyncio.run(server.get_prompt("coach", {"game_id": "2"})).messages[0].content.text
    assert "no existe o no está analizada" in missing and "list_games" in missing
