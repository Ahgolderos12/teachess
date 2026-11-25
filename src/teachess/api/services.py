"""Import and analysis work run by background jobs. Each run opens its own resources."""

import io
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from pathlib import Path
from typing import Any

import chess.pgn
import httpx

from teachess.api.jobs import JobError, Progress
from teachess.db import repository as repo
from teachess.engine.analysis import PersistentCacheEngine, analyse_game
from teachess.engine.models import Engine
from teachess.engine.stockfish import StockfishNotConfiguredError
from teachess.ingest import chesscom, http, lichess
from teachess.ingest.models import Color, Platform
from teachess.ingest.pgn_file import FetchResult, load_pgn_text

HttpClientFactory = Callable[[], httpx.Client]
EngineFactory = Callable[[], AbstractContextManager[Engine]]


def import_games(
    db_path: Path,
    http_client: HttpClientFactory,
    platform: Platform,
    username: str,
    max_games: int,
    pgn: str | None,
    color: Color | None,
    progress: Progress,
) -> dict[str, Any]:
    progress(0, 0, "Descargando partidas…" if platform != "pgn" else "Leyendo el PGN…")
    fetched = _fetch(http_client, platform, username, max_games, pgn, color)
    with closing(repo.connect(db_path)) as conn:
        new = 0
        for index, game in enumerate(fetched.games, start=1):
            new += repo.insert_game(conn, game)
            progress(index, len(fetched.games), "Guardando partidas…")
    return {
        "username": username,
        "new": new,
        "existing": len(fetched.games) - new,
        "skipped": fetched.skipped,
    }


def _fetch(
    http_client: HttpClientFactory,
    platform: Platform,
    username: str,
    max_games: int,
    pgn: str | None,
    color: Color | None,
) -> FetchResult:
    try:
        if platform == "pgn":
            if not pgn or not pgn.strip():
                raise JobError("El PGN está vacío.")
            return load_pgn_text(pgn, username, color)
        fetch = chesscom.fetch_games if platform == "chesscom" else lichess.fetch_games
        with http_client() as client:
            return fetch(client, username, max_games)
    except http.IngestError as exc:
        raise JobError(str(exc)) from None


def analyse_games(
    db_path: Path,
    open_engine: EngineFactory,
    game_ids: list[int],
    depth: int,
    progress: Progress,
) -> dict[str, Any]:
    total = len(game_ids)
    progress(0, total, "Arrancando Stockfish…")
    analysed = 0
    try:
        with closing(repo.connect(db_path)) as conn, open_engine() as stockfish:
            engine = PersistentCacheEngine(stockfish, conn)
            for index, game_id in enumerate(game_ids, start=1):
                progress(index - 1, total, f"Analizando partida {index} de {total}…")
                stored = repo.get_game(conn, game_id)
                parsed = chess.pgn.read_game(io.StringIO(stored.game.pgn)) if stored else None
                if parsed is None:
                    continue
                moves = analyse_game(parsed, engine, depth)
                repo.save_move_analysis(conn, game_id, moves, depth)
                analysed += 1
    except StockfishNotConfiguredError as exc:
        raise JobError(str(exc)) from None
    progress(total, total, "Análisis terminado.")
    return {"analyzed": analysed, "depth": depth, "game_ids": game_ids}
