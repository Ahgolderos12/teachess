"""Report data built from stored analysis; formatting lives in render.py."""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

import chess

from teachess.db import repository as repo
from teachess.db.repository import StoredGame
from teachess.engine.models import Classification, MoveAnalysis, Phase

ERROR_CLASSES: tuple[Classification, ...] = ("inaccuracy", "mistake", "blunder")
PHASES: tuple[Phase, ...] = ("opening", "middlegame", "endgame")


@dataclass(frozen=True)
class GameReport:
    stored: StoredGame
    user_moves: list[MoveAnalysis]
    mistakes: list[MoveAnalysis]  # user's moves classified as an inaccuracy or worse

    @property
    def acpl(self) -> float | None:
        """User's average centipawn loss in this game."""
        if not self.user_moves:
            return None
        return sum(m.cp_loss for m in self.user_moves) / len(self.user_moves)

    @property
    def counts(self) -> Counter[Classification]:
        return Counter(m.classification for m in self.mistakes)


@dataclass(frozen=True)
class UserReport:
    username: str
    games: list[GameReport]
    pending: int  # imported but not analysed yet
    by_phase: dict[Phase, Counter[Classification]] = field(default_factory=dict)

    @property
    def acpl(self) -> float | None:
        moves = [m for g in self.games for m in g.user_moves]
        return sum(m.cp_loss for m in moves) / len(moves) if moves else None

    @property
    def counts(self) -> Counter[Classification]:
        total: Counter[Classification] = Counter()
        for game in self.games:
            total.update(game.counts)
        return total

    def worst_games(self, limit: int = 5) -> list[GameReport]:
        ranked = sorted(
            self.games,
            key=lambda g: (g.counts["blunder"], g.counts["mistake"], g.acpl or 0),
            reverse=True,
        )
        return [g for g in ranked if g.mistakes][:limit]


def build_game_report(stored: StoredGame, moves: list[MoveAnalysis]) -> GameReport:
    user_turn = chess.WHITE if stored.game.user_color == "white" else chess.BLACK
    user_moves = [m for m in moves if mover(m) == user_turn]
    return GameReport(
        stored=stored,
        user_moves=user_moves,
        mistakes=[m for m in user_moves if m.classification != "ok"],
    )


def build_user_report(username: str, games: list[GameReport], pending: int) -> UserReport:
    by_phase: dict[Phase, Counter[Classification]] = {phase: Counter() for phase in PHASES}
    for game in games:
        for m in game.mistakes:
            by_phase[m.phase][m.classification] += 1
    return UserReport(username=username, games=games, pending=pending, by_phase=by_phase)


def load_game_report(conn: sqlite3.Connection, game_id: int) -> GameReport | None:
    """None if the game does not exist or has not been analysed."""
    stored = repo.get_game(conn, game_id)
    if stored is None or stored.analyzed_depth is None:
        return None
    return build_game_report(stored, repo.get_move_analysis(conn, game_id))


def load_user_report(conn: sqlite3.Connection, username: str) -> UserReport:
    games = repo.list_games(conn, username=username)
    analysed = [g for g in games if g.analyzed_depth is not None]
    reports = [build_game_report(g, repo.get_move_analysis(conn, g.id)) for g in analysed]
    return build_user_report(username, reports, pending=len(games) - len(analysed))


def mover(move: MoveAnalysis) -> chess.Color:
    return chess.Board(move.fen_before).turn


def move_label(move: MoveAnalysis) -> str:
    """'12.' for a White move, '12...' for a Black move."""
    board = chess.Board(move.fen_before)
    return f"{board.fullmove_number}{'.' if board.turn == chess.WHITE else '...'}"


def best_line_san(move: MoveAnalysis, max_plies: int = 5) -> str:
    """Engine's principal variation in SAN, cut at the first illegal move."""
    board = chess.Board(move.fen_before)
    line: list[chess.Move] = []
    for uci in move.eval_before.pv[:max_plies]:
        candidate = chess.Move.from_uci(uci)
        if not board.is_legal(candidate):
            break
        line.append(candidate)
        board.push(candidate)
    return chess.Board(move.fen_before).variation_san(line) if line else ""
