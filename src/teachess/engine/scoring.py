"""Pure scoring of moves: centipawn loss, win probability and classification.

No database or engine dependencies, so schema migrations can reuse it to rescore stored rows.
"""

import math

import chess

from teachess.engine.models import CHECKMATE_CP, Classification, PositionEval

# Evaluations are clamped so that moves in already-decided positions are not over-penalised;
# forced mates count as a fully decided position. Used for the centipawn loss (ACPL).
EVAL_CLAMP_CP = 1000

# Classification by drop in win probability (percentage points), as Lichess does.
INACCURACY_WIN = 10.0
MISTAKE_WIN = 20.0
BLUNDER_WIN = 30.0

# Lichess win-probability model: https://lichess.org/page/accuracy
_WIN_K = 0.00368208


def white_cp(evaluation: PositionEval) -> int:
    """Clamped score in centipawns from White's point of view."""
    if evaluation.mate is not None:
        return EVAL_CLAMP_CP if evaluation.mate > 0 else -EVAL_CLAMP_CP
    cp = evaluation.cp or 0
    return max(-EVAL_CLAMP_CP, min(EVAL_CLAMP_CP, cp))


def cp_loss(before: PositionEval, after: PositionEval, mover: chess.Color) -> int:
    sign = 1 if mover == chess.WHITE else -1
    return max(0, (white_cp(before) - white_cp(after)) * sign)


def win_percent(evaluation: PositionEval) -> float:
    """White's chance of winning (0-100). A forced or delivered mate is 0 or 100."""
    if evaluation.mate is not None:
        return 100.0 if evaluation.mate > 0 else 0.0
    cp = evaluation.cp or 0
    if abs(cp) >= CHECKMATE_CP:
        return 100.0 if cp > 0 else 0.0
    cp = max(-EVAL_CLAMP_CP, min(EVAL_CLAMP_CP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-_WIN_K * cp)) - 1)


def win_loss(before: PositionEval, after: PositionEval, mover: chess.Color) -> float:
    """Drop in the mover's win probability, in percentage points, never negative."""
    drop = win_percent(before) - win_percent(after)
    return max(0.0, drop if mover == chess.WHITE else -drop)


def move_accuracy(loss: float) -> float:
    """Accuracy of one move (0-100) from its win-probability drop, as Lichess computes it."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss) - 3.1669))


def classify(loss: float) -> Classification:
    """Classify a move by its drop in win probability."""
    if loss >= BLUNDER_WIN:
        return "blunder"
    if loss >= MISTAKE_WIN:
        return "mistake"
    if loss >= INACCURACY_WIN:
        return "inaccuracy"
    return "ok"
