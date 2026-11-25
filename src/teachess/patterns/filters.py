"""Filters for the Statistics page: choose which of the player's games the figures cover."""

from collections import Counter
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from teachess.patterns.facts import GameFacts

DAY_BLOCKS = (0, 6, 12, 18)  # start hour of madrugada, mañana, tarde, noche


@dataclass(frozen=True)
class GameFilter:
    time_class: str | None = None  # bullet, blitz, rapid, daily
    time_control: str | None = None  # as in the PGN: "600", "180+2"…
    color: str | None = None  # white, black
    outcome: str | None = None  # win, draw, loss
    termination: str | None = None  # checkmate, resignation, time…
    opening: str | None = None  # case-insensitive text found in the opening name
    since: str | None = None  # YYYY-MM-DD, inclusive
    until: str | None = None  # YYYY-MM-DD, inclusive
    min_gap: int | None = None  # rival's pre-game rating minus the player's, inclusive
    max_gap: int | None = None
    weekday: int | None = None  # 0 = Monday (local time)
    day_block: int | None = None  # one of DAY_BLOCKS (local time)
    last: int | None = None  # keep only the newest N games that match…
    offset: int = 0  # …after skipping the newest `offset` (e.g. "the 20 before those")

    def is_empty(self) -> bool:
        return self == GameFilter()

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name)}

    def apply(self, facts: list[GameFacts]) -> list[GameFacts]:
        """Matching games, keeping the input order (newest first)."""
        matching = [f for f in facts if self._matches(f)]
        if self.offset or self.last:
            end = self.offset + self.last if self.last else None
            matching = matching[self.offset : end]
        return matching

    def _matches(self, f: GameFacts) -> bool:
        game = f.stored.game
        checks = [
            self.time_class is None or f.time_class == self.time_class,
            self.time_control is None or game.time_control == self.time_control,
            self.color is None or game.user_color == self.color,
            self.outcome is None or f.outcome == self.outcome,
            self.termination is None or f.termination == self.termination,
            self.opening is None or self.opening.lower() in (f.opening or "").lower(),
            self.since is None or (game.played_at or "")[:10] >= self.since,
            self.until is None or (game.played_at or "9999")[:10] <= self.until,
        ]
        if not all(checks):
            return False
        if self.min_gap is not None or self.max_gap is not None:
            if f.user_elo_before is None or f.opponent_elo_before is None:
                return False
            gap = f.opponent_elo_before - f.user_elo_before
            if self.min_gap is not None and gap < self.min_gap:
                return False
            if self.max_gap is not None and gap > self.max_gap:
                return False
        if self.weekday is not None or self.day_block is not None:
            moment = local_time(f)
            if moment is None:
                return False
            if self.weekday is not None and moment.weekday() != self.weekday:
                return False
            if self.day_block is not None and day_block(moment.hour) != self.day_block:
                return False
        return True


def filter_options(facts: list[GameFacts]) -> dict[str, Any]:
    """Values worth offering in the filter controls, from all the player's games."""
    dates = [f.stored.game.played_at[:10] for f in facts if f.stored.game.played_at]
    openings = Counter(f.opening_family for f in facts if f.opening_family)
    return {
        "time_classes": sorted({f.time_class for f in facts}),
        "time_controls": [
            tc for tc, _ in Counter(f.stored.game.time_control for f in facts).most_common() if tc
        ],
        "terminations": [t for t, _ in Counter(f.termination for f in facts).most_common()],
        "openings": [name for name, _ in openings.most_common(60)],
        "first_date": min(dates, default=None),
        "last_date": max(dates, default=None),
        "games": len(facts),
    }


def local_time(f: GameFacts) -> datetime | None:
    played = f.stored.game.played_at
    if not played or len(played) <= 10:
        return None
    try:
        moment = datetime.fromisoformat(played)
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo else moment


def day_block(hour: int) -> int:
    return max(start for start in DAY_BLOCKS if start <= hour)
