"""Terminal rendering of reports (Spanish)."""

from rich.console import Console
from rich.table import Table

from teachess.engine.models import Classification, Phase, PositionEval
from teachess.ingest.models import ImportedGame
from teachess.report.builder import (
    ERROR_CLASSES,
    PHASES,
    GameReport,
    UserReport,
    best_line_san,
    move_label,
)

CLASS_LABELS: dict[Classification, str] = {
    "ok": "correcta",
    "inaccuracy": "imprecisión",
    "mistake": "error",
    "blunder": "error grave",
}
CLASS_STYLES: dict[Classification, str] = {
    "ok": "",
    "inaccuracy": "yellow",
    "mistake": "dark_orange",
    "blunder": "bold red",
}
PHASE_LABELS: dict[Phase, str] = {
    "opening": "apertura",
    "middlegame": "medio juego",
    "endgame": "final",
}
PLATFORM_LABELS = {"chesscom": "Chess.com", "lichess": "Lichess", "pgn": "PGN"}


def format_eval(evaluation: PositionEval) -> str:
    """White's point of view: '+0.35', '-1.20', '#3', '#-2'."""
    if evaluation.mate is not None:
        return f"#{evaluation.mate}"
    cp = evaluation.cp or 0
    if abs(cp) >= 100_000:  # checkmate already on the board
        return "1-0" if cp > 0 else "0-1"
    return f"{cp / 100:+.2f}"


def render_game_report(report: GameReport, console: Console) -> None:
    game = report.stored.game
    console.print(f"[bold]Partida #{report.stored.id}[/bold] · {_game_summary(game)}")
    if game.url:
        console.print(game.url, style="dim")
    console.print(_summary_line(report.acpl, report.counts))

    if not report.mistakes:
        console.print("Sin imprecisiones ni errores según el motor.", style="green")
        return

    table = Table(title="Tus imprecisiones y errores (evaluación desde blancas)")
    for column in ("Jugada", "Jugaste", "Mejor", "Antes", "Después", "Pérdida", "Tipo", "Fase"):
        table.add_column(column)
    table.add_column("Línea del motor", style="dim")
    for m in report.mistakes:
        table.add_row(
            move_label(m),
            m.san,
            m.best_move_san or "—",
            format_eval(m.eval_before),
            format_eval(m.eval_after),
            str(m.cp_loss),
            f"[{CLASS_STYLES[m.classification]}]{CLASS_LABELS[m.classification]}[/]",
            PHASE_LABELS[m.phase],
            best_line_san(m),
        )
    console.print(table)


def render_user_report(report: UserReport, console: Console) -> None:
    console.print(
        f"[bold]Informe de {report.username}[/bold]: {len(report.games)} partidas analizadas"
        + (f" ({report.pending} pendientes de analizar)" if report.pending else "")
    )
    if not report.games:
        console.print("No hay partidas analizadas. Ejecuta primero `teachess analyze`.")
        return
    console.print(_summary_line(report.acpl, report.counts))

    phases = Table(title="Errores por fase")
    phases.add_column("Fase")
    for cls in ERROR_CLASSES:
        phases.add_column(CLASS_LABELS[cls].capitalize(), justify="right")
    for phase in PHASES:
        counts = report.by_phase[phase]
        phases.add_row(PHASE_LABELS[phase], *(str(counts[cls]) for cls in ERROR_CLASSES))
    console.print(phases)

    worst = report.worst_games()
    if worst:
        table = Table(title="Partidas con más errores")
        for column in ("ID", "Rival", "Resultado", "Fecha", "Graves", "Errores", "ACPL"):
            table.add_column(column)
        for g in worst:
            game = g.stored.game
            table.add_row(
                str(g.stored.id),
                _opponent(game),
                _user_result(game),
                (game.played_at or "?")[:10],
                str(g.counts["blunder"]),
                str(g.counts["mistake"]),
                _format_acpl(g.acpl),
            )
        console.print(table)
        console.print("Detalle de una partida: `teachess report --game ID`", style="dim")


def _summary_line(acpl: float | None, counts: dict[Classification, int]) -> str:
    parts = [f"{counts.get(cls, 0)} {CLASS_LABELS[cls]}" for cls in reversed(ERROR_CLASSES)]
    return f"ACPL: {_format_acpl(acpl)} · " + ", ".join(parts)


def _format_acpl(acpl: float | None) -> str:
    return "—" if acpl is None else f"{acpl:.0f}"


def _game_summary(game: ImportedGame) -> str:
    color = "blancas" if game.user_color == "white" else "negras"
    date = (game.played_at or "fecha desconocida")[:10]
    return (
        f"{game.white} vs {game.black} · {game.result} · juegas con {color} · {date} · "
        f"{PLATFORM_LABELS.get(game.platform, game.platform)}"
    )


def _opponent(game: ImportedGame) -> str:
    return game.black if game.user_color == "white" else game.white


def _user_result(game: ImportedGame) -> str:
    if game.result == "1/2-1/2":
        return "tablas"
    won = "1-0" if game.user_color == "white" else "0-1"
    if game.result == won:
        return "victoria"
    return "derrota" if game.result in ("1-0", "0-1") else "?"
