"""Coach tools: chess facts from the database and Stockfish, never from the LLM.

Handlers are plain Python and know nothing about the LLM. Every FEN and move is validated
with python-chess; invalid input raises ToolInputError, which the agent reports back to the
model as an error result so it can correct itself.
"""

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import chess
import chess.pgn

from teachess.engine.models import Classification, Engine, MoveAnalysis
from teachess.engine.scoring import classify, cp_loss, win_loss, win_percent
from teachess.report.builder import (
    GameReport,
    best_line_san,
    format_eval,
    line_san,
    move_label,
    mover,
)

MAX_LINE_PLIES = 5  # explanations use short lines, not long engine variations

LEVELS: tuple[Classification, ...] = ("inaccuracy", "mistake", "blunder")
_LEVEL_RANK: dict[str, int] = {level: rank for rank, level in enumerate(LEVELS)}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_game_summary",
        "description": (
            "Datos generales de la partida de esta sesión: jugadores, color del usuario, "
            "resultado, fecha, ritmo, apertura, ACPL y recuento de errores del usuario."
        ),
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_critical_moments",
        "description": (
            "Jugadas del usuario clasificadas por el motor como imprecisión, error o error "
            "grave (desde el nivel mínimo indicado), con la mejor jugada, evaluaciones, pérdida "
            "de probabilidad de victoria y una línea corta del motor."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "min_level": {
                    "type": "string",
                    "enum": list(LEVELS),
                    "description": "Nivel mínimo: inaccuracy, mistake o blunder.",
                }
            },
            "required": ["min_level"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_move",
        "description": (
            "Análisis del motor de una jugada concreta de la partida (del usuario o del rival): "
            "FEN previa, mejor jugada, evaluaciones antes y después, pérdida y línea corta."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "move_number": {"type": "integer", "description": "Número de jugada (1, 2, …)."},
                "color": {"type": "string", "enum": ["white", "black"]},
            },
            "required": ["move_number", "color"],
            "additionalProperties": False,
        },
    },
    {
        "name": "evaluate_position",
        "description": (
            "Evalúa con Stockfish una posición dada en FEN: evaluación, probabilidad de victoria "
            "de las blancas, mejor jugada y línea corta."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"fen": {"type": "string", "description": "Posición en FEN."}},
            "required": ["fen"],
            "additionalProperties": False,
        },
    },
    {
        "name": "evaluate_move",
        "description": (
            "Evalúa con Stockfish una jugada hipotética en una posición (preguntas del tipo "
            "«¿y si hubiera jugado…?»): evaluación tras la jugada, comparación con la mejor, "
            "clasificación y la mejor respuesta del rival."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "fen": {"type": "string", "description": "Posición en FEN antes de la jugada."},
                "move": {"type": "string", "description": "Jugada en SAN (Nf3) o UCI (g1f3)."},
            },
            "required": ["fen", "move"],
            "additionalProperties": False,
        },
    },
]


class ToolInputError(ValueError):
    """Invalid tool input; the message is shown to the model so it can correct itself."""


@dataclass(frozen=True)
class ToolResult:
    content: str  # JSON
    is_error: bool = False


class CoachToolbox:
    """Tools bound to one analysed game."""

    def __init__(self, report: GameReport, moves: list[MoveAnalysis], engine: Engine, depth: int):
        self._report = report
        self._moves = moves
        self._engine = engine
        self._depth = depth
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_game_summary": lambda _: self.game_summary(),
            "get_critical_moments": lambda args: self.critical_moments(args["min_level"]),
            "get_move": lambda args: self.move(args["move_number"], args["color"]),
            "evaluate_position": lambda args: self.evaluate_position(args["fen"]),
            "evaluate_move": lambda args: self.evaluate_move(args["fen"], args["move"]),
        }

    def run(self, name: str, arguments: object) -> ToolResult:
        """Execute a tool call coming from the model. Never raises for bad input."""
        handler = self._handlers.get(name)
        if handler is None:
            return _error(f"Herramienta desconocida: {name}.")
        if not isinstance(arguments, dict):
            return _error("La entrada de la herramienta debe ser un objeto JSON.")
        try:
            return ToolResult(json.dumps(handler(arguments), ensure_ascii=False))
        except KeyError as exc:
            return _error(f"Falta el campo obligatorio {exc}.")
        except ToolInputError as exc:
            return _error(str(exc))

    # --- game data -----------------------------------------------------------

    def game_summary(self) -> dict[str, Any]:
        stored = self._report.stored
        game = stored.game
        counts = self._report.counts
        return {
            "white": game.white,
            "black": game.black,
            "user_color": game.user_color,
            "result": game.result,
            "played_at": game.played_at,
            "time_control": game.time_control,
            "platform": game.platform,
            "opening": _opening(game.pgn),
            "user_moves": len(self._report.user_moves),
            "user_acpl": None if self._report.acpl is None else round(self._report.acpl),
            "user_mistakes": {level: counts[level] for level in LEVELS},
            "analysis_depth": stored.analyzed_depth,
        }

    def critical_moments(self, min_level: str) -> dict[str, Any]:
        threshold = _LEVEL_RANK.get(min_level)
        if threshold is None:
            raise ToolInputError(f"min_level debe ser uno de: {', '.join(LEVELS)}.")
        moments = [
            self._describe(m)
            for m in self._report.mistakes
            if _LEVEL_RANK[m.classification] >= threshold
        ]
        return {"min_level": min_level, "moments": moments}

    def move(self, move_number: int, color: str) -> dict[str, Any]:
        if color not in ("white", "black"):
            raise ToolInputError("color debe ser white o black.")
        if not isinstance(move_number, int) or move_number < 1:
            raise ToolInputError("move_number debe ser un entero positivo.")
        ply = (move_number - 1) * 2 + (1 if color == "white" else 2)
        found = next((m for m in self._moves if m.ply == ply), None)
        if found is None:
            last = self._moves[-1] if self._moves else None
            limit = move_label(last) + last.san if last else "ninguna"
            raise ToolInputError(f"Esa jugada no existe en la partida (última: {limit}).")
        return self._describe(found)

    def _describe(self, m: MoveAnalysis) -> dict[str, Any]:
        user_turn = chess.WHITE if self._report.stored.game.user_color == "white" else chess.BLACK
        return {
            "move": f"{move_label(m)}{m.san}",
            "played_by": "user" if mover(m) == user_turn else "opponent",
            "fen_before": m.fen_before,
            "best_move": m.best_move_san,
            "eval_before": format_eval(m.eval_before),
            "eval_after": format_eval(m.eval_after),
            "win_loss_pct": round(m.win_loss, 1),
            "cp_loss": m.cp_loss,
            "classification": m.classification,
            "phase": m.phase,
            "engine_line": best_line_san(m, MAX_LINE_PLIES),
            "clock_seconds": m.clock_seconds,
        }

    # --- engine queries ----------------------------------------------------------

    def evaluate_position(self, fen: str) -> dict[str, Any]:
        board = _parse_fen(fen)
        result: dict[str, Any] = {"fen": board.fen(), "side_to_move": _color(board.turn)}
        if board.is_game_over():
            outcome = board.outcome()
            assert outcome is not None
            return {**result, "game_over": True, "result": outcome.result()}
        evaluation = self._engine.analyse(board, self._depth)
        best = chess.Move.from_uci(evaluation.best_move) if evaluation.best_move else None
        return {
            **result,
            "eval": format_eval(evaluation),
            "white_win_pct": round(win_percent(evaluation), 1),
            "best_move": board.san(best) if best and board.is_legal(best) else None,
            "engine_line": line_san(board.fen(), evaluation.pv, MAX_LINE_PLIES),
            "depth": evaluation.depth,
        }

    def evaluate_move(self, fen: str, move_text: str) -> dict[str, Any]:
        board = _parse_fen(fen)
        if board.is_game_over():
            raise ToolInputError("La partida ya ha terminado en esa posición.")
        move = _parse_move(board, move_text)
        before = self._engine.analyse(board, self._depth)
        played_best = move.uci() == before.best_move
        san = board.san(move)
        best = chess.Move.from_uci(before.best_move) if before.best_move else None
        best_san = board.san(best) if best and board.is_legal(best) else None
        mover_color = board.turn
        board.push(move)
        after = self._engine.analyse(board, self._depth)
        drop = 0.0 if played_best else win_loss(before, after, mover_color)
        return {
            "move": san,
            "best_move": best_san,
            "is_best": played_best,
            "eval_before": format_eval(before),
            "eval_after": format_eval(after),
            "win_loss_pct": round(drop, 1),
            "cp_loss": 0 if played_best else cp_loss(before, after, mover_color),
            "classification": classify(drop),
            "best_reply_line": line_san(board.fen(), after.pv, MAX_LINE_PLIES),
            "depth": after.depth,
        }


def _error(message: str) -> ToolResult:
    return ToolResult(json.dumps({"error": message}, ensure_ascii=False), is_error=True)


def _parse_fen(fen: str) -> chess.Board:
    if not isinstance(fen, str):
        raise ToolInputError("fen debe ser un texto.")
    try:
        board = chess.Board(fen.strip())
    except ValueError as exc:
        raise ToolInputError(f"FEN no válido: {exc}.") from None
    if not board.is_valid():
        raise ToolInputError(f"La posición no es legal ({board.status()!r}).")
    return board


def _parse_move(board: chess.Board, text: str) -> chess.Move:
    if not isinstance(text, str) or not text.strip():
        raise ToolInputError("move debe ser una jugada en SAN o UCI.")
    text = text.strip()
    try:
        return board.parse_san(text)
    except ValueError:
        pass
    try:
        move = chess.Move.from_uci(text)
    except ValueError:
        move = None
    if move is not None and board.is_legal(move):
        return move
    legal = ", ".join(board.san(m) for m in board.legal_moves)
    raise ToolInputError(f"Jugada ilegal o ambigua: {text}. Jugadas legales: {legal}.")


def _color(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _opening(pgn: str) -> str | None:
    headers = chess.pgn.read_headers(io.StringIO(pgn))
    if headers is None:
        return None
    name = headers.get("Opening")
    if name:
        return name
    eco_url = headers.get("ECOUrl", "")  # Chess.com: .../openings/Sicilian-Defense-...
    if "/openings/" in eco_url:
        return eco_url.rsplit("/openings/", 1)[1].replace("-", " ")
    return headers.get("ECO")
