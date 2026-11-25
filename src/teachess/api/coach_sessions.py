"""Coach chat for the web, over the paid Claude API. Only enabled with an API key.

`Coach.ask` is blocking and reports through callbacks, so each question runs in a thread
that pushes events into a queue; the HTTP response streams them as Server-Sent Events.
"""

import json
import queue
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import anthropic

from teachess.coach.agent import Coach, CoachConfig
from teachess.coach.backend import BackendEngine, CoachBackend
from teachess.coach.prompts import game_context
from teachess.coach.tools import CoachToolbox
from teachess.config import Effort
from teachess.db import repository as repo
from teachess.report.builder import load_game_report

MAX_SESSIONS = 20
_DONE = object()


class CoachUnavailableError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


class SessionBusyError(Exception):
    pass


@dataclass
class _Session:
    coach: Coach
    game_id: int
    busy: threading.Lock = field(default_factory=threading.Lock)


class CoachSessions:
    def __init__(
        self,
        backend: CoachBackend,
        client_factory: Callable[[], anthropic.Anthropic] | None,
        model: str,
        effort: Effort,
    ):
        self._backend = backend
        self._client_factory = client_factory
        self._model = model
        self._effort = effort
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._client_factory is not None

    def create(self, game_id: int) -> str:
        if self._client_factory is None:
            raise CoachUnavailableError
        with self._backend.connection() as conn:
            report = load_game_report(conn, game_id)
            if report is None:
                raise LookupError(f"La partida {game_id} no existe o no está analizada.")
            moves = repo.get_move_analysis(conn, game_id)
        depth = report.stored.analyzed_depth or self._backend.depth_for(None)
        toolbox = CoachToolbox(report, moves, BackendEngine(self._backend), depth)
        context = game_context(toolbox.game_summary(), toolbox.critical_moments("inaccuracy"))
        coach = Coach(
            self._client_factory(),
            toolbox,
            CoachConfig(model=self._model, effort=self._effort),
            context,
        )
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = _Session(coach=coach, game_id=game_id)
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        return session_id

    def ask(self, session_id: str, text: str) -> Iterator[str]:
        """Start answering `text`; returns the SSE stream of the answer."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._sessions.move_to_end(session_id)
        if session is None:
            raise SessionNotFoundError
        if not session.busy.acquire(blocking=False):
            raise SessionBusyError
        events: queue.Queue[object] = queue.Queue()
        thread = threading.Thread(
            target=_answer, args=(session, text, events), daemon=True, name="coach"
        )
        thread.start()
        return _sse(events)


def _answer(session: _Session, text: str, events: "queue.Queue[object]") -> None:
    try:
        reply = session.coach.ask(
            text,
            on_text=lambda chunk: events.put({"type": "text", "text": chunk}),
            on_tool=lambda name: events.put({"type": "tool", "name": name}),
        )
        usage = session.coach.usage
        events.put(
            {
                "type": "done",
                "refused": reply.refused,
                "truncated": reply.truncated,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                },
            }
        )
    except Exception as exc:  # noqa: BLE001 - reported to the browser, never lost
        events.put({"type": "error", "message": describe_api_error(exc)})
    finally:
        session.busy.release()
        events.put(_DONE)


def _sse(events: "queue.Queue[object]") -> Iterator[str]:
    while True:
        event = events.get()
        if event is _DONE:
            return
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def describe_api_error(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "La clave de Anthropic no es válida. Revisa ANTHROPIC_API_KEY en el archivo .env."
    if isinstance(exc, TypeError) and "authentication" in str(exc):
        return "Falta la clave de Anthropic: configura ANTHROPIC_API_KEY en el archivo .env."
    if isinstance(exc, anthropic.RateLimitError):
        return "Demasiadas peticiones seguidas; espera un poco y repite."
    if isinstance(exc, anthropic.APIConnectionError):
        return "No hay conexión con la API de Anthropic."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Error de la API de Anthropic ({exc.status_code})."
    return f"Error inesperado del coach: {exc}"
