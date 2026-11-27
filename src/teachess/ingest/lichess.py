"""Lichess games export: GET /api/games/user/{username} (PGN, newest first)."""

import httpx

from teachess.ingest import http
from teachess.ingest.models import ImportedGame
from teachess.ingest.pgn_file import FetchResult, parse_games, pgn_date, user_color

BASE_URL = "https://lichess.org"


def fetch_games(client: httpx.Client, username: str, max_games: int) -> FetchResult:
    response = http.get(
        client,
        f"{BASE_URL}/api/games/user/{username}",
        params={
            "max": max_games,
            "clocks": "true",
            "opening": "true",
            "finished": "true",
            "sort": "dateDesc",
        },
        headers={"Accept": "application/x-chess-pgn"},
        not_found_message=f"El usuario «{username}» no existe en Lichess.",
    )
    result = FetchResult()
    for game in parse_games(response.text):
        side = user_color(game, username) if game else None
        site = game.headers.get("Site", "") if game else ""
        if game is None or side is None or not site:
            result.skipped += 1
            continue
        result.games.append(
            ImportedGame(
                platform="lichess",
                external_id=site.rstrip("/").rsplit("/", 1)[-1],
                username=username,
                user_color=side,
                white=game.headers.get("White", "?"),
                black=game.headers.get("Black", "?"),
                result=game.headers.get("Result", "*"),
                time_control=game.headers.get("TimeControl"),
                played_at=_played_at(pgn_date(game), game.headers.get("UTCTime")),
                url=site,
                pgn=str(game),
            )
        )
    return result


def _played_at(date: str | None, time: str | None) -> str | None:
    if date is None:
        return None
    return f"{date}T{time}+00:00" if time else date
