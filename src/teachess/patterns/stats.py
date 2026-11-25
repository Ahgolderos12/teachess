"""Player statistics for the Statistics page: everything measurable about the player's games.

Results, rating, openings and terminations need only the PGN; error, time-management and
conversion figures come from the stored Stockfish analysis.
"""

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import datetime
from statistics import mean
from typing import Any

from teachess.engine.models import Classification
from teachess.engine.scoring import move_accuracy
from teachess.patterns.diagnosis import (
    EARLY_MOVE,
    SERIOUS,
    TIME_TROUBLE_FRACTION,
    error_rates_by_clock,
    phase_error_rates,
    record,
    seconds_by_phase,
    sustained_advantage,
)
from teachess.patterns.facts import DECISIVE_WIN, GameFacts, UserMove

LOSING_WIN = 100.0 - DECISIVE_WIN  # 20 %: a clearly lost position
ERROR_CLASSES: tuple[Classification, ...] = ("inaccuracy", "mistake", "blunder")
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DAY_BLOCKS = ((0, "madrugada (0-6 h)"), (6, "mañana (6-12 h)"), (12, "tarde (12-18 h)"),
              (18, "noche (18-24 h)"))  # fmt: skip
# Wide bands: Chess.com PGNs seem to carry post-game ratings, which shift close games by
# roughly ±8 points each way (wins look like games against weaker rivals).
RATING_BUCKETS = ((-10_000, "rival 150+ por debajo"), (-149, "rival 50-149 por debajo"),
                  (-49, "rival parecido (±50)"), (50, "rival 50-149 por encima"),
                  (150, "rival 150+ por encima"))  # fmt: skip
TIME_CLASSES = ("bullet", "blitz", "rapid", "daily")
THINK_BUCKETS = ((0, "< 2 s"), (2, "2-5 s"), (5, "5-15 s"), (15, "15-60 s"), (60, "> 60 s"))
DECISIVE_BUCKETS = ((1, "1-10"), (11, "11-20"), (21, "21-30"), (31, "31-40"), (41, "41+"))
MAX_OPENINGS = 25


def player_stats(facts: list[GameFacts]) -> dict[str, Any]:
    """All statistics for one player's games (facts newest first)."""
    finished = [f for f in facts if f.outcome is not None]
    analysed = [f for f in finished if f.analysed]
    return {
        "games_total": len(facts),
        "games_analysed": sum(f.analysed for f in facts),
        "games_pending": sum(not f.analysed for f in facts),
        "summary": _summary(finished, analysed),
        "results": {
            "by_color": {
                color: record(f for f in finished if f.stored.game.user_color == color)
                for color in ("white", "black")
            },
            "by_time_class": [
                row
                for tc in TIME_CLASSES
                if (row := {"key": tc, **record(f for f in finished if f.time_class == tc)})[
                    "games"
                ]
            ],
            "by_time_control": _grouped(finished, lambda f: f.stored.game.time_control or "?"),
            "by_rating_diff": _by_rating_diff(finished),
            "by_weekday": _by_weekday(finished),
            "by_time_of_day": _by_time_of_day(finished),
        },
        "terminations": {
            outcome: dict(
                Counter(f.termination for f in finished if f.outcome == outcome).most_common()
            )
            for outcome in ("win", "draw", "loss")
        },
        "errors": _errors(analysed),
        "openings": _openings(finished),
        "time": _time(analysed),
        "decisive_errors": _decisive(analysed),
        "conversion": _conversion(analysed),
        "duration": {
            outcome: _avg(f.full_moves for f in finished if f.outcome == outcome)
            for outcome in ("win", "draw", "loss")
        },
        "monthly": _monthly(finished),
        "timeline": [_timeline_point(f) for f in reversed(finished)],
        "worst_games": _worst_games(analysed),
    }


def game_accuracy(f: GameFacts) -> float | None:
    """Mean move accuracy of the player in the game (Lichess per-move formula)."""
    if not f.user_moves:
        return None
    return mean(move_accuracy(um.move.win_loss) for um in f.user_moves)


def game_acpl(f: GameFacts) -> float | None:
    return mean(um.move.cp_loss for um in f.user_moves) if f.user_moves else None


# --- sections ---------------------------------------------------------------------


def _summary(finished: list[GameFacts], analysed: list[GameFacts]) -> dict[str, Any]:
    moves = [um for f in analysed for um in f.user_moves]
    return {
        "record": record(finished),
        "acpl": _round(mean(um.move.cp_loss for um in moves)) if moves else None,
        "accuracy": _round(mean(move_accuracy(um.move.win_loss) for um in moves))
        if moves
        else None,
        "avg_moves": _avg(f.full_moves for f in finished),
        "ratings": _ratings(finished),
        "streaks": _streaks(finished),
    }


def _ratings(finished: list[GameFacts]) -> list[dict[str, Any]]:
    """Rating per time class (each class has its own rating), most played first."""
    rows = []
    for tc in TIME_CLASSES:
        group = [f for f in finished if f.time_class == tc and f.user_elo is not None]
        if not group:
            continue
        ratings = [f.user_elo for f in group if f.user_elo is not None]  # newest first
        rows.append(
            {
                "time_class": tc,
                "games": len(group),
                "latest": ratings[0],
                "peak": max(ratings),
                "lowest": min(ratings),
                "change": ratings[0] - ratings[-1],
                "avg_opponent": _avg(f.opponent_elo for f in group if f.opponent_elo),
            }
        )
    return sorted(rows, key=lambda row: row["games"], reverse=True)


def _streaks(finished: list[GameFacts]) -> dict[str, Any]:
    chronological = [f.outcome for f in reversed(finished)]
    longest = {"win": 0, "loss": 0}
    run_outcome, run = None, 0
    for outcome in chronological:
        run = run + 1 if outcome == run_outcome else 1
        run_outcome = outcome
        if outcome in longest:
            longest[outcome] = max(longest[outcome], run)
    return {
        "current": {"outcome": run_outcome, "games": run} if chronological else None,
        "longest_win": longest["win"],
        "longest_loss": longest["loss"],
    }


def _grouped(games: list[GameFacts], key: Callable[[GameFacts], str]) -> list[dict[str, Any]]:
    groups: dict[str, list[GameFacts]] = {}
    for f in games:
        groups.setdefault(key(f), []).append(f)
    rows = [{"key": k, **record(group)} for k, group in groups.items()]
    return sorted(rows, key=lambda row: row["games"], reverse=True)


def _by_rating_diff(games: list[GameFacts]) -> list[dict[str, Any]]:
    rated = [f for f in games if f.user_elo and f.opponent_elo]
    rows = []
    for index, (low, label) in enumerate(RATING_BUCKETS):
        high = RATING_BUCKETS[index + 1][0] if index + 1 < len(RATING_BUCKETS) else 10_000
        group = [f for f in rated if low <= (f.opponent_elo or 0) - (f.user_elo or 0) < high]
        rows.append({"key": label, **record(group)})
    return rows


def _by_weekday(games: list[GameFacts]) -> list[dict[str, Any]]:
    local = [(f, t) for f in games if (t := _local_time(f)) is not None]
    return [
        {"key": name, **record(f for f, t in local if t.weekday() == day)}
        for day, name in enumerate(WEEKDAYS)
    ]


def _by_time_of_day(games: list[GameFacts]) -> list[dict[str, Any]]:
    local = [(f, t) for f in games if (t := _local_time(f)) is not None]
    rows = []
    for index, (start, label) in enumerate(DAY_BLOCKS):
        end = DAY_BLOCKS[index + 1][0] if index + 1 < len(DAY_BLOCKS) else 24
        rows.append({"key": label, **record(f for f, t in local if start <= t.hour < end)})
    return rows


def _errors(analysed: list[GameFacts]) -> dict[str, Any]:
    moves = [um for f in analysed for um in f.user_moves]
    counts = Counter(um.move.classification for um in moves)
    by_phase = phase_error_rates(analysed)
    for phase, row in by_phase.items():
        phase_moves = [um for um in moves if um.move.phase == phase]
        row["counts"] = {
            cls: sum(um.move.classification == cls for um in phase_moves) for cls in ERROR_CLASSES
        }
    games = len(analysed)
    return {
        "moves": len(moves),
        "counts": {cls: counts[cls] for cls in ERROR_CLASSES},
        "per_game": {
            cls: _round(counts[cls] / games, 2) if games else None for cls in ERROR_CLASSES
        },  # fmt: skip
        "by_phase": by_phase,
        "games_without_serious_errors": sum(
            all(um.move.classification not in SERIOUS for um in f.user_moves) for f in analysed
        ),
    }


def _openings(games: list[GameFacts]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[GameFacts]] = {}
    for f in games:
        groups.setdefault((f.opening_family or "Desconocida", f.stored.game.user_color), []).append(
            f
        )
    rows = []
    for (family, color), group in groups.items():
        analysed = [f for f in group if f.analysed]
        early = [
            f for f in analysed if (err := f.decisive_error()) and err.move_number <= EARLY_MOVE
        ]
        rows.append(
            {
                "opening": family,
                "color": color,
                **record(group),
                "accuracy": _avg(game_accuracy(f) for f in analysed),
                "acpl": _avg(game_acpl(f) for f in analysed),
                "decided_early": len(early),
                "last_game_id": group[0].game_id,
            }
        )
    rows.sort(key=lambda row: row["games"], reverse=True)
    return rows[:MAX_OPENINGS]


def _time(analysed: list[GameFacts]) -> dict[str, Any]:
    timed = [f for f in analysed if f.base_seconds is not None]
    buckets = []
    for index, (low, label) in enumerate(THINK_BUCKETS):
        high = THINK_BUCKETS[index + 1][0] if index + 1 < len(THINK_BUCKETS) else float("inf")
        moves = [
            um
            for f in timed
            for um in f.user_moves
            if um.seconds_spent is not None and low <= um.seconds_spent < high
        ]
        serious = sum(um.move.classification in SERIOUS for um in moves)
        buckets.append(
            {
                "key": label,
                "moves": len(moves),
                "serious_errors": serious,
                "serious_pct": _round(100 * serious / len(moves)) if moves else None,
            }
        )
    fractions = [
        frac for f in timed for um in f.user_moves if (frac := f.clock_fraction(um)) is not None
    ]
    low_clock = sum(frac < TIME_TROUBLE_FRACTION for frac in fractions)
    low_rate, normal_rate = error_rates_by_clock(timed)
    lost = [f for f in timed if f.outcome == "loss"]
    return {
        "avg_seconds_by_phase": seconds_by_phase(timed),
        "think_time": buckets,
        "low_clock_moves_pct": _round(100 * low_clock / len(fractions)) if fractions else None,
        "serious_per_100_low_clock": low_rate,
        "serious_per_100_otherwise": normal_rate,
        "losses_on_time": sum(f.termination == "time" for f in lost),
        "wins_on_time": sum(f.termination == "time" and f.outcome == "win" for f in timed),
        "avg_clock_left_pct_end_of_losses": _avg(
            100 * frac
            for f in lost
            if f.user_moves and (frac := f.clock_fraction(f.user_moves[-1])) is not None
        ),
    }


def _decisive(analysed: list[GameFacts]) -> dict[str, Any]:
    not_won = [f for f in analysed if f.outcome != "win"]
    errors = [(f, err) for f in not_won if (err := f.decisive_error()) is not None]
    buckets = []
    for index, (low, label) in enumerate(DECISIVE_BUCKETS):
        high = DECISIVE_BUCKETS[index + 1][0] if index + 1 < len(DECISIVE_BUCKETS) else 10_000
        buckets.append(
            {"key": label, "games": sum(low <= err.move_number < high for _, err in errors)}
        )
    return {
        "not_won": len(not_won),
        "with_decisive_error": len(errors),
        "by_move_number": buckets,
        "by_phase": dict(Counter(err.move.phase for _, err in errors)),
        "avg_move_number": _avg(err.move_number for _, err in errors),
        "avg_seconds_spent": _avg(err.seconds_spent for _, err in errors if err.seconds_spent),
    }


def _conversion(analysed: list[GameFacts]) -> dict[str, Any]:
    winning = [f for f in analysed if sustained_advantage(f.user_moves)]
    losing = [f for f in analysed if _sustained_disadvantage(f.user_moves)]
    converted = sum(f.outcome == "win" for f in winning)
    saved = sum(f.outcome != "loss" for f in losing)
    return {
        "winning_games": len(winning),
        "converted": converted,
        "conversion_pct": _round(100 * converted / len(winning)) if winning else None,
        "losing_games": len(losing),
        "saved": saved,
        "save_pct": _round(100 * saved / len(losing)) if losing else None,
    }


def _monthly(games: list[GameFacts]) -> list[dict[str, Any]]:
    groups: dict[str, list[GameFacts]] = {}
    for f in games:
        if f.stored.game.played_at:
            groups.setdefault(f.stored.game.played_at[:7], []).append(f)
    return [
        {
            "month": month,
            **record(group),
            "accuracy": _avg(game_accuracy(f) for f in group if f.analysed),
            "acpl": _avg(game_acpl(f) for f in group if f.analysed),
        }
        for month, group in sorted(groups.items())
    ]


def _timeline_point(f: GameFacts) -> dict[str, Any]:
    counts = Counter(um.move.classification for um in f.user_moves)
    return {
        "game_id": f.game_id,
        "played_at": f.stored.game.played_at,
        "outcome": f.outcome,
        "rating": f.user_elo,
        "time_control": f.stored.game.time_control,
        "time_class": f.time_class,
        "accuracy": _round(game_accuracy(f)),
        "acpl": _round(game_acpl(f)),
        "blunders": counts["blunder"] if f.analysed else None,
        "mistakes": counts["mistake"] if f.analysed else None,
    }


def _worst_games(analysed: list[GameFacts], limit: int = 10) -> list[dict[str, Any]]:
    def key(f: GameFacts) -> tuple[int, int, float]:
        counts = Counter(um.move.classification for um in f.user_moves)
        return counts["blunder"], counts["mistake"], game_acpl(f) or 0

    rows = []
    for f in sorted(analysed, key=key, reverse=True)[:limit]:
        counts = Counter(um.move.classification for um in f.user_moves)
        rows.append(
            {
                "game_id": f.game_id,
                "played_at": f.stored.game.played_at,
                "opponent": f.opponent,
                "user_color": f.stored.game.user_color,
                "outcome": f.outcome,
                "opening": f.opening_family,
                "counts": {cls: counts[cls] for cls in ERROR_CLASSES},
                "accuracy": _round(game_accuracy(f)),
                "acpl": _round(game_acpl(f)),
            }
        )
    return rows


# --- helpers ---------------------------------------------------------------------


def _sustained_disadvantage(moves: tuple[UserMove, ...]) -> bool:
    return any(
        a.win_after <= LOSING_WIN and b.win_after <= LOSING_WIN
        for a, b in zip(moves, moves[1:], strict=False)
    )


def _local_time(f: GameFacts) -> datetime | None:
    played = f.stored.game.played_at
    if not played or len(played) <= 10:
        return None
    try:
        moment = datetime.fromisoformat(played)
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo else moment


def _avg(values: Iterable[float | int | None]) -> float | None:
    items = [v for v in values if v is not None]
    return _round(mean(items)) if items else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)
