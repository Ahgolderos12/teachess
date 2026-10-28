"""Per-move analysis of a game: centipawn loss, classification, phase and clock."""

import sqlite3

import chess
import chess.pgn

from teachess.db import repository as repo
from teachess.engine.models import Classification, Engine, MoveAnalysis, Phase, PositionEval

# Evaluations are clamped so that moves in already-decided positions are not over-penalised;
# forced mates count as a fully decided position.
EVAL_CLAMP_CP = 1000

INACCURACY_CP = 50
MISTAKE_CP = 100
BLUNDER_CP = 300

OPENING_LAST_FULLMOVE = 10
ENDGAME_MAX_PIECE_MATERIAL = 13  # per side, excluding pawns and king
_PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


class PersistentCacheEngine:
    """Engine decorator that stores evaluations in SQLite, keyed by (FEN, depth)."""

    def __init__(self, inner: Engine, conn: sqlite3.Connection):
        self._inner = inner
        self._conn = conn

    def analyse(self, board: chess.Board, depth: int) -> PositionEval:
        fen = board.fen()
        cached = repo.get_position_eval(self._conn, fen, depth)
        if cached is not None:
            return cached
        result = self._inner.analyse(board, depth)
        repo.put_position_eval(self._conn, fen, depth, result)
        return result


def analyse_game(game: chess.pgn.Game, engine: Engine, depth: int) -> list[MoveAnalysis]:
    """Analyse every mainline move. Each position is evaluated once."""
    board = game.board()
    before = engine.analyse(board, depth)
    moves: list[MoveAnalysis] = []
    for ply, node in enumerate(game.mainline(), start=1):
        move = node.move
        mover = board.turn
        fen_before = board.fen()
        san = board.san(move)
        best_san = _legal_san(board, before.best_move)
        phase = game_phase(board)

        board.push(move)
        after = engine.analyse(board, depth)
        loss = 0 if move.uci() == before.best_move else cp_loss(before, after, mover)
        moves.append(
            MoveAnalysis(
                ply=ply,
                san=san,
                uci=move.uci(),
                fen_before=fen_before,
                eval_before=before,
                eval_after=after,
                best_move_san=best_san,
                cp_loss=loss,
                classification=classify(loss),
                phase=phase,
                clock_seconds=node.clock(),
            )
        )
        before = after
    return moves


def white_cp(evaluation: PositionEval) -> int:
    """Clamped score in centipawns from White's point of view."""
    if evaluation.mate is not None:
        return EVAL_CLAMP_CP if evaluation.mate > 0 else -EVAL_CLAMP_CP
    cp = evaluation.cp or 0
    return max(-EVAL_CLAMP_CP, min(EVAL_CLAMP_CP, cp))


def cp_loss(before: PositionEval, after: PositionEval, mover: chess.Color) -> int:
    sign = 1 if mover == chess.WHITE else -1
    return max(0, (white_cp(before) - white_cp(after)) * sign)


def classify(loss: int) -> Classification:
    if loss >= BLUNDER_CP:
        return "blunder"
    if loss >= MISTAKE_CP:
        return "mistake"
    if loss >= INACCURACY_CP:
        return "inaccuracy"
    return "ok"


def game_phase(board: chess.Board) -> Phase:
    """Simple heuristic: endgame by remaining piece material, opening by move number."""
    material = [
        sum(len(board.pieces(piece, color)) * value for piece, value in _PIECE_VALUES.items())
        for color in chess.COLORS
    ]
    if max(material) <= ENDGAME_MAX_PIECE_MATERIAL:
        return "endgame"
    if board.fullmove_number <= OPENING_LAST_FULLMOVE:
        return "opening"
    return "middlegame"


def _legal_san(board: chess.Board, uci: str | None) -> str | None:
    """SAN of an engine move, or None if it is missing or not legal here."""
    if uci is None:
        return None
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return board.san(move) if board.is_legal(move) else None
