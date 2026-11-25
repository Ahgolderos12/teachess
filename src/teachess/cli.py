"""Command-line entry point."""

import io
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import anthropic
import chess.pgn
import httpx
import typer
from rich.console import Console
from rich.progress import track

from teachess import __version__
from teachess.coach.agent import Coach, CoachConfig, CoachReply
from teachess.coach.mcp_server import CoachBackend, build_server
from teachess.coach.prompts import game_context
from teachess.coach.tools import CoachToolbox
from teachess.config import Settings, SettingsError, load_settings
from teachess.db import repository as repo
from teachess.db.repository import StoredGame
from teachess.engine.analysis import PersistentCacheEngine, analyse_game
from teachess.engine.models import Engine
from teachess.engine.stockfish import StockfishEngine, StockfishNotConfiguredError
from teachess.ingest import chesscom, http, lichess
from teachess.ingest.pgn_file import FetchResult, load_pgn_file
from teachess.report.builder import load_game_report, load_user_report
from teachess.report.render import render_game_report, render_user_report

app = typer.Typer(
    help="Teachess: entrenador de ajedrez que aprende del jugador.",
    no_args_is_help=True,
)


class PlatformOption(StrEnum):
    chesscom = "chesscom"
    lichess = "lichess"
    pgn = "pgn"


class ColorOption(StrEnum):
    white = "white"
    black = "black"


# Factories for external resources; tests replace them.
def _http_client() -> httpx.Client:
    return http.make_client()


def _open_engine(settings: Settings) -> AbstractContextManager[Engine]:
    return StockfishEngine(settings.stockfish_path)


def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Muestra la versión."
        ),
    ] = False,
) -> None:
    """Teachess: entrenador de ajedrez que aprende del jugador."""


@app.command("import")
def import_games(
    platform: Annotated[PlatformOption, typer.Option(help="Origen de las partidas.")],
    user: Annotated[
        str | None,
        typer.Option(help="Tu usuario (por defecto, CHESSCOM_USER o LICHESS_USER)."),
    ] = None,
    file: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False, help="Archivo PGN (con pgn).")
    ] = None,
    color: Annotated[
        ColorOption | None,
        typer.Option(help="Tu color en el PGN si tu nombre no aparece en él."),
    ] = None,
    max_games: Annotated[int, typer.Option(min=1, help="Máximo de partidas a descargar.")] = 50,
) -> None:
    """Importa partidas de Chess.com, Lichess o un archivo PGN."""
    settings = load_settings()
    username = user or _default_user(platform, settings)
    if username is None:
        _fail("Indica el usuario con --user.")

    try:
        if platform is PlatformOption.pgn:
            if file is None:
                _fail("Indica el archivo con --file.")
            fetched = load_pgn_file(file, username, color.value if color else None)
        else:
            fetcher = chesscom if platform is PlatformOption.chesscom else lichess
            with _http_client() as client:
                fetched = fetcher.fetch_games(client, username, max_games)
    except http.IngestError as exc:
        _fail(str(exc))
    except (OSError, UnicodeDecodeError) as exc:
        _fail(f"No se pudo leer el archivo PGN: {exc}")

    with closing(repo.connect(settings.db_path)) as conn:
        _store(conn, fetched)


def _default_user(platform: PlatformOption, settings: Settings) -> str | None:
    if platform is PlatformOption.chesscom:
        return settings.chesscom_user
    if platform is PlatformOption.lichess:
        return settings.lichess_user
    return None


def _store(conn: sqlite3.Connection, fetched: FetchResult) -> None:
    new = sum(repo.insert_game(conn, game) for game in fetched.games)
    typer.echo(
        f"Partidas nuevas: {new} · ya importadas: {len(fetched.games) - new} · "
        f"descartadas: {fetched.skipped} (no estándar, inválidas o sin tu participación)."
    )


@app.command()
def analyze(
    game: Annotated[int | None, typer.Option(help="ID de una partida.")] = None,
    user: Annotated[str | None, typer.Option(help="Analiza las partidas de este usuario.")] = None,
    depth: Annotated[
        int | None, typer.Option(min=1, help="Profundidad de Stockfish (TEACHESS_DEPTH).")
    ] = None,
    reanalyze: Annotated[
        bool, typer.Option(help="Vuelve a analizar partidas ya analizadas.")
    ] = False,
) -> None:
    """Analiza partidas importadas con Stockfish."""
    _require_one(game, user)
    settings = load_settings()
    search_depth = depth or settings.engine_depth

    with closing(repo.connect(settings.db_path)) as conn:
        games = _games_to_analyse(conn, game, user, reanalyze)
        if not games:
            typer.echo("No hay partidas pendientes de analizar.")
            return
        try:
            with _open_engine(settings) as stockfish:
                engine = PersistentCacheEngine(stockfish, conn)
                for stored in track(games, description="Analizando…"):
                    parsed = chess.pgn.read_game(io.StringIO(stored.game.pgn))
                    if parsed is None:
                        continue
                    moves = analyse_game(parsed, engine, search_depth)
                    repo.save_move_analysis(conn, stored.id, moves, search_depth)
        except StockfishNotConfiguredError as exc:
            _fail(str(exc))
    typer.echo(f"Partidas analizadas: {len(games)} (profundidad {search_depth}).")


def _games_to_analyse(
    conn: sqlite3.Connection, game_id: int | None, user: str | None, reanalyze: bool
) -> list[StoredGame]:
    if game_id is None:
        return repo.list_games(conn, username=user, pending_only=not reanalyze)
    stored = repo.get_game(conn, game_id)
    if stored is None:
        _fail(f"No existe la partida {game_id}.")
    if stored.analyzed_depth is not None and not reanalyze:
        typer.echo(
            f"La partida {game_id} ya está analizada (profundidad {stored.analyzed_depth}); "
            "usa --reanalyze para repetir."
        )
        return []
    return [stored]


@app.command()
def report(
    game: Annotated[int | None, typer.Option(help="ID de una partida.")] = None,
    user: Annotated[str | None, typer.Option(help="Informe global de este usuario.")] = None,
) -> None:
    """Muestra el informe de errores de una partida o de un usuario."""
    _require_one(game, user)
    console = Console()
    with closing(repo.connect(load_settings().db_path)) as conn:
        if game is not None:
            game_report = load_game_report(conn, game)
            if game_report is None:
                _fail(f"La partida {game} no existe o no está analizada.")
            render_game_report(game_report, console)
        else:
            assert user is not None
            render_user_report(load_user_report(conn, user), console)


TOOL_LABELS = {
    "get_game_summary": "resumen de la partida",
    "get_critical_moments": "momentos críticos",
    "get_move": "jugada de la partida",
    "evaluate_position": "Stockfish: posición",
    "evaluate_move": "Stockfish: jugada",
}
EXIT_WORDS = {"salir", "exit", "quit"}


@app.command()
def coach(
    game: Annotated[int, typer.Option(help="ID de una partida ya analizada.")],
) -> None:
    """Conversa con el coach (Claude) sobre una partida analizada."""
    try:
        settings = load_settings()
    except SettingsError as exc:
        _fail(str(exc))
    console = Console()
    with closing(repo.connect(settings.db_path)) as conn:
        game_report = load_game_report(conn, game)
        if game_report is None:
            _fail(f"La partida {game} no existe o no está analizada.")
        # Same depth as the stored analysis, so the game's positions come from the cache.
        depth = game_report.stored.analyzed_depth or settings.engine_depth
        try:
            with _open_engine(settings) as stockfish:
                toolbox = CoachToolbox(
                    game_report,
                    repo.get_move_analysis(conn, game),
                    PersistentCacheEngine(stockfish, conn),
                    depth,
                )
                context = game_context(
                    toolbox.game_summary(), toolbox.critical_moments("inaccuracy")
                )
                session = Coach(
                    _anthropic_client(),
                    toolbox,
                    CoachConfig(model=settings.model, effort=settings.effort),
                    context,
                )
                game_info = game_report.stored.game
                console.print(
                    f"[bold]Coach de Teachess[/bold] · partida #{game}: "
                    f"{game_info.white} vs {game_info.black} · modelo {settings.model}"
                )
                console.print("Escribe tu pregunta (`salir` para terminar).", style="dim")
                _chat(session, console)
        except StockfishNotConfiguredError as exc:
            _fail(str(exc))
    usage = session.usage
    console.print(
        f"Tokens: entrada {usage.input_tokens} (caché {usage.cache_read_tokens}), "
        f"salida {usage.output_tokens}.",
        style="dim",
    )


@app.command("mcp")
def mcp_server() -> None:
    """Servidor MCP (stdio) con las herramientas del coach, para usarlo desde Claude Code."""
    try:
        settings = load_settings()
    except SettingsError as exc:
        _fail(str(exc))
    # stdout belongs to the MCP protocol: nothing else may be printed there.
    backend = CoachBackend(settings.db_path, settings.engine_depth, lambda: _open_engine(settings))
    try:
        build_server(backend).run("stdio")
    finally:
        backend.close()


def _chat(session: Coach, console: Console) -> None:
    def show_text(text: str) -> None:
        console.print(text, end="", markup=False, highlight=False, soft_wrap=True)

    def show_tool(name: str) -> None:
        console.print(f"\n· consultando {TOOL_LABELS.get(name, name)}…", style="dim", end="")

    while True:
        try:
            question = console.input("\n[bold]Tú:[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            return
        console.print("\n[bold green]Coach:[/bold green] ", end="")
        reply = _ask(session, question, show_text, show_tool, console)
        console.print()
        if reply is not None:
            _show_reply_notes(reply, console)


def _ask(
    session: Coach,
    question: str,
    show_text: Callable[[str], None],
    show_tool: Callable[[str], None],
    console: Console,
) -> CoachReply | None:
    """One coach turn. Recoverable API errors are shown and the chat goes on."""
    try:
        return session.ask(question, on_text=show_text, on_tool=show_tool)
    except anthropic.AuthenticationError:
        _fail("\nLa clave de Anthropic no es válida. Revisa ANTHROPIC_API_KEY en el archivo .env.")
    except TypeError as exc:
        if "authentication" not in str(exc):
            raise
        _fail("\nFalta la clave de Anthropic: configura ANTHROPIC_API_KEY en el archivo .env.")
    except anthropic.RateLimitError:
        console.print("\nDemasiadas peticiones seguidas; espera un poco y repite.", style="yellow")
    except anthropic.APIConnectionError:
        console.print("\nNo hay conexión con la API de Anthropic.", style="yellow")
    except anthropic.APIStatusError as exc:
        console.print(f"\nError de la API de Anthropic ({exc.status_code}).", style="yellow")
    return None


def _show_reply_notes(reply: CoachReply, console: Console) -> None:
    if reply.refused:
        console.print(
            "El modelo no ha respondido a esta pregunta. Prueba a reformularla.", style="yellow"
        )
    elif reply.truncated:
        console.print("(Respuesta cortada por longitud; pide que continúe.)", style="dim")


def _require_one(game: int | None, user: str | None) -> None:
    if (game is None) == (user is None):
        _fail("Indica --game o --user (solo uno).")


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)
