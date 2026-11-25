"""Teacher terminal: WebSocket <-> pseudo-terminal bridge, with a fake program as Claude Code."""

import asyncio
import json
import os
import sys
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from teachess.api.app import ApiConfig
from teachess.api.terminal import MANUAL_COMMAND, child_env, claude_command, kickoff
from teachess.coach.prompts import TERMINAL_START_MESSAGE
from tests.test_api import config as api_config  # noqa: F401 - fixture
from tests.test_api import make_client, ok

pytestmark = pytest.mark.skipif(os.name != "posix", reason="pty is Unix only")

# Prints its terminal size, then echoes one line back and exits with code 3.
FAKE_CLAUDE = (
    "import os, sys\n"
    "size = os.get_terminal_size(0)\n"
    "print(f'size {size.columns}x{size.lines}', flush=True)\n"
    "line = sys.stdin.readline()\n"
    "print('echo ' + line.strip(), flush=True)\n"
    "sys.exit(3)\n"
)
ORIGIN = {"origin": "http://127.0.0.1:8000"}


@pytest.fixture
def client(api_config: ApiConfig, tmp_path: Path) -> Iterator[TestClient]:  # noqa: F811
    fake = replace(
        api_config,
        project_dir=tmp_path,
        teacher_command=[sys.executable, "-c", FAKE_CLAUDE],
        allowed_hosts=["testserver"],
    )
    yield from make_client(fake)


def read_until_exit(ws: Any) -> tuple[str, int]:
    output = ""
    while True:
        message = json.loads(ws.receive_text())
        if message["type"] == "exit":
            return output, message["code"]
        output += message["data"]


def test_terminal_runs_the_program_in_a_pty(client: TestClient) -> None:
    info = ok(client.get("/api/teacher"))
    assert info["available"] is True and info["token"]
    assert info["manual_command"] == MANUAL_COMMAND
    url = f"/api/teacher/terminal?token={info['token']}&cols=90&rows=20"
    with client.websocket_connect(url, headers=ORIGIN) as ws:
        first = json.loads(ws.receive_text())
        assert first == {"type": "output", "data": "size 90x20\r\n"}
        ws.send_text(json.dumps({"type": "input", "data": "hola\r"}))
        output, code = read_until_exit(ws)
    assert "echo hola" in output and code == 3


@pytest.mark.parametrize(
    ("token", "headers"),
    [
        ("wrong", ORIGIN),
        (None, {"origin": "https://evil.example"}),
        (None, {}),
    ],
)
def test_terminal_rejects_foreign_pages(
    client: TestClient, token: str | None, headers: dict[str, str]
) -> None:
    real = ok(client.get("/api/teacher"))["token"]
    url = f"/api/teacher/terminal?token={token or real}"
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(url, headers=headers) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4403


def test_claude_is_locked_down_and_never_gets_the_api_key() -> None:
    command = claude_command("/bin/claude", python="/py")
    assert command[0] == "/bin/claude" and TERMINAL_START_MESSAGE not in command
    system = command[command.index("--append-system-prompt") + 1]
    assert "llama a `get_player_diagnosis`" in system and "<diagnostico>" not in system
    assert command[command.index("--tools") + 1] == ""  # no shell, no file tools
    assert "--strict-mcp-config" in command
    assert command[command.index("--allowedTools") + 1] == "mcp__teachess"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "--no-chrome" in command and "--disable-slash-commands" in command
    assert "--model" not in command
    with_model = claude_command("/bin/claude", python="/py", model="claude-opus-5-5", session="s1")
    assert with_model[with_model.index("--model") + 1] == "claude-opus-5-5"
    server = json.loads(with_model[with_model.index("--mcp-config") + 1])["mcpServers"]["teachess"]
    assert server["env"] == {"TEACHESS_TERMINAL_SESSION": "s1"}
    mcp = json.loads(command[command.index("--mcp-config") + 1])
    assert mcp == {
        "mcpServers": {"teachess": {"command": "/py", "args": ["-m", "teachess", "mcp"]}}
    }
    env = child_env(
        {
            "ANTHROPIC_API_KEY": "sk",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "x",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "PATH": "/bin",
        }
    )
    assert set(env) == {"CLAUDE_CODE_USE_BEDROCK", "PATH", "TERM", "COLORTERM"}
    assert env["TERM"] == "xterm-256color"


def test_teacher_board_shows_the_last_position(client: TestClient) -> None:
    assert ok(client.get("/api/teacher/board")) == {"board": None}


def test_kickoff_types_the_first_message_once_mcp_is_ready() -> None:
    read_end, write_end = os.pipe()
    checks = iter([False, False, True])
    try:
        asyncio.run(kickoff(write_end, lambda: next(checks), text="Empieza", grace=0))
        assert os.read(read_end, 100) == b"Empieza\r"
        # Never ready: it still starts after the timeout, so the lesson does not hang.
        asyncio.run(kickoff(write_end, lambda: False, text="Hola", timeout=0.1, grace=0))
        assert os.read(read_end, 100) == b"Hola\r"
    finally:
        os.close(read_end)
        os.close(write_end)


def test_mcp_server_announces_its_terminal_session(tmp_path: Path) -> None:
    from teachess.coach.backend import CoachBackend
    from tests.fakes import ScriptedEngine

    backend = CoachBackend(tmp_path / "db.sqlite", 10, lambda: nullcontext(ScriptedEngine()))
    assert backend.mcp_ready("abc") is False
    backend.announce_mcp_ready("abc")
    assert backend.mcp_ready("abc") is True and backend.mcp_ready("other") is False
