"""Teacher tab: Claude Code running in a pseudo-terminal, bridged to the browser.

The browser talks to this module over a WebSocket; the process is the user's own Claude Code
(their subscription), started as the Teacher: its instructions go in the system prompt and
the first message just starts the lesson. Claude Code is
locked down: no built-in tools (no shell, no file access), only the `teachess` MCP server.

Security: a WebSocket is not covered by CORS, so any web page open in the browser could try
to connect to 127.0.0.1. Connections need the right `Origin` and a per-start token that only
same-origin pages can read (GET /api/teacher).

Unix only (pty); on Windows the tab shows how to run the same command in a terminal.
"""

import asyncio
import codecs
import contextlib
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from starlette.websockets import WebSocket, WebSocketDisconnect

from teachess.coach.prompts import TERMINAL_START_MESSAGE, teacher_terminal_system_prompt

log = logging.getLogger(__name__)

MANUAL_COMMAND = "claude /mcp__teachess__teacher"  # same lesson from any terminal
# Variables never passed to Claude Code: an API key would make it bill the API instead of
# using the user's subscription, and the session markers make it think it runs nested inside
# another Claude Code session (when `teachess serve` was itself started from one).
_DROPPED_ENV = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_PID"}
_DROPPED_PREFIXES = (
    "CLAUDE_CODE_SESSION",
    "CLAUDE_CODE_CHILD",
    "CLAUDE_CODE_MESSAGING",
    "CLAUDE_CODE_ENTRYPOINT",
)
MAX_COLS = 500
MAX_ROWS = 200
SESSION_ENV = "TEACHESS_TERMINAL_SESSION"
READY_TIMEOUT_SECONDS = 45.0
READY_GRACE_SECONDS = 1.5  # the MCP handshake finishes just after the server announces itself


def claude_command(
    claude: str,
    python: str = sys.executable,
    model: str | None = None,
    session: str | None = None,
) -> list[str]:
    """Claude Code with only the teachess MCP server: no shell, files, browser or skills.

    `dontAsk` denies any tool outside the allow-list without prompting, whatever the user's
    default permission mode is. `session` reaches the MCP server, which announces when it is
    up so the lesson only starts once its tools exist (see `kickoff`).
    """
    server: dict[str, Any] = {"command": python, "args": ["-m", "teachess", "mcp"]}
    if session:
        server["env"] = {SESSION_ENV: session}
    command = [
        claude,
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        json.dumps({"mcpServers": {"teachess": server}}),
        "--allowedTools",
        "mcp__teachess",
        "--permission-mode",
        "dontAsk",
        "--no-chrome",
        "--disable-slash-commands",
        "--append-system-prompt",
        teacher_terminal_system_prompt(),
    ]
    if model:
        command += ["--model", model]
    return command


def child_env(base: Mapping[str, str]) -> dict[str, str]:
    env = {
        k: v
        for k, v in base.items()
        if k not in _DROPPED_ENV and not k.startswith(_DROPPED_PREFIXES)
    }
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    return env


class TeacherTerminal:
    def __init__(
        self,
        cwd: Path,
        allowed_hosts: Sequence[str],
        command: list[str] | None = None,  # tests: a fake program instead of Claude Code
        model: str | None = None,  # Claude Code model; None: the user's default
        mcp_ready: Callable[[str], bool] | None = None,  # has this session's MCP server started?
    ):
        self._cwd = cwd
        self._allowed_hosts = {h for h in allowed_hosts if h != "*"} | {"127.0.0.1", "localhost"}
        self.token = secrets.token_urlsafe(24)
        self._fixed_command = command
        self._claude = None if command else shutil.which("claude")
        self._model = model
        self._mcp_ready = mcp_ready
        self._active: subprocess.Popen[bytes] | None = None

    def _command(self, session: str) -> list[str] | None:
        if self._fixed_command is not None:
            return self._fixed_command
        if self._claude is None:
            return None
        return claude_command(self._claude, model=self._model, session=session)

    def availability(self) -> tuple[bool, str | None]:
        if os.name != "posix":
            return False, "La terminal integrada solo funciona en macOS y Linux."
        if self._fixed_command is None and self._claude is None:
            return False, "No se encuentra Claude Code (el comando `claude`) en el PATH."
        return True, None

    def info(self) -> dict[str, Any]:
        available, reason = self.availability()
        return {
            "available": available,
            "reason": reason,
            "token": self.token if available else None,
            "manual_command": MANUAL_COMMAND,
        }

    def origin_allowed(self, origin: str | None) -> bool:
        if not origin:
            return False
        parts = urlsplit(origin)
        return parts.scheme in ("http", "https") and parts.hostname in self._allowed_hosts

    def close(self) -> None:
        if self._active is not None:
            _terminate(self._active)
            self._active = None

    async def serve(self, websocket: WebSocket) -> None:
        """Run one terminal session for the WebSocket until either side closes."""
        token = websocket.query_params.get("token", "")
        if not secrets.compare_digest(token, self.token) or not self.origin_allowed(
            websocket.headers.get("origin")
        ):
            await websocket.close(code=4403)
            return
        session = secrets.token_hex(8)
        command = self._command(session)
        if not self.availability()[0] or command is None:
            await websocket.close(code=4503)
            return
        await websocket.accept()
        await asyncio.to_thread(self.close)  # one lesson at a time: a reload replaces it
        cols = _clamp(websocket.query_params.get("cols"), 100, MAX_COLS)
        rows = _clamp(websocket.query_params.get("rows"), 30, MAX_ROWS)
        process, master = _spawn(command, self._cwd, cols, rows)
        self._active = process
        starter = None
        if self._mcp_ready is not None:
            ready = self._mcp_ready
            starter = asyncio.create_task(kickoff(master, lambda: ready(session)))
        try:
            await _bridge(websocket, process, master)
        finally:
            if starter is not None:
                starter.cancel()
            await asyncio.to_thread(_terminate, process)
            if self._active is process:
                self._active = None
            with contextlib.suppress(OSError):
                os.close(master)


def _spawn(command: list[str], cwd: Path, cols: int, rows: int) -> tuple[Any, int]:
    import pty  # Unix only

    master, slave = pty.openpty()
    _set_size(master, cols, rows)
    try:
        process = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=cwd,
            env=child_env(os.environ),
            start_new_session=True,  # own process group, so we can signal and kill it whole
            close_fds=True,
        )
    finally:
        os.close(slave)
    os.set_blocking(master, False)
    return process, master


async def _bridge(websocket: WebSocket, process: Any, master: int) -> None:
    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes | None] = asyncio.Queue()

    def readable() -> None:
        try:
            data = os.read(master, 65536)
        except BlockingIOError:
            return
        except OSError:  # EIO: the child closed the terminal
            data = b""
        if not data:
            loop.remove_reader(master)
            output.put_nowait(None)
        else:
            output.put_nowait(data)

    loop.add_reader(master, readable)

    async def pump_output() -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while (chunk := await output.get()) is not None:
            await websocket.send_text(json.dumps({"type": "output", "data": decoder.decode(chunk)}))
        code = await asyncio.to_thread(process.wait)
        await websocket.send_text(json.dumps({"type": "exit", "code": code}))

    async def pump_input() -> None:
        while True:
            message = json.loads(await websocket.receive_text())
            if message.get("type") == "input" and isinstance(message.get("data"), str):
                os.write(master, message["data"].encode())
            elif message.get("type") == "resize":
                _set_size(
                    master,
                    _clamp(message.get("cols"), 100, MAX_COLS),
                    _clamp(message.get("rows"), 30, MAX_ROWS),
                )
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGWINCH)

    tasks = [asyncio.create_task(pump_output()), asyncio.create_task(pump_input())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        with contextlib.suppress(Exception):
            loop.remove_reader(master)
        with contextlib.suppress(Exception):
            await websocket.close()


async def kickoff(
    fd: int,
    ready: Callable[[], bool],
    text: str = TERMINAL_START_MESSAGE,
    timeout: float = READY_TIMEOUT_SECONDS,
    grace: float = READY_GRACE_SECONDS,
) -> None:
    """Type the first message once the MCP server is up (or after `timeout` anyway).

    Passing it as a command-line prompt would race with the MCP connection: Claude Code
    would answer before the teachess tools exist.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline and not await asyncio.to_thread(ready):
        await asyncio.sleep(0.25)
    await asyncio.sleep(grace)
    os.write(fd, text.encode())
    await asyncio.sleep(0.3)  # separate keystroke, so the TUI doesn't take it as pasted text
    os.write(fd, b"\r")


def _set_size(fd: int, cols: int, rows: int) -> None:
    import fcntl
    import struct
    import termios

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _terminate(process: Any) -> None:
    if process.poll() is not None:
        return
    for sig, wait in ((signal.SIGHUP, 1.0), (signal.SIGKILL, 2.0)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, sig)
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _clamp(value: object, default: int, maximum: int) -> int:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(2, min(number, maximum))
