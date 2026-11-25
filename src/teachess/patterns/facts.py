"""Per-game facts derived from the PGN headers and the stored engine analysis.

Everything here is measured, never guessed: results and clocks come from the PGN, and every
judgement about a move comes from the Stockfish analysis already saved in the database.
"""

import io
import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

import chess
import chess.pgn

from teachess.db import repository as repo
from teachess.db.repository import StoredGame
from teachess.engine.models import MoveAnalysis
from teachess.engine.scoring import MISTAKE_WIN, win_percent
from teachess.report.builder import mover, opening_name

Outcome = Literal["win", "draw", "loss"]
TimeClass = Literal["bullet", "blitz", "rapid", "daily"]
Termination = Literal[
    "checkmate", "resignation", "time", "abandoned", "agreement", "repetition",
    "stalemate", "insufficient", "other",
]  # fmt: skip

SCORE: dict[Outcome, float] = {"win": 1.0, "draw": 0.5, "loss": 0.0}

# A position counts as decided for the player below this win probability (percentage).
LOST_BELOW_WIN = 50.0
# Advantage considered decisive (win probability >= 80 % is about +3.8 pawns).
DECISIVE_WIN = 80.0

_OPENING_KEYWORDS = {"Opening", "Defense", "Defence", "Game", "Gambit", "Attack", "System"}


@dataclass(frozen=True)
class UserMove:
    """One of the player's moves with the context needed by the detectors."""

    move: MoveAnalysis
    move_number: int
    win_after: float  # player's win probability after the move (0-100)
    seconds_spent: float | None  # thinking time, from consecutive %clk values


@dataclass(frozen=True)
class GameFacts:
    stored: StoredGame
    outcome: Outcome | None  # None for unfinished games ("*")
    termination: Termination
    base_seconds: int | None  # None for daily or unknown time controls
    increment: int
    opening: str | None
    opening_family: str | None
    user_elo: int | None
    opponent_elo: int | None
    full_moves: int
    analysed: bool
    user_moves: tuple[UserMove, ...]  # empty if not analysed
    win_curve: tuple[float, ...]  # player's win probability after every ply (if analysed)

    @property
    def game_id(self) -> int:
        return self.stored.id

    @property
    def score(self) -> float:
        return SCORE[self.outcome] if self.outcome else 0.0

    @property
    def points_lost(self) -> float:
        return 1.0 - self.score if self.outcome else 0.0

    @property
    def time_class(self) -> TimeClass:
        """Chess.com-style class from the estimated duration (base + 40 × increment)."""
        if self.base_seconds is None:
            return "daily"
        estimate = self.base_seconds + 40 * self.increment
        return "bullet" if estimate < 180 else "blitz" if estimate < 600 else "rapid"

    @property
    def opponent(self) -> str:
        game = self.stored.game
        return game.black if game.user_color == "white" else game.white

    def decisive_error(self) -> UserMove | None:
        """The player's first mistake or blunder after which the game never came back.

        Only for games the player did not win: the first move losing at least a mistake's
        worth of win probability after which the player's win probability stays below 50 %
        until the end. None if the game slipped away gradually or ended another way.
        """
        if self.outcome == "win" or not self.user_moves:
            return None
        for user_move in self.user_moves:
            if user_move.move.win_loss < MISTAKE_WIN:
                continue
            start = user_move.move.ply - 1  # index of this ply in win_curve
            if all(w < LOST_BELOW_WIN for w in self.win_curve[start:]):
                return user_move
        return None

    def clock_fraction(self, user_move: UserMove) -> float | None:
        """Share of the base time left after the move (0-1), if the clock is known."""
        if self.base_seconds is None or user_move.move.clock_seconds is None:
            return None
        return user_move.move.clock_seconds / self.base_seconds


def build_game_facts(stored: StoredGame, moves: list[MoveAnalysis] | None) -> GameFacts:
    game = stored.game
    pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
    headers = pgn_game.headers if pgn_game is not None else chess.pgn.Headers()
    final_board = pgn_game.end().board() if pgn_game is not None else chess.Board()
    base, increment = parse_time_control(game.time_control)
    user_color = chess.WHITE if game.user_color == "white" else chess.BLACK
    opening = opening_name(game.pgn)
    analysed = stored.analyzed_depth is not None and bool(moves)
    user_moves = _user_moves(moves or [], user_color, base, increment) if analysed else ()
    curve = tuple(_user_win(m, user_color) for m in moves or []) if analysed else ()
    elo_keys = ("WhiteElo", "BlackElo") if user_color == chess.WHITE else ("BlackElo", "WhiteElo")
    return GameFacts(
        stored=stored,
        outcome=outcome_for(game.result, game.user_color),
        termination=parse_termination(headers.get("Termination", ""), final_board),
        base_seconds=base,
        increment=increment,
        opening=opening,
        opening_family=opening_family(opening),
        user_elo=_int_or_none(headers.get(elo_keys[0])),
        opponent_elo=_int_or_none(headers.get(elo_keys[1])),
        full_moves=final_board.fullmove_number - (1 if final_board.turn == chess.WHITE else 0),
        analysed=analysed,
        user_moves=user_moves,
        win_curve=curve,
    )


def load_facts(conn: sqlite3.Connection, username: str) -> list[GameFacts]:
    """Facts for every imported game of the player, newest first."""
    facts = []
    for stored in repo.list_games(conn, username=username):
        moves = repo.get_move_analysis(conn, stored.id) if stored.analyzed_depth else None
        facts.append(build_game_facts(stored, moves))
    return facts


def outcome_for(result: str, user_color: str) -> Outcome | None:
    if result == "1/2-1/2":
        return "draw"
    if result not in ("1-0", "0-1"):
        return None
    white_won = result == "1-0"
    return "win" if white_won == (user_color == "white") else "loss"


def parse_time_control(time_control: str | None) -> tuple[int | None, int]:
    """'600+5' -> (600, 5); '300' -> (300, 0); daily ('1/86400') or unknown -> (None, 0)."""
    if not time_control:
        return None, 0
    match = re.fullmatch(r"(\d+)(?:\+(\d+))?", time_control.strip())
    if match is None:
        return None, 0
    return int(match.group(1)), int(match.group(2) or 0)


def parse_termination(text: str, final_board: chess.Board) -> Termination:
    """Classify the PGN `Termination` header (Chess.com wording or Lichess codes)."""
    lowered = text.lower()
    if final_board.is_checkmate() or "checkmate" in lowered:
        return "checkmate"
    rules: list[tuple[str, Termination]] = [
        ("resign", "resignation"),
        ("abandon", "abandoned"),
        ("insufficient", "insufficient"),
        ("time", "time"),  # "won on time", "Time forfeit"
        ("agreement", "agreement"),
        ("repetition", "repetition"),
        ("stalemate", "stalemate"),
    ]
    for needle, kind in rules:
        if needle in lowered:
            return kind
    if final_board.is_stalemate():
        return "stalemate"
    return "other"


def opening_family(name: str | None) -> str | None:
    """'Sicilian Defense Alapin Variation 2...d5' -> 'Sicilian Defense'."""
    if not name:
        return None
    words = name.split()
    for index, word in enumerate(words):
        if word in _OPENING_KEYWORDS:
            return " ".join(words[: index + 1])
        if any(char.isdigit() for char in word):
            return " ".join(words[: min(index, 3)]) or name
    return " ".join(words[:3])


def _user_moves(
    moves: list[MoveAnalysis], user_color: chess.Color, base: int | None, increment: int
) -> tuple[UserMove, ...]:
    result = []
    previous_clock: float | None = float(base) if base is not None else None
    for m in moves:
        if mover(m) != user_color:
            continue
        spent = None
        if previous_clock is not None and m.clock_seconds is not None:
            spent = max(0.0, previous_clock - m.clock_seconds + increment)
        previous_clock = m.clock_seconds
        result.append(
            UserMove(
                move=m,
                move_number=chess.Board(m.fen_before).fullmove_number,
                win_after=_user_win(m, user_color),
                seconds_spent=spent,
            )
        )
    return tuple(result)


def _user_win(move: MoveAnalysis, user_color: chess.Color) -> float:
    white = win_percent(move.eval_after)
    return white if user_color == chess.WHITE else 100.0 - white


def _int_or_none(text: str | None) -> int | None:
    try:
        return int(text) if text else None
    except ValueError:
        return None
