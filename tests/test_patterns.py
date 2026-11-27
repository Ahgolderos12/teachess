"""Player diagnosis over synthetic games: every pattern built from known evaluations."""

from collections.abc import Sequence

import chess
import pytest

from teachess.db.repository import StoredGame
from teachess.engine.models import MoveAnalysis, PositionEval
from teachess.engine.scoring import classify
from teachess.ingest.models import ImportedGame
from teachess.patterns.diagnosis import (
    diagnose,
    early_losses,
    failed_conversions,
    hasty_errors,
    time_trouble,
    weak_openings,
    weak_phase,
)
from teachess.patterns.facts import (
    GameFacts,
    build_game_facts,
    opening_family,
    outcome_for,
    parse_termination,
    parse_time_control,
)

DANCE = ["Nf3", "Nf6", "Ng1", "Ng8"]  # legal forever: lets us build games of any length
EVEN, LOST, WON = 0, -600, 600  # White's eval in centipawns (±600 ≈ 90 % win probability)


def build(
    game_id: int,
    *,
    user_color: str = "white",
    result: str = "0-1",
    plies: int = 40,
    evals: dict[int, int] | None = None,
    losses: dict[int, float] | None = None,
    clocks: dict[int, float] | None = None,
    termination: str = "Black won by resignation",
    opening: str = "Italian-Game",
    time_control: str = "600",
    played_at: str = "2026-11-01",
) -> GameFacts:
    """A game of knight moves whose evaluations and losses are scripted per ply.

    `evals[ply]` is White's eval after that ply and holds until the next scripted ply.
    """
    board = chess.Board()
    moves: list[MoveAnalysis] = []
    current = EVEN
    evals = evals or {}
    for ply in range(1, plies + 1):
        san = DANCE[(ply - 1) % 4]
        before = PositionEval(cp=current, mate=None, best_move=None, pv=(), depth=10)
        current = evals.get(ply, current)
        loss = (losses or {}).get(ply, 0.0)
        fen = board.fen()
        move = board.push_san(san)
        moves.append(
            MoveAnalysis(
                ply=ply,
                san=san,
                uci=move.uci(),
                fen_before=fen,
                eval_before=before,
                eval_after=PositionEval(cp=current, mate=None, best_move=None, pv=(), depth=10),
                best_move_san="e4",
                cp_loss=0,
                win_loss=loss,
                classification=classify(loss),
                phase="opening" if ply <= 20 else "middlegame",
                clock_seconds=(clocks or {}).get(ply),
            )
        )
    movetext = " ".join(
        f"{i // 2 + 1}. {m.san}" if i % 2 == 0 else m.san for i, m in enumerate(moves)
    )
    pgn = (
        f'[Termination "{termination}"]\n'
        f'[ECOUrl "https://www.chess.com/openings/{opening}"]\n'
        f'[WhiteElo "1000"]\n[BlackElo "1100"]\n\n{movetext} {result}'
    )
    game = ImportedGame(
        platform="chesscom",
        external_id=str(game_id),
        username="alice",
        user_color=user_color,  # type: ignore[arg-type]
        white="alice" if user_color == "white" else "bob",
        black="bob" if user_color == "white" else "alice",
        result=result,
        time_control=time_control,
        played_at=played_at,
        url=None,
        pgn=pgn,
    )
    stored = StoredGame(id=game_id, game=game, imported_at="", analyzed_depth=10)
    return build_game_facts(stored, moves)


def early_blunder(game_id: int) -> GameFacts:
    """White blunders on move 6 (ply 11) and never recovers."""
    return build(game_id, evals={11: LOST}, losses={11: 45.0})


# --- facts ----------------------------------------------------------------------


def test_parsing_helpers() -> None:
    assert parse_time_control("600+5") == (600, 5)
    assert parse_time_control("300") == (300, 0)
    assert parse_time_control("1/86400") == (None, 0)
    assert outcome_for("0-1", "black") == "win"
    assert outcome_for("1-0", "black") == "loss"
    assert outcome_for("*", "white") is None
    board = chess.Board()
    assert parse_termination("alice won on time", board) == "time"
    assert parse_termination("Time forfeit", board) == "time"
    assert parse_termination("Game drawn by timeout vs insufficient material", board) == (
        "insufficient"
    )
    assert parse_termination("bob won by resignation", board) == "resignation"
    assert opening_family("Sicilian Defense Alapin Variation 2...d5") == "Sicilian Defense"
    assert opening_family("Kings Pawn Opening 2.Nf3") == "Kings Pawn Opening"
    assert opening_family("Ruy Lopez 3...a6") == "Ruy Lopez"
    assert opening_family(None) is None


def test_game_facts() -> None:
    facts = build(1, clocks={1: 590.0, 3: 560.0}, time_control="600+5")
    assert facts.outcome == "loss" and facts.termination == "resignation"
    assert (facts.base_seconds, facts.increment) == (600, 5)
    assert facts.opening_family == "Italian Game"
    assert (facts.user_elo, facts.opponent_elo) == (1000, 1100)
    assert facts.full_moves == 20
    first, second = facts.user_moves[:2]
    assert first.seconds_spent == 15.0  # 600 - 590 + 5
    assert second.seconds_spent == 35.0  # 590 - 560 + 5


def test_decisive_error_is_the_first_error_that_never_recovers() -> None:
    assert early_blunder(1).decisive_error() is not None
    facts = early_blunder(1).decisive_error()
    assert facts is not None and facts.move_number == 6
    # A blunder followed by a comeback is not decisive; the later one is.
    game = build(2, evals={11: LOST, 15: EVEN, 31: LOST}, losses={11: 45.0, 31: 40.0})
    decisive = game.decisive_error()
    assert decisive is not None and decisive.move_number == 16
    # Won games have no decisive error.
    assert build(3, result="1-0", evals={11: LOST}, losses={11: 45.0}).decisive_error() is None


# --- detectors --------------------------------------------------------------------


def test_early_losses() -> None:
    games = [early_blunder(1), early_blunder(2), build(3, result="1-0")]
    finding = early_losses(games)
    assert finding is not None
    assert finding.games == (1, 2) and finding.points_lost == 2.0
    assert finding.metrics["decisive_move_numbers"] == [6, 6]
    assert finding.evidence[0]["move"] == "6.Ng1"
    assert early_losses(games[1:]) is None  # one game is not a pattern


def test_time_trouble() -> None:
    on_time = build(1, termination="bob won on time")
    low_clock = build(2, evals={31: LOST}, losses={31: 40.0}, clocks={31: 30.0})
    plenty = build(3, evals={31: LOST}, losses={31: 40.0}, clocks={31: 300.0})
    finding = time_trouble([on_time, low_clock, plenty])
    assert finding is not None
    assert finding.games == (1, 2)
    assert finding.metrics["losses_on_time"] == 1
    assert finding.metrics["decisive_errors_low_clock"] == 1


def test_hasty_errors() -> None:
    clocks = {ply: 600.0 - ply for ply in range(1, 41)}  # one second per move
    game_a = build(1, losses={21: 25.0, 25: 25.0}, clocks=clocks)
    game_b = build(2, evals={21: LOST}, losses={21: 45.0}, clocks=clocks)
    finding = hasty_errors([game_a, game_b])
    assert finding is not None
    assert finding.metrics["hasty_serious_errors"] == 3
    assert finding.metrics["decided_games"] == 1 and finding.points_lost == 1.0
    assert finding.evidence[0]["win_loss_pct"] == 45.0  # worst first
    slow = {ply: 600.0 - 10 * ply for ply in range(1, 41)}  # 20 s per own move: not hasty
    assert hasty_errors([build(3, losses={21: 25.0, 25: 25.0, 29: 25.0}, clocks=slow)]) is None


def test_failed_conversions() -> None:
    thrown = {21: WON, 31: LOST}
    games = [
        build(1, evals=thrown, losses={31: 60.0}),
        build(2, result="1/2-1/2", evals={21: WON, 31: EVEN}, losses={31: 40.0}),
        build(3, evals={21: WON, 23: EVEN}),  # winning for a single move only: not counted
    ]
    finding = failed_conversions(games)
    assert finding is not None
    assert finding.games == (1, 2) and finding.points_lost == 1.5
    assert finding.metrics == {"games": 2, "losses": 1, "draws": 1}
    assert finding.evidence[0]["move"] == "16.Ng1"
    assert finding.evidence[0]["winning_since"] == "11.Nf3"


def test_weak_phase() -> None:
    errors = {ply: 25.0 for ply in (23, 27, 31, 35)}  # all in the middlegame
    games = [build(i, losses=errors) for i in (1, 2)]
    finding = weak_phase(games)
    assert finding is not None and finding.metrics["phase"] == "middlegame"
    assert finding.metrics["by_phase"]["middlegame"]["serious_errors"] == 8
    assert finding.metrics["by_phase"]["opening"]["serious_errors"] == 0


def test_weak_openings_only_counts_early_decisions_as_points() -> None:
    games = [early_blunder(1), build(2), build(3), build(4, opening="Sicilian-Defense")]
    finding = weak_openings(games)
    assert finding is not None
    assert finding.metrics["openings"][0]["opening"] == "Italian Game"
    assert finding.games == (1, 2, 3)
    assert finding.points_lost == 1.0  # only game 1 was decided in the opening
    assert finding.evidence[0]["game_id"] == 1


@pytest.mark.parametrize("window", [2, 20])
def test_diagnose_ranks_findings_and_uses_the_window(window: int) -> None:
    games: Sequence[GameFacts] = [early_blunder(i) for i in range(1, 6)]
    result = diagnose(list(games), window=window)
    assert result["window"]["games"] == min(window, 5)
    assert result["overview"]["record"]["losses"] == min(window, 5)
    points = [f["points_lost"] for f in result["findings"]]
    assert points == sorted(points, reverse=True)
    assert result["findings"][0]["kind"] in ("early_losses", "weak_openings")
    assert any("orientativos" in note for note in result["notes"])


def test_player_stats() -> None:
    from teachess.patterns.stats import player_stats

    clocks = {ply: 600.0 - ply for ply in range(1, 41)}
    games = [
        build(3, result="1-0", played_at="2026-11-03T20:00:00+00:00", clocks=clocks),
        build(2, evals={21: WON, 31: LOST}, losses={31: 60.0}, played_at="2026-11-02"),
        early_blunder(1),
    ]
    stats = player_stats(games)
    assert stats["summary"]["record"] == {
        "games": 3, "wins": 1, "draws": 0, "losses": 2, "points": 1.0, "score_pct": 33,
    }  # fmt: skip
    assert stats["summary"]["streaks"]["current"] == {"outcome": "win", "games": 1}
    assert stats["summary"]["streaks"]["longest_loss"] == 2
    assert stats["summary"]["ratings"][0]["time_class"] == "rapid"
    assert stats["errors"]["counts"]["blunder"] == 2
    assert stats["conversion"]["winning_games"] == 1 and stats["conversion"]["converted"] == 0
    assert stats["decisive_errors"]["with_decisive_error"] == 2
    assert stats["openings"][0]["decided_early"] == 1
    assert [p["game_id"] for p in stats["timeline"]] == [1, 2, 3]  # oldest first
    assert [b["moves"] for b in stats["time"]["think_time"]][:2] == [1, 19]  # 2 s per own move
    assert sum(row["games"] for row in stats["results"]["by_time_of_day"]) == 1


def test_pre_game_ratings_are_estimated_for_chesscom() -> None:
    from dataclasses import replace as dc_replace

    from teachess.patterns.facts import estimate_pre_game_ratings

    def rated(game_id: int, result: str, user_after: int, rival_after: int, day: str) -> GameFacts:
        facts = build(game_id, result=result, played_at=f"2026-11-{day}T10:00:00+00:00")
        return dc_replace(facts, user_elo=user_after, opponent_elo=rival_after)

    games = [  # newest first, as load_facts returns them
        rated(3, "0-1", 1000, 1010, "03"),  # lost 8 after the previous game's 1008
        rated(2, "1-0", 1008, 990, "02"),  # won 8 after 1000
        rated(1, "1-0", 1000, 984, "01"),  # first game: estimated with the Elo formula
    ]
    first, second, third = reversed(estimate_pre_game_ratings(games))
    assert (second.user_elo_before, second.opponent_elo_before) == (1000, 998)
    assert (third.user_elo_before, third.opponent_elo_before) == (1008, 1002)
    assert first.user_elo_before is not None and 990 < first.user_elo_before < 1000  # won: gained
    assert first.opponent_elo_before == 984 + (1000 - first.user_elo_before)
    # Lichess PGNs already carry pre-game ratings.
    lichess = dc_replace(
        games[0],
        stored=dc_replace(
            games[0].stored, game=dc_replace(games[0].stored.game, platform="lichess")
        ),
    )
    assert estimate_pre_game_ratings([lichess])[0].user_elo_before is None  # left as built


def test_game_filter() -> None:
    from teachess.patterns.filters import GameFilter

    games = [
        build(
            4,
            user_color="black",
            result="0-1",
            opening="Sicilian-Defense-Alapin",
            played_at="2026-11-04",
        ),
        build(3, played_at="2026-11-03", termination="bob won on time"),
        build(2, result="1/2-1/2", time_control="180", played_at="2026-11-02"),
        build(1, result="1-0", played_at="2026-11-01"),
    ]

    def ids(**kwargs: object) -> list[int]:
        return [f.game_id for f in GameFilter(**kwargs).apply(games)]  # type: ignore[arg-type]

    assert ids() == [4, 3, 2, 1]
    assert ids(color="black") == [4] and ids(outcome="win") == [4, 1]
    assert ids(opening="sicilian") == [4] and ids(termination="time") == [3]
    assert ids(time_class="blitz") == [2] and ids(time_control="600") == [4, 3, 1]
    assert ids(since="2026-11-02", until="2026-11-03") == [3, 2]
    assert ids(last=2) == [4, 3] and ids(last=2, offset=2) == [2, 1]
    assert ids(outcome="win", last=1, offset=1) == [1]  # last/offset apply after the rest
    assert GameFilter().is_empty() and GameFilter(color="white").to_dict() == {"color": "white"}
