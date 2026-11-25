"""JSON shapes the web consumes. Chess facts come from stored analysis, never computed here."""

import io
from typing import Any, Literal

import chess
import chess.pgn

from teachess.db.repository import StoredGame
from teachess.engine.models import MoveAnalysis, PositionEval
from teachess.engine.scoring import win_percent
from teachess.report.builder import (
    ERROR_CLASSES,
    PHASES,
    GameReport,
    UserReport,
    best_line_san,
    format_eval,
    move_label,
    opening_name,
)

UserResult = Literal["win", "loss", "draw", "unknown"]
LINE_PLIES = 5


def user_result(stored: StoredGame) -> UserResult:
    result = stored.game.result
    if result == "1/2-1/2":
        return "draw"
    if result not in ("1-0", "0-1"):
        return "unknown"
    won = "1-0" if stored.game.user_color == "white" else "0-1"
    return "win" if result == won else "loss"


def game_row(stored: StoredGame, report: GameReport | None) -> dict[str, Any]:
    game = stored.game
    return {
        "id": stored.id,
        "platform": game.platform,
        "username": game.username,
        "white": game.white,
        "black": game.black,
        "opponent": game.black if game.user_color == "white" else game.white,
        "user_color": game.user_color,
        "result": game.result,
        "user_result": user_result(stored),
        "played_at": game.played_at,
        "time_control": game.time_control,
        "url": game.url,
        "opening": opening_name(game.pgn),
        "analyzed_depth": stored.analyzed_depth,
        "summary": _summary(report),
    }


def _summary(report: GameReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "acpl": None if report.acpl is None else round(report.acpl, 1),
        "counts": {cls: report.counts[cls] for cls in ERROR_CLASSES},
        "user_moves": len(report.user_moves),
    }


def game_detail(
    stored: StoredGame, report: GameReport | None, analysis: list[MoveAnalysis]
) -> dict[str, Any]:
    """Full game for the viewer. Unanalysed games still get their moves from the PGN."""
    parsed = chess.pgn.read_game(io.StringIO(stored.game.pgn))
    if parsed is None:
        raise ValueError("PGN ilegible")
    start_fen = parsed.board().fen()
    by_ply = {m.ply: m for m in analysis}
    user_turn = chess.WHITE if stored.game.user_color == "white" else chess.BLACK
    moves = []
    board = parsed.board()
    for ply, node in enumerate(parsed.mainline(), start=1):
        fen_before = board.fen()
        turn = board.turn
        san = board.san(node.move)
        board.push(node.move)
        entry: dict[str, Any] = {
            "ply": ply,
            "move_number": chess.Board(fen_before).fullmove_number,
            "color": "white" if turn == chess.WHITE else "black",
            "by_user": turn == user_turn,
            "san": san,
            "uci": node.move.uci(),
            "fen_before": fen_before,
            "fen_after": board.fen(),
            "clock_seconds": node.clock(),
            "analysis": None,
        }
        analysed = by_ply.get(ply)
        if analysed is not None and analysed.uci == node.move.uci():
            entry["label"] = move_label(analysed)
            entry["analysis"] = _move_analysis(analysed)
        else:
            entry["label"] = f"{entry['move_number']}{'.' if turn == chess.WHITE else '...'}"
        moves.append(entry)

    first = by_ply.get(1)
    return {
        **game_row(stored, report),
        "start_fen": start_fen,
        "start_eval": _eval(first.eval_before) if first else None,
        "moves": moves,
    }


def _move_analysis(m: MoveAnalysis) -> dict[str, Any]:
    return {
        "eval_before": _eval(m.eval_before),
        "eval_after": _eval(m.eval_after),
        "best_move_san": m.best_move_san,
        "best_move_uci": m.eval_before.best_move,
        "engine_line": best_line_san(m, LINE_PLIES),
        "win_loss": round(m.win_loss, 1),
        "cp_loss": m.cp_loss,
        "classification": m.classification,
        "phase": m.phase,
    }


def _eval(evaluation: PositionEval) -> dict[str, Any]:
    return {
        "text": format_eval(evaluation),
        "cp": evaluation.cp,
        "mate": evaluation.mate,
        "white_win_pct": round(win_percent(evaluation), 1),
        "depth": evaluation.depth,
    }


def user_report(report: UserReport, usernames: list[str]) -> dict[str, Any]:
    return {
        "username": report.username,
        "known_user": report.username.lower() in {u.lower() for u in usernames},
        "games_analyzed": len(report.games),
        "games_pending": report.pending,
        "acpl": None if report.acpl is None else round(report.acpl, 1),
        "counts": {cls: report.counts[cls] for cls in ERROR_CLASSES},
        "by_phase": {
            phase: {cls: report.by_phase[phase][cls] for cls in ERROR_CLASSES} for phase in PHASES
        },
        "results": _results(report),
        "worst_games": [game_row(g.stored, g) for g in report.worst_games(limit=10)],
    }


def _results(report: UserReport) -> dict[UserResult, int]:
    totals: dict[UserResult, int] = {"win": 0, "loss": 0, "draw": 0, "unknown": 0}
    for game in report.games:
        totals[user_result(game.stored)] += 1
    return totals
