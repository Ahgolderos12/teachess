"""Player diagnosis: recurring patterns found in the player's recent games.

Each detector is a pure function over GameFacts that returns a Finding with measured
numbers and concrete evidence (game, move, clock). The coach picks a finding and explains
it; it never draws statistical conclusions on its own.
"""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from teachess.engine.models import Phase
from teachess.patterns.facts import DECISIVE_WIN, GameFacts, UserMove
from teachess.report.builder import format_eval, move_label

DEFAULT_WINDOW = 20
MIN_GAMES = 2  # a pattern needs at least this many games behind it

EARLY_MOVE = 15  # a game decided by move 15 points at the opening
TIME_TROUBLE_FRACTION = 0.10  # less than 10 % of the base time left
HASTY_MIN_CLOCK_FRACTION = 0.25  # ...while still having at least a quarter of the time
SERIOUS = ("mistake", "blunder")
MAX_EVIDENCE = 5


@dataclass(frozen=True)
class Finding:
    kind: str
    title: str
    summary: str  # one sentence with the measured numbers, in Spanish
    lesson: str  # suggested lesson topic
    points_lost: float  # points lost in the games where this pattern decided the result
    games: tuple[int, ...]  # ids of the games behind the pattern
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "lesson": self.lesson,
            "points_lost": self.points_lost,
            "games_affected": len(self.games),
            "metrics": self.metrics,
            "evidence": list(self.evidence),
        }


def diagnose(facts: list[GameFacts], window: int = DEFAULT_WINDOW) -> dict[str, Any]:
    """Diagnosis over the latest `window` analysed games (facts must be newest first)."""
    finished = [f for f in facts if f.outcome is not None]
    recent = [f for f in finished if f.analysed][:window]
    detectors: list[Callable[[list[GameFacts]], Finding | None]] = [
        early_losses,
        time_trouble,
        hasty_errors,
        failed_conversions,
        weak_phase,
    ]
    findings = [finding for detect in detectors if (finding := detect(recent))]
    if (openings := weak_openings(finished)) is not None:
        findings.append(openings)
    findings.sort(key=lambda f: (f.points_lost, len(f.games)), reverse=True)
    pending = sum(1 for f in facts if not f.analysed)
    notes = []
    if pending:
        notes.append(
            f"{pending} partidas importadas aún no están analizadas y no cuentan en los "
            "patrones que dependen del motor."
        )
    if len(recent) < 10:
        notes.append(
            f"Solo hay {len(recent)} partidas analizadas en la ventana: los patrones son "
            "orientativos."
        )
    return {
        "games_total": len(facts),
        "games_analysed": len(facts) - pending,
        "window": _window_info(recent),
        "overview": overview(recent),
        "findings": [f.to_dict() for f in findings],
        "notes": notes,
    }


def overview(games: list[GameFacts]) -> dict[str, Any]:
    """Results and how games ended over a set of games."""
    elos = [f.user_elo for f in games if f.user_elo is not None]
    return {
        "record": record(games),
        "as_white": record(f for f in games if f.stored.game.user_color == "white"),
        "as_black": record(f for f in games if f.stored.game.user_color == "black"),
        "losses_by_termination": dict(
            Counter(f.termination for f in games if f.outcome == "loss").most_common()
        ),
        "rating_latest": elos[0] if elos else None,
        "rating_oldest_in_window": elos[-1] if elos else None,
        "last_10": "".join(
            {"win": "V", "draw": "T", "loss": "D"}[f.outcome] for f in games[:10] if f.outcome
        ),
    }


# --- detectors -----------------------------------------------------------------


def early_losses(games: list[GameFacts]) -> Finding | None:
    """Games decided by a single error in the first moves: an opening problem."""
    hits = [
        (f, err)
        for f in games
        if (err := f.decisive_error()) is not None and err.move_number <= EARLY_MOVE
    ]
    if len(hits) < MIN_GAMES:
        return None
    not_won = sum(1 for f in games if f.outcome != "win")
    families = Counter(f.opening_family or "desconocida" for f, _ in hits)
    return Finding(
        kind="early_losses",
        title="Partidas decididas en la apertura",
        summary=(
            f"{len(hits)} de las {not_won} partidas no ganadas de las últimas {len(games)} se "
            f"decidieron con un error antes de la jugada {EARLY_MOVE + 1} "
            f"(de media en la {mean(err.move_number for _, err in hits):.0f})."
        ),
        lesson="Aperturas: principios y repertorio para las aperturas donde caes antes.",
        points_lost=_points(f for f, _ in hits),
        games=tuple(f.game_id for f, _ in hits),
        metrics={
            "games": len(hits),
            "not_won_in_window": not_won,
            "decisive_move_numbers": [err.move_number for _, err in hits],
            "openings": dict(families.most_common()),
        },
        evidence=tuple(_evidence(f, err) for f, err in hits[:MAX_EVIDENCE]),
    )


def time_trouble(games: list[GameFacts]) -> Finding | None:
    """Losses on time or decided by an error made with almost no time left."""
    timed = [f for f in games if f.base_seconds is not None]
    hits: list[tuple[GameFacts, UserMove | None]] = []
    for f in timed:
        if f.outcome == "win":
            continue
        err = f.decisive_error()
        if f.termination == "time" and f.outcome == "loss":
            hits.append((f, err))
        elif err is not None and (frac := f.clock_fraction(err)) is not None:
            if frac < TIME_TROUBLE_FRACTION:
                hits.append((f, err))
    if len(hits) < MIN_GAMES:
        return None
    low, normal = error_rates_by_clock(timed)
    on_time = sum(1 for f, _ in hits if f.termination == "time" and f.outcome == "loss")
    return Finding(
        kind="time_trouble",
        title="Apuros de tiempo",
        summary=(
            f"{len(hits)} partidas de las últimas {len(games)} se perdieron por el reloj: "
            f"{on_time} por tiempo y {len(hits) - on_time} por un error decisivo con menos del "
            f"{TIME_TROUBLE_FRACTION * 100:.0f} % del tiempo."
        ),
        lesson="Gestión del tiempo: repartir el reloj y decidir rápido en posiciones sencillas.",
        points_lost=_points(f for f, _ in hits),
        games=tuple(f.game_id for f, _ in hits),
        metrics={
            "losses_on_time": on_time,
            "decisive_errors_low_clock": len(hits) - on_time,
            "serious_errors_per_100_moves_low_clock": low,
            "serious_errors_per_100_moves_otherwise": normal,
            "avg_seconds_per_move_by_phase": seconds_by_phase(timed),
        },
        evidence=tuple(_evidence(f, err) for f, err in hits[:MAX_EVIDENCE]),
    )


def hasty_errors(games: list[GameFacts]) -> Finding | None:
    """Serious errors played in a few seconds while there was plenty of time left."""
    hasty: list[tuple[GameFacts, UserMove]] = []
    serious_total = 0
    for f in games:
        if f.base_seconds is None:
            continue
        quick = max(2.0, f.base_seconds / 100)
        for um in f.user_moves:
            if um.move.classification not in SERIOUS:
                continue
            serious_total += 1
            frac = f.clock_fraction(um)
            if (
                um.seconds_spent is not None
                and um.seconds_spent <= quick
                and frac is not None
                and frac >= HASTY_MIN_CLOCK_FRACTION
            ):
                hasty.append((f, um))
    if len(hasty) < 3 or len({f.game_id for f, _ in hasty}) < MIN_GAMES:
        return None
    decided = {
        f.game_id: f for f, um in hasty if (err := f.decisive_error()) and err.move is um.move
    }
    hasty.sort(key=lambda pair: pair[1].move.win_loss, reverse=True)
    return Finding(
        kind="hasty_errors",
        title="Errores por jugar demasiado rápido",
        summary=(
            f"{len(hasty)} de tus {serious_total} errores y errores graves de las últimas "
            f"{len(games)} partidas los jugaste en muy pocos segundos teniendo tiempo de sobra; "
            f"{len(decided)} decidieron la partida."
        ),
        lesson="Rutina antes de mover: amenazas del rival, jaques, capturas y piezas colgadas.",
        points_lost=_points(decided.values()),
        games=tuple(dict.fromkeys(f.game_id for f, _ in hasty)),
        metrics={
            "hasty_serious_errors": len(hasty),
            "serious_errors_total": serious_total,
            "decided_games": len(decided),
            "avg_seconds_spent": round(mean(um.seconds_spent or 0 for _, um in hasty), 1),
        },
        evidence=tuple(_evidence(f, um) for f, um in hasty[:MAX_EVIDENCE]),
    )


def failed_conversions(games: list[GameFacts]) -> Finding | None:
    """Games with a clearly winning position that were not won."""
    hits: list[tuple[GameFacts, UserMove, UserMove | None]] = []
    for f in games:
        if f.outcome == "win":
            continue
        peak = sustained_advantage(f.user_moves)
        if peak is None:
            continue
        later = [um for um in f.user_moves if um.move.ply > peak.move.ply]
        thrown = max(later, key=lambda um: um.move.win_loss, default=None)
        hits.append((f, peak, thrown))
    if len(hits) < MIN_GAMES:
        return None
    draws = sum(1 for f, _, _ in hits if f.outcome == "draw")
    evidence = []
    for f, peak, thrown in hits[:MAX_EVIDENCE]:
        item = _evidence(f, thrown)
        item["winning_since"] = f"{move_label(peak.move)}{peak.move.san}"
        item["winning_eval"] = format_eval(peak.move.eval_after)
        evidence.append(item)
    return Finding(
        kind="failed_conversions",
        title="Ventajas ganadoras que se escapan",
        summary=(
            f"En {len(hits)} de las últimas {len(games)} partidas llegaste a una posición "
            f"ganadora (≥ {DECISIVE_WIN:.0f} % de probabilidad) y no ganaste: "
            f"{len(hits) - draws} derrotas y {draws} tablas."
        ),
        lesson="Convertir la ventaja: simplificar, quitar contrajuego y no relajarse.",
        points_lost=_points(f for f, _, _ in hits),
        games=tuple(f.game_id for f, _, _ in hits),
        metrics={"games": len(hits), "losses": len(hits) - draws, "draws": draws},
        evidence=tuple(evidence),
    )


def weak_phase(games: list[GameFacts]) -> Finding | None:
    """A phase of the game with clearly more serious errors than the others."""
    rates = phase_error_rates(games)
    measured = {p: r for p, r in rates.items() if r["moves"] >= 20}
    if len(measured) < 2:
        return None
    worst = max(measured, key=lambda p: measured[p]["serious_per_100"])
    others = [r["serious_per_100"] for p, r in measured.items() if p != worst]
    baseline = mean(others)
    if measured[worst]["serious_per_100"] < max(1.0, 1.4 * baseline):
        return None
    decided = [f for f in games if (err := f.decisive_error()) and err.move.phase == worst]
    errors = sorted(
        ((f, um) for f in games for um in f.user_moves
         if um.move.phase == worst and um.move.classification in SERIOUS),
        key=lambda pair: pair[1].move.win_loss,
        reverse=True,
    )  # fmt: skip
    name = PHASE_NAMES[worst]
    return Finding(
        kind="weak_phase",
        title=f"Más errores en {name}",
        summary=(
            f"En {name} cometes {_num(measured[worst]['serious_per_100'])} errores serios cada "
            f"100 jugadas, frente a {_num(baseline)} en el resto de fases; {len(decided)} partidas "
            "se decidieron ahí."
        ),
        lesson=PHASE_LESSONS[worst],
        points_lost=_points(decided),
        games=tuple(dict.fromkeys(f.game_id for f, _ in errors)),
        metrics={"phase": worst, "by_phase": rates},
        evidence=tuple(_evidence(f, um) for f, um in errors[:MAX_EVIDENCE]),
    )


def weak_openings(games: list[GameFacts]) -> Finding | None:
    """Openings (by family and colour) played at least 3 times with a poor score.

    Needs only the PGN headers, so it uses every finished game, analysed or not.
    """
    groups: dict[tuple[str, str], list[GameFacts]] = {}
    for f in games:
        if f.opening_family:
            groups.setdefault((f.opening_family, f.stored.game.user_color), []).append(f)
    weak = []
    for (family, color), group in groups.items():
        score = sum(f.score for f in group) / len(group)
        if len(group) >= 3 and score <= 0.35:
            weak.append({"opening": family, "color": color, **record(group)})
    if not weak:
        return None
    weak.sort(key=lambda o: o["games"] - o["points"], reverse=True)
    keys = {(o["opening"], o["color"]) for o in weak}
    affected = [f for f in games if (f.opening_family, f.stored.game.user_color) in keys]
    # Only games decided early count as points lost to the opening itself.
    decided_early = [
        f for f in affected if (err := f.decisive_error()) and err.move_number <= EARLY_MOVE
    ]
    by_relevance = sorted(
        affected, key=lambda f: (f in decided_early, f.outcome == "loss"), reverse=True
    )
    return Finding(
        kind="weak_openings",
        title="Aperturas con mal resultado",
        summary=(
            f"{len(weak)} aperturas jugadas al menos 3 veces con un 35 % de puntos o menos: "
            + ", ".join(
                f"{o['opening']} con {COLOR_NAMES[o['color']]} ({o['score_pct']} %)"
                for o in weak[:3]
            )
            + "."
        ),
        lesson="Repertorio: revisar o cambiar las aperturas que peor te funcionan.",
        points_lost=_points(decided_early),
        games=tuple(f.game_id for f in affected),
        metrics={
            "openings": weak,
            "games_considered": len(games),
            "games_decided_by_move_15": len(decided_early),
        },
        evidence=tuple(_evidence(f, f.decisive_error()) for f in by_relevance[:MAX_EVIDENCE]),
    )


# --- shared measurements ----------------------------------------------------------

PHASE_NAMES: dict[str, str] = {
    "opening": "la apertura",
    "middlegame": "el medio juego",
    "endgame": "el final",
}
PHASE_LESSONS: dict[str, str] = {
    "opening": "Principios de apertura a partir de tus propias posiciones.",
    "middlegame": "Medio juego: amenazas, piezas colgadas y planes, con tus posiciones.",
    "endgame": "Técnica de finales a partir de tus propias posiciones.",
}
COLOR_NAMES = {"white": "blancas", "black": "negras"}
_PHASES: tuple[Phase, ...] = ("opening", "middlegame", "endgame")


def phase_error_rates(games: list[GameFacts]) -> dict[str, dict[str, Any]]:
    rates: dict[str, dict[str, Any]] = {}
    for phase in _PHASES:
        moves = [um for f in games for um in f.user_moves if um.move.phase == phase]
        serious = sum(1 for um in moves if um.move.classification in SERIOUS)
        rates[phase] = {
            "moves": len(moves),
            "serious_errors": serious,
            "serious_per_100": round(100 * serious / len(moves), 1) if moves else None,
            "avg_win_loss_pct": round(mean(um.move.win_loss for um in moves), 1) if moves else None,
        }
    return rates


def error_rates_by_clock(games: list[GameFacts]) -> tuple[float | None, float | None]:
    low: list[UserMove] = []
    normal: list[UserMove] = []
    for f in games:
        for um in f.user_moves:
            frac = f.clock_fraction(um)
            if frac is not None:
                (low if frac < TIME_TROUBLE_FRACTION else normal).append(um)

    def rate(moves: list[UserMove]) -> float | None:
        if not moves:
            return None
        return round(100 * sum(um.move.classification in SERIOUS for um in moves) / len(moves), 1)

    return rate(low), rate(normal)


def seconds_by_phase(games: list[GameFacts]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for phase in _PHASES:
        spent = [
            um.seconds_spent
            for f in games
            for um in f.user_moves
            if um.move.phase == phase and um.seconds_spent is not None
        ]
        result[phase] = round(mean(spent), 1) if spent else None
    return result


def sustained_advantage(moves: tuple[UserMove, ...]) -> UserMove | None:
    """First of two consecutive own moves leaving a decisive advantage."""
    for current, following in zip(moves, moves[1:], strict=False):
        if current.win_after >= DECISIVE_WIN and following.win_after >= DECISIVE_WIN:
            return current
    return None


def record(games: Iterable[GameFacts]) -> dict[str, Any]:
    items = list(games)
    counts = Counter(f.outcome for f in items)
    points = sum(f.score for f in items)
    return {
        "games": len(items),
        "wins": counts["win"],
        "draws": counts["draw"],
        "losses": counts["loss"],
        "points": points,
        "score_pct": round(100 * points / len(items)) if items else None,
    }


def _num(value: float) -> str:
    """Spanish decimal comma: 7.3 -> '7,3'."""
    return f"{value:.1f}".replace(".", ",")


def _points(games: Iterable[GameFacts]) -> float:
    return sum(f.points_lost for f in games)


def _window_info(games: list[GameFacts]) -> dict[str, Any]:
    dates = [f.stored.game.played_at[:10] for f in games if f.stored.game.played_at]
    return {"games": len(games), "from": min(dates, default=None), "to": max(dates, default=None)}


def _evidence(f: GameFacts, um: UserMove | None) -> dict[str, Any]:
    game = f.stored.game
    item: dict[str, Any] = {
        "game_id": f.game_id,
        "played_at": (game.played_at or "")[:10] or None,
        "opponent": f.opponent,
        "user_color": game.user_color,
        "outcome": f.outcome,
        "opening": f.opening,
        "time_control": game.time_control,
        "termination": f.termination,
    }
    if um is not None:
        m = um.move
        item.update(
            move=f"{move_label(m)}{m.san}",
            fen_before=m.fen_before,
            best_move=m.best_move_san,
            classification=m.classification,
            win_loss_pct=round(m.win_loss, 1),
            win_after_pct=round(um.win_after, 1),
            phase=m.phase,
            clock_left_seconds=m.clock_seconds,
            seconds_spent=None if um.seconds_spent is None else round(um.seconds_spent, 1),
        )
    return item
