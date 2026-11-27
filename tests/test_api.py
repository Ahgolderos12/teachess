import json
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from teachess.api.app import ApiConfig, create_app
from teachess.api.jobs import JobManager
from teachess.engine.models import Engine
from teachess.engine.stockfish import StockfishNotConfiguredError
from teachess.ingest import http
from tests.fakes import SCHOLAR_PGN, FakeAnthropic, ScriptedEngine, api_message, text_block

LICHESS_PGN = (
    '[Site "https://lichess.org/Abc12345"]\n[White "Bob"]\n[Black "alice"]\n[Result "1-0"]\n'
    '[UTCDate "2026.10.01"]\n[UTCTime "10:00:00"]\n[Opening "Scholar\'s Mate"]\n\n'
    + SCHOLAR_PGN
    + "\n"
)
FEN_BEFORE_NF6 = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


class InlineExecutor:
    """Runs jobs synchronously so tests are deterministic."""

    def submit(self, fn: Callable[..., Any], *args: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        future.set_result(fn(*args))
        return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        return None


def lichess_transport(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LICHESS_PGN)


def scripted_engine() -> AbstractContextManager[Engine]:
    return nullcontext(ScriptedEngine())


def no_stockfish() -> AbstractContextManager[Engine]:
    raise StockfishNotConfiguredError("STOCKFISH_PATH no está configurado.")


@pytest.fixture
def config(tmp_path: Path) -> ApiConfig:
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>teachess</html>")
    (web / "assets" / "app.js").write_text("console.log('ok')")
    (tmp_path / "secret.txt").write_text("secret")
    return ApiConfig(
        db_path=tmp_path / "web.sqlite",
        engine_depth=10,
        open_engine=scripted_engine,
        http_client=lambda: http.make_client(transport=httpx.MockTransport(lichess_transport)),
        stockfish_configured=True,
        model="claude-opus-5-5",
        effort="medium",
        default_users={"chesscom": None, "lichess": "alice"},
        static_dir=web,
        allowed_hosts=["testserver"],
        job_manager=JobManager(InlineExecutor()),  # type: ignore[arg-type]
    )


def make_client(config: ApiConfig) -> Iterator[TestClient]:
    with TestClient(create_app(config)) as client:
        yield client


@pytest.fixture
def client(config: ApiConfig) -> Iterator[TestClient]:
    yield from make_client(config)


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json()


def import_and_analyse(client: TestClient) -> dict[str, Any]:
    job = ok(client.post("/api/imports", json={"platform": "lichess", "analyze": True}), 202)
    assert job["status"] == "done", job
    return job


def test_status_on_empty_database(client: TestClient) -> None:
    status = ok(client.get("/api/status"))
    assert status["games"] == 0 and status["users"] == []
    assert status["stockfish"] is True
    assert status["coach"] == {
        "web_enabled": False,
        "model": "claude-opus-5-5",
        "mcp_command": "/mcp__teachess__coach",
    }


def test_import_then_analyse_in_one_job(client: TestClient) -> None:
    job = import_and_analyse(client)
    assert job["result"]["new"] == 1 and job["result"]["username"] == "alice"
    assert job["result"]["analysis"]["analyzed"] == 1
    assert ok(client.get(f"/api/jobs/{job['id']}"))["status"] == "done"

    again = ok(client.post("/api/imports", json={"platform": "lichess"}), 202)
    assert (again["result"]["new"], again["result"]["existing"]) == (0, 1)

    games = ok(client.get("/api/games"))["games"]
    assert len(games) == 1
    game = games[0]
    assert game["opponent"] == "Bob" and game["user_result"] == "loss"
    assert game["opening"] == "Scholar's Mate"
    assert game["summary"]["counts"] == {"inaccuracy": 0, "mistake": 0, "blunder": 1}
    assert ok(client.get("/api/games", params={"user": "nobody"}))["games"] == []
    assert ok(client.get("/api/status"))["users"] == ["alice"]


def test_import_validation_and_failures(config: ApiConfig, client: TestClient) -> None:
    assert client.post("/api/imports", json={"platform": "chesscom"}).status_code == 400
    assert client.post("/api/imports", json={"platform": "pgn", "user": "x"}).status_code == 400
    assert client.post("/api/imports", json={"platform": "xyz"}).status_code == 422

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    broken = replace(
        config, http_client=lambda: http.make_client(transport=httpx.MockTransport(failing))
    )
    for broken_client in make_client(broken):
        job = ok(broken_client.post("/api/imports", json={"platform": "lichess"}), 202)
        assert job["status"] == "error" and job["error"]


def test_import_pgn_text(client: TestClient) -> None:
    body = {"platform": "pgn", "user": "Me", "pgn": SCHOLAR_PGN, "color": "white"}
    job = ok(client.post("/api/imports", json=body), 202)
    assert job["result"]["new"] == 1
    game = ok(client.get("/api/games"))["games"][0]
    assert game["platform"] == "pgn" and game["user_color"] == "white"
    assert game["summary"] is None  # not analysed


def test_analysis_without_stockfish_keeps_the_import(config: ApiConfig) -> None:
    for no_engine in make_client(replace(config, open_engine=no_stockfish)):
        job = ok(no_engine.post("/api/imports", json={"platform": "lichess", "analyze": True}), 202)
        assert job["status"] == "done" and job["result"]["new"] == 1
        assert "STOCKFISH_PATH" in job["result"]["analysis_error"]
        failed = ok(no_engine.post("/api/analyses", json={"user": "alice"}), 202)
        assert failed["status"] == "error" and "STOCKFISH_PATH" in failed["error"]


def test_analyses(client: TestClient) -> None:
    ok(client.post("/api/imports", json={"platform": "lichess"}), 202)
    job = ok(client.post("/api/analyses", json={"user": "alice", "depth": 12}), 202)
    assert job["result"] == {"analyzed": 1, "depth": 12, "game_ids": [1]}
    assert client.post("/api/analyses", json={"user": "alice"}).status_code == 409
    assert client.post("/api/analyses", json={"game_id": 1}).status_code == 409
    redo = ok(client.post("/api/analyses", json={"game_id": 1, "reanalyze": True}), 202)
    assert redo["result"]["analyzed"] == 1
    assert client.post("/api/analyses", json={"game_id": 99}).status_code == 404
    assert client.post("/api/analyses", json={}).status_code == 422
    assert client.post("/api/analyses", json={"game_id": 1, "user": "a"}).status_code == 422


def test_game_detail(client: TestClient) -> None:
    ok(client.post("/api/imports", json={"platform": "lichess"}), 202)
    unanalysed = ok(client.get("/api/games/1"))
    assert [m["san"] for m in unanalysed["moves"]][-1] == "Qxf7#"
    assert all(m["analysis"] is None for m in unanalysed["moves"])

    ok(client.post("/api/analyses", json={"game_id": 1}), 202)
    game = ok(client.get("/api/games/1"))
    assert game["start_fen"].startswith("rnbqkbnr/pppppppp")
    assert game["start_eval"]["text"] == "+0.30"
    moves = game["moves"]
    assert len(moves) == 7
    nf6 = moves[5]
    assert (nf6["label"], nf6["san"], nf6["by_user"], nf6["color"]) == (
        "3...",
        "Nf6",
        True,
        "black",
    )
    assert nf6["fen_before"] == FEN_BEFORE_NF6
    assert nf6["analysis"]["classification"] == "blunder"
    assert nf6["analysis"]["best_move_san"] == "g6"
    assert nf6["analysis"]["best_move_uci"] == "g7g6"
    assert nf6["analysis"]["eval_after"]["white_win_pct"] == 100.0
    assert moves[0]["clock_seconds"] == 600.0
    assert moves[-1]["analysis"]["eval_after"]["text"] == "1-0"
    assert client.get("/api/games/42").status_code == 404


def test_user_report(client: TestClient) -> None:
    import_and_analyse(client)
    report = ok(client.get("/api/users/ALICE/report"))
    assert report["known_user"] is True
    assert report["games_analyzed"] == 1 and report["games_pending"] == 0
    assert report["counts"]["blunder"] == 1
    assert report["by_phase"]["opening"]["blunder"] == 1
    assert report["results"]["loss"] == 1
    assert [g["id"] for g in report["worst_games"]] == [1]
    assert ok(client.get("/api/users/nobody/report"))["known_user"] is False


def test_user_stats_and_diagnosis(client: TestClient) -> None:
    import_and_analyse(client)
    stats = ok(client.get("/api/users/ALICE/stats"))
    assert stats["user"] == "alice" and stats["games_analysed"] == 1
    assert stats["summary"]["record"]["losses"] == 1
    assert stats["errors"]["counts"]["blunder"] == 1
    assert stats["terminations"]["loss"] == {"checkmate": 1}
    assert stats["openings"][0]["opening"] == "Scholar's Mate"
    assert [p["game_id"] for p in stats["timeline"]] == [1]
    diagnosis = ok(client.get("/api/users/alice/diagnosis?window=10"))
    assert diagnosis["window"]["games"] == 1 and diagnosis["notes"]
    assert client.get("/api/users/nobody/stats").status_code == 404
    assert client.get("/api/users/alice/diagnosis?window=1").status_code == 422


def test_engine_endpoints(config: ApiConfig, client: TestClient) -> None:
    evaluation = ok(client.post("/api/engine/evaluate", json={"fen": FEN_BEFORE_NF6}))
    assert evaluation["best_move"] == "g6" and evaluation["eval"] == "-1.00"
    move = ok(client.post("/api/engine/move", json={"fen": FEN_BEFORE_NF6, "move": "f8c5"}))
    assert move["move"] == "Bc5" and move["fen_after"].startswith("r1bqk1nr")
    bad = client.post("/api/engine/move", json={"fen": FEN_BEFORE_NF6, "move": "Ke3"})
    assert bad.status_code == 400 and "Jugadas legales" in bad.json()["detail"]
    assert client.post("/api/engine/evaluate", json={"fen": "nope"}).status_code == 400
    missing_game = client.post("/api/engine/evaluate", json={"fen": FEN_BEFORE_NF6, "game_id": 7})
    assert missing_game.status_code == 400

    for no_engine in make_client(replace(config, open_engine=no_stockfish)):
        uncached = "4k3/8/8/8/8/8/8/4K2R w K - 0 1"  # FEN_BEFORE_NF6 is cached by now
        response = no_engine.post("/api/engine/evaluate", json={"fen": uncached})
        assert response.status_code == 503 and "STOCKFISH_PATH" in response.json()["detail"]


def test_coach_is_off_without_api_key(client: TestClient) -> None:
    import_and_analyse(client)
    response = client.post("/api/coach/sessions", json={"game_id": 1})
    assert response.status_code == 403
    assert "/mcp__teachess__coach 1" in response.json()["detail"]


def test_coach_streams_answers_with_api_key(config: ApiConfig) -> None:
    fake = FakeAnthropic(api_message(text_block("Hola, "), text_block("revisemos 3...Nf6.")))
    enabled = replace(config, anthropic_client=lambda: fake)  # type: ignore[arg-type,return-value]
    for client in make_client(enabled):
        assert ok(client.get("/api/status"))["coach"]["web_enabled"] is True
        assert client.post("/api/coach/sessions", json={"game_id": 1}).status_code == 404
        import_and_analyse(client)
        session = ok(client.post("/api/coach/sessions", json={"game_id": 1}), 201)["session_id"]

        response = client.post(f"/api/coach/sessions/{session}/messages", json={"text": "¿Y?"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line]
        assert [e["type"] for e in events] == ["text", "text", "done"]
        assert "".join(e.get("text", "") for e in events) == "Hola, revisemos 3...Nf6."
        assert events[-1]["refused"] is False and events[-1]["usage"]["input_tokens"] == 100

        empty = client.post(f"/api/coach/sessions/{session}/messages", json={"text": ""})
        assert empty.status_code == 422
        unknown = client.post("/api/coach/sessions/zzz/messages", json={"text": "hola"})
        assert unknown.status_code == 404


def test_coach_api_errors_are_streamed(config: ApiConfig) -> None:
    class NoCredentials(FakeAnthropic):
        def _stream(self, **kwargs: Any) -> Any:
            raise TypeError("Could not resolve authentication method.")

    enabled = replace(config, anthropic_client=NoCredentials)  # type: ignore[arg-type]
    for client in make_client(enabled):
        import_and_analyse(client)
        session = ok(client.post("/api/coach/sessions", json={"game_id": 1}), 201)["session_id"]
        response = client.post(f"/api/coach/sessions/{session}/messages", json={"text": "hola"})
        event = json.loads(response.text.strip()[6:])
        assert event["type"] == "error" and "ANTHROPIC_API_KEY" in event["message"]


def test_web_app_and_unknown_routes(client: TestClient) -> None:
    assert client.get("/").text == "<html>teachess</html>"
    assert client.get("/games/3").text == "<html>teachess</html>"  # client-side route
    assert client.get("/assets/app.js").text == "console.log('ok')"
    assert "secret" not in client.get("/../secret.txt").text
    assert "secret" not in client.get("/%2e%2e/secret.txt").text
    unknown = client.get("/api/nothing")
    assert unknown.status_code == 404 and "desconocida" in unknown.json()["detail"]
    assert client.get("/api/jobs/missing").status_code == 404


def test_web_not_built(config: ApiConfig) -> None:
    for client in make_client(replace(config, static_dir=config.db_path.parent / "missing")):
        response = client.get("/")
        assert response.status_code == 404 and "npm run build" in response.json()["detail"]
        assert client.get("/api/status").status_code == 200


def test_rejects_unknown_hosts(client: TestClient) -> None:
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400


def test_sync_imports_and_analyses_new_games(config: ApiConfig) -> None:
    for client in make_client(config):
        status = ok(client.get("/api/sync"))
        assert status["configured"] is True and status["users"] == {"lichess": "alice"}
        assert status["interval_hours"] is None and status["job"] is None  # manual only
        job = ok(client.post("/api/sync"), 202)
        assert job["kind"] == "sync" and job["status"] == "done"
        assert job["result"]["new"] == 1 and job["result"]["analyzed"] == 1
        assert ok(client.get("/api/sync"))["job"]["id"] == job["id"]
        again = ok(client.post("/api/sync"), 202)
        assert again["result"]["new"] == 0 and again["result"]["analyzed"] == 0


def test_sync_needs_a_configured_player(config: ApiConfig) -> None:
    for client in make_client(replace(config, default_users={"chesscom": None})):
        assert ok(client.get("/api/sync"))["configured"] is False
        assert client.post("/api/sync").status_code == 400


def test_sync_reports_platform_errors(config: ApiConfig) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    broken = replace(
        config, http_client=lambda: http.make_client(transport=httpx.MockTransport(failing))
    )
    for client in make_client(broken):
        job = ok(client.post("/api/sync"), 202)
        assert job["status"] == "error" and "alice" in job["error"]


def test_stats_filters(client: TestClient) -> None:
    import_and_analyse(client)
    filtered = ok(client.get("/api/users/alice/stats", params={"color": "black"}))
    assert filtered["filter"] == {"color": "black"}
    assert filtered["summary"]["record"]["games"] == 1
    by_hour = ok(client.get("/api/users/alice/stats", params={"day_block": 18}))
    assert by_hour["filter"] == {"day_block": 18}  # the count depends on the local time zone
    assert filtered["options"]["openings"] == ["Scholar's Mate"]
    empty = ok(client.get("/api/users/alice/stats", params={"color": "white"}))
    assert empty["summary"]["record"]["games"] == 0 and empty["timeline"] == []
    assert empty["options"]["games"] == 1  # options always cover every game
    for bad in ({"day_block": 5}, {"since": "ayer"}, {"color": "red"}):
        assert client.get("/api/users/alice/stats", params=bad).status_code == 422
