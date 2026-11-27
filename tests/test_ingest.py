from pathlib import Path

import httpx
import pytest

from teachess.ingest import chesscom, http, lichess
from teachess.ingest.pgn_file import load_pgn_file

FIXTURES = Path(__file__).parent / "fixtures"
LICHESS_PGN = (FIXTURES / "lichess_alice.pgn").read_text(encoding="utf-8")


# --- shared HTTP helper -------------------------------------------------------


def test_get_retries_once_after_rate_limit() -> None:
    calls: list[str] = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["User-Agent"])
        return httpx.Response(429 if len(calls) == 1 else 200, text="ok")

    client = http.make_client(transport=httpx.MockTransport(handler))
    response = http.get(client, "https://example.org/x", sleep=waits.append)
    assert response.text == "ok"
    assert waits == [http.RATE_LIMIT_WAIT_SECONDS]
    assert calls[0].startswith("teachess/")


def test_get_maps_404_to_ingest_error() -> None:
    client = http.make_client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(http.IngestError, match="no existe"):
        http.get(client, "https://example.org/x", not_found_message="no existe")


def test_get_maps_network_error_to_ingest_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = http.make_client(transport=httpx.MockTransport(handler))
    with pytest.raises(http.IngestError, match="No se pudo conectar"):
        http.get(client, "https://example.org/x")


# --- Lichess -------------------------------------------------------------------


def test_lichess_fetch_parses_valid_games_and_skips_others() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=LICHESS_PGN)

    client = http.make_client(transport=httpx.MockTransport(handler))
    result = lichess.fetch_games(client, "alice", max_games=10)

    request = seen[0]
    assert request.url.path == "/api/games/user/alice"
    assert request.url.params["max"] == "10"
    assert request.url.params["clocks"] == "true"
    assert request.headers["Accept"] == "application/x-chess-pgn"

    assert [g.external_id for g in result.games] == ["AbCd1234", "EfGh5678"]
    assert result.skipped == 2  # illegal move + atomic variant
    first, second = result.games
    assert first.user_color == "white"
    assert first.played_at == "2026-10-01T10:00:00+00:00"
    assert first.url == "https://lichess.org/AbCd1234"
    assert "[%clk 0:09:45]" in first.pgn
    assert second.user_color == "black"
    assert second.result == "0-1"


# --- Chess.com -----------------------------------------------------------------

SCHOLAR_PGN = (
    '[White "Alice"]\n[Black "Bob"]\n[Result "1-0"]\n\n'
    "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n"
)
FOOLS_PGN = '[White "Dave"]\n[Black "Alice"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n'


def chesscom_game(game_id: int, pgn: str, *, rules: str = "chess") -> dict[str, object]:
    return {
        "url": f"https://www.chess.com/game/live/{game_id}",
        "pgn": pgn,
        "time_control": "600",
        "end_time": 1_790_000_000 + game_id,
        "rules": rules,
    }


def test_chesscom_walks_archives_newest_first_until_max() -> None:
    base = "https://api.chess.com/pub/player/alice/games"
    pages = {
        "/pub/player/alice/games/archives": {"archives": [f"{base}/2026/09", f"{base}/2026/10"]},
        "/pub/player/alice/games/2026/10": {
            "games": [
                chesscom_game(3, SCHOLAR_PGN),
                chesscom_game(4, FOOLS_PGN, rules="chess960"),
                chesscom_game(5, FOOLS_PGN),
            ]
        },
        "/pub/player/alice/games/2026/09": {
            "games": [chesscom_game(1, SCHOLAR_PGN), chesscom_game(2, SCHOLAR_PGN)]
        },
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json=pages[request.url.path])

    client = http.make_client(transport=httpx.MockTransport(handler))
    result = chesscom.fetch_games(client, "Alice", max_games=3)

    assert [g.external_id for g in result.games] == ["live/5", "live/3", "live/2"]
    assert result.skipped == 1
    assert [g.user_color for g in result.games] == ["black", "white", "white"]
    assert result.games[0].played_at == "2026-09-21T14:13:25+00:00"
    assert result.games[0].time_control == "600"
    assert requested[0].endswith("/archives")


def test_chesscom_unknown_user() -> None:
    client = http.make_client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(http.IngestError, match="Chess.com"):
        chesscom.fetch_games(client, "nobody", max_games=5)


# --- local PGN file ------------------------------------------------------------


def test_pgn_file_matches_user_by_name(tmp_path: Path) -> None:
    path = tmp_path / "otb.pgn"
    path.write_text(SCHOLAR_PGN + "\n" + FOOLS_PGN, encoding="utf-8")
    result = load_pgn_file(path, "alice")
    assert [g.user_color for g in result.games] == ["white", "black"]
    assert all(g.platform == "pgn" for g in result.games)
    # Same content, same id: re-importing the file must not duplicate games.
    assert load_pgn_file(path, "alice").games[0].external_id == result.games[0].external_id


def test_pgn_file_color_override_and_unknown_player(tmp_path: Path) -> None:
    path = tmp_path / "otb.pgn"
    path.write_text(SCHOLAR_PGN, encoding="utf-8")
    assert load_pgn_file(path, "zoe").skipped == 1
    forced = load_pgn_file(path, "zoe", color="black")
    assert forced.games[0].user_color == "black"
