"""FastAPI application: JSON API under /api and the compiled web app at /."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import anthropic
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from teachess import __version__
from teachess.api import serializers
from teachess.api.coach_sessions import (
    CoachSessions,
    CoachUnavailableError,
    SessionBusyError,
    SessionNotFoundError,
)
from teachess.api.jobs import JobError, JobManager, Progress
from teachess.api.services import EngineFactory, HttpClientFactory, analyse_games, import_games
from teachess.coach.backend import CoachBackend
from teachess.coach.tools import ToolInputError
from teachess.config import Effort
from teachess.db import repository as repo
from teachess.report.builder import load_game_report, load_user_report

MCP_COACH_COMMAND = "/mcp__teachess__coach"


@dataclass(frozen=True)
class ApiConfig:
    db_path: Path
    engine_depth: int
    open_engine: EngineFactory
    http_client: HttpClientFactory
    stockfish_configured: bool
    model: str
    effort: Effort
    default_users: dict[str, str | None] = field(default_factory=dict)
    anthropic_client: Callable[[], anthropic.Anthropic] | None = None  # None: web coach off
    static_dir: Path | None = None
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    job_manager: JobManager | None = None  # tests inject a synchronous one


# --- request bodies -----------------------------------------------------------------


class ImportRequest(BaseModel):
    platform: Literal["chesscom", "lichess", "pgn"]
    user: str | None = Field(default=None, max_length=100)
    max_games: int = Field(default=50, ge=1, le=500)
    pgn: str | None = Field(default=None, max_length=5_000_000)
    color: Literal["white", "black"] | None = None
    analyze: bool = False


class AnalysisRequest(BaseModel):
    game_id: int | None = None
    user: str | None = Field(default=None, max_length=100)
    depth: int | None = Field(default=None, ge=1, le=30)
    reanalyze: bool = False

    @model_validator(mode="after")
    def exactly_one_target(self) -> "AnalysisRequest":
        if (self.game_id is None) == (self.user is None):
            raise ValueError("Indica game_id o user (solo uno).")
        return self


class EvaluateRequest(BaseModel):
    fen: str = Field(max_length=200)
    game_id: int | None = None


class MoveRequest(EvaluateRequest):
    move: str = Field(max_length=10)


class CoachSessionRequest(BaseModel):
    game_id: int


class CoachMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


# --- application ---------------------------------------------------------------------


def create_app(config: ApiConfig) -> FastAPI:
    backend = CoachBackend(config.db_path, config.engine_depth, config.open_engine)
    jobs = config.job_manager or JobManager()
    coach = CoachSessions(backend, config.anthropic_client, config.model, config.effort)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        jobs.shutdown()
        backend.close()

    app = FastAPI(title="Teachess", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        with backend.connection() as conn:
            games = repo.list_games(conn)
            users = repo.list_usernames(conn)
        return {
            "version": __version__,
            "stockfish": config.stockfish_configured,
            "engine_depth": config.engine_depth,
            "default_users": config.default_users,
            "users": users,
            "games": len(games),
            "games_analyzed": sum(g.analyzed_depth is not None for g in games),
            "coach": {
                "web_enabled": coach.enabled,
                "model": config.model,
                "mcp_command": MCP_COACH_COMMAND,
            },
        }

    # --- games and reports -------------------------------------------------------

    @app.get("/api/games")
    def games(
        user: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    ) -> dict[str, Any]:
        with backend.connection() as conn:
            stored_games = repo.list_games(conn, username=user)[:limit]
            rows = [serializers.game_row(g, load_game_report(conn, g.id)) for g in stored_games]
        return {"games": rows}

    @app.get("/api/games/{game_id}")
    def game(game_id: int) -> dict[str, Any]:
        with backend.connection() as conn:
            stored = repo.get_game(conn, game_id)
            if stored is None:
                raise HTTPException(404, f"No existe la partida {game_id}.")
            report = load_game_report(conn, game_id)
            analysis = repo.get_move_analysis(conn, game_id) if report else []
        try:
            return serializers.game_detail(stored, report, analysis)
        except ValueError:
            raise HTTPException(422, f"El PGN de la partida {game_id} no se puede leer.") from None

    @app.get("/api/users/{username}/report")
    def user_report(username: str) -> dict[str, Any]:
        with backend.connection() as conn:
            report = load_user_report(conn, username)
            usernames = repo.list_usernames(conn)
        return serializers.user_report(report, usernames)

    # --- background jobs -----------------------------------------------------------

    @app.post("/api/imports", status_code=202)
    def start_import(request: ImportRequest) -> dict[str, Any]:
        username = (request.user or "").strip() or config.default_users.get(request.platform)
        if not username:
            raise HTTPException(400, "Indica el usuario.")
        if request.platform == "pgn" and not (request.pgn or "").strip():
            raise HTTPException(400, "Pega o sube un PGN.")

        def run(progress: Progress) -> dict[str, Any]:
            result = import_games(
                config.db_path,
                config.http_client,
                request.platform,
                username,
                request.max_games,
                request.pgn,
                request.color,
                progress,
            )
            if request.analyze:
                pending = _pending_games(username)
                if pending:
                    try:
                        result["analysis"] = analyse_games(
                            config.db_path,
                            config.open_engine,
                            pending,
                            config.engine_depth,
                            progress,
                        )
                    except JobError as exc:  # the import itself did succeed
                        result["analysis_error"] = str(exc)
            return result

        return jobs.submit("import", run)

    @app.post("/api/analyses", status_code=202)
    def start_analysis(request: AnalysisRequest) -> dict[str, Any]:
        depth = request.depth or config.engine_depth
        with backend.connection() as conn:
            if request.game_id is not None:
                stored = repo.get_game(conn, request.game_id)
                if stored is None:
                    raise HTTPException(404, f"No existe la partida {request.game_id}.")
                targets = [stored]
            else:
                targets = repo.list_games(
                    conn, username=request.user, pending_only=not request.reanalyze
                )
        if not request.reanalyze:
            targets = [g for g in targets if g.analyzed_depth is None]
        if not targets:
            raise HTTPException(409, "No hay partidas pendientes de analizar.")
        ids = [g.id for g in targets]
        return jobs.submit(
            "analysis",
            lambda progress: analyse_games(
                config.db_path, config.open_engine, ids, depth, progress
            ),
        )

    def _pending_games(username: str) -> list[int]:
        with backend.connection() as conn:
            return [g.id for g in repo.list_games(conn, username=username, pending_only=True)]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        snapshot = jobs.get(job_id)
        if snapshot is None:
            raise HTTPException(404, "Tarea no encontrada.")
        return snapshot

    # --- engine --------------------------------------------------------------------

    @app.post("/api/engine/evaluate")
    def evaluate(request: EvaluateRequest) -> dict[str, Any]:
        return _engine_call(
            lambda: _with_engine(request.game_id, lambda t: t.evaluate_position(request.fen))
        )

    @app.post("/api/engine/move")
    def evaluate_move(request: MoveRequest) -> dict[str, Any]:
        return _engine_call(
            lambda: _with_engine(
                request.game_id, lambda t: t.evaluate_move(request.fen, request.move)
            )
        )

    def _with_engine(game_id: int | None, fn: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        with backend.engine_tools(game_id) as tools:
            return fn(tools)

    # --- coach (paid API, opt-in) -------------------------------------------------

    @app.post("/api/coach/sessions", status_code=201)
    def create_coach_session(request: CoachSessionRequest) -> dict[str, Any]:
        try:
            return {"session_id": coach.create(request.game_id)}
        except CoachUnavailableError:
            raise HTTPException(
                403,
                "El coach web usa la API de pago de Anthropic y no está activado "
                "(falta ANTHROPIC_API_KEY). Úsalo gratis desde Claude Code con "
                f"{MCP_COACH_COMMAND} {request.game_id}.",
            ) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/coach/sessions/{session_id}/messages")
    def coach_message(
        session_id: str, message: Annotated[CoachMessage, Body()]
    ) -> StreamingResponse:
        try:
            stream = coach.ask(session_id, message.text.strip())
        except SessionNotFoundError:
            raise HTTPException(404, "La sesión del coach ha caducado; abre una nueva.") from None
        except SessionBusyError:
            raise HTTPException(409, "El coach todavía está respondiendo.") from None
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str) -> JSONResponse:
        return JSONResponse({"detail": f"Ruta de la API desconocida: /api/{path}"}, 404)

    _mount_web(app, config.static_dir)
    return app


def _engine_call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except ToolInputError as exc:
        raise HTTPException(400, str(exc)) from None
    except RuntimeError as exc:  # Stockfish missing or crashed
        raise HTTPException(503, str(exc)) from None


def _mount_web(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the compiled single-page app; unknown paths fall back to index.html."""
    index = static_dir / "index.html" if static_dir else None

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if static_dir is None or index is None or not index.is_file():
            raise HTTPException(
                404,
                "La web no está compilada. Ejecuta: cd web && npm install && npm run build",
            )
        root = static_dir.resolve()
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
