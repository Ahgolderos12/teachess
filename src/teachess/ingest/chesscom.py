"""Chess.com published-data API: monthly archives of a player's games."""

from datetime import UTC, datetime
from typing import Any

import httpx

from teachess.ingest import http
from teachess.ingest.models import ImportedGame
from teachess.ingest.pgn_file import FetchResult, parse_games, user_color

BASE_URL = "https://api.chess.com/pub"


def fetch_games(client: httpx.Client, username: str, max_games: int) -> FetchResult:
    """Newest games first, walking monthly archives backwards until max_games."""
    not_found = f"El usuario «{username}» no existe en Chess.com."
    archives: list[str] = http.get(
        client,
        f"{BASE_URL}/player/{username.lower()}/games/archives",
        not_found_message=not_found,
    ).json()["archives"]

    result = FetchResult()
    for archive_url in reversed(archives):
        month: list[dict[str, Any]] = http.get(
            client, archive_url, not_found_message=not_found
        ).json()["games"]
        for raw in reversed(month):  # each archive is in chronological order
            if len(result.games) >= max_games:
                return result
            game = _to_imported(raw, username)
            if game is None:
                result.skipped += 1
            else:
                result.games.append(game)
    return result


def _to_imported(raw: dict[str, Any], username: str) -> ImportedGame | None:
    if raw.get("rules") != "chess" or not raw.get("pgn") or not raw.get("url"):
        return None
    parsed = next(parse_games(raw["pgn"]), None)
    if parsed is None:
        return None
    side = user_color(parsed, username)
    if side is None:
        return None
    end_time = raw.get("end_time")
    return ImportedGame(
        platform="chesscom",
        external_id=raw["url"].rstrip("/").split("/game/", 1)[-1],
        username=username,
        user_color=side,
        white=parsed.headers.get("White", "?"),
        black=parsed.headers.get("Black", "?"),
        result=parsed.headers.get("Result", "*"),
        time_control=raw.get("time_control"),
        played_at=(
            datetime.fromtimestamp(end_time, UTC).isoformat(timespec="seconds")
            if end_time
            else None
        ),
        url=raw["url"],
        pgn=str(parsed),
    )
