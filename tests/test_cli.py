from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from teachess import cli
from teachess.config import Settings
from teachess.db import repository as repo
from teachess.engine.models import Engine
from teachess.engine.stockfish import StockfishNotConfiguredError
from teachess.ingest import http
from tests.fakes import (
    SCHOLAR_PGN,
    FakeAnthropic,
    ScriptedEngine,
    api_message,
    text_block,
    tool_block,
)

LICHESS_PGN = (
    '[Site "https://lichess.org/Abc12345"]\n[White "Bob"]\n[Black "alice"]\n[Result "1-0"]\n'
    '[UTCDate "2026.10.01"]\n[UTCTime "10:00:00"]\n\n' + SCHOLAR_PGN + "\n"
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("TEACHESS_DB", str(db_path))
    monkeypatch.setenv("TEACHESS_DEPTH", "10")
    monkeypatch.setenv("LICHESS_USER", "alice")
    monkeypatch.setattr(
        cli,
        "_http_client",
        lambda: http.make_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text=LICHESS_PGN))
        ),
    )
    engine = ScriptedEngine()

    def open_engine(settings: Settings) -> AbstractContextManager[Engine]:
        return nullcontext(engine)

    monkeypatch.setattr(cli, "_open_engine", open_engine)
    yield db_path


def invoke(*args: str) -> str:
    result = runner.invoke(cli.app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_import_analyze_report_end_to_end(env: Path) -> None:
    assert "Partidas nuevas: 1" in invoke("import", "--platform", "lichess")
    assert "Partidas nuevas: 0 · ya importadas: 1" in invoke("import", "--platform", "lichess")

    assert "Partidas analizadas: 1 (profundidad 10)" in invoke("analyze", "--user", "alice")
    assert "No hay partidas pendientes" in invoke("analyze", "--user", "alice")

    game_output = invoke("report", "--game", "1")
    assert "errores graves: 1" in game_output and "Nf6" in game_output
    assert "Informe de alice" in invoke("report", "--user", "alice")

    conn = repo.connect(env)
    assert conn.execute("SELECT COUNT(*) FROM position_evals").fetchone()[0] == 8
    conn.close()


def test_analyze_single_game_already_analysed(env: Path) -> None:
    invoke("import", "--platform", "lichess")
    invoke("analyze", "--game", "1")
    assert "--reanalyze" in invoke("analyze", "--game", "1")
    assert "Partidas analizadas: 1" in invoke("analyze", "--game", "1", "--reanalyze")


def test_import_pgn_file(tmp_path: Path) -> None:
    path = tmp_path / "otb.pgn"
    path.write_text(LICHESS_PGN, encoding="utf-8")
    output = invoke("import", "--platform", "pgn", "--file", str(path), "--user", "alice")
    assert "Partidas nuevas: 1" in output


def test_errors_exit_with_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_stockfish(settings: Settings) -> AbstractContextManager[Engine]:
        raise StockfishNotConfiguredError("STOCKFISH_PATH no está configurado")

    cases = [
        (["report", "--game", "1", "--user", "alice"], "solo uno"),
        (["report", "--game", "42"], "no existe o no está analizada"),
        (["analyze", "--game", "42"], "No existe la partida 42"),
        (["import", "--platform", "pgn"], "--user"),
    ]
    for args, message in cases:
        result = runner.invoke(cli.app, args)
        assert result.exit_code == 1, args
        assert message in result.output

    invoke("import", "--platform", "lichess")
    monkeypatch.setattr(cli, "_open_engine", no_stockfish)
    result = runner.invoke(cli.app, ["analyze", "--user", "alice"])
    assert result.exit_code == 1
    assert "STOCKFISH_PATH" in result.output


def analysed_game() -> None:
    invoke("import", "--platform", "lichess")
    invoke("analyze", "--game", "1")


def use_client(monkeypatch: pytest.MonkeyPatch, client: object) -> None:
    monkeypatch.setattr(cli, "_anthropic_client", lambda: client)


def test_coach_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    analysed_game()
    client = FakeAnthropic(
        api_message(
            tool_block("t1", "get_move", {"move_number": 3, "color": "black"}),
            stop_reason="tool_use",
        ),
        api_message(text_block("3...Nf6 permite el mate [Qxf7#].")),
    )
    use_client(monkeypatch, client)

    result = runner.invoke(cli.app, ["coach", "--game", "1"], input="\n¿Por qué perdí?\nsalir\n")

    assert result.exit_code == 0, result.output
    assert "Bob vs alice" in result.output
    assert "consultando jugada de la partida" in result.output
    assert "3...Nf6 permite el mate [Qxf7#]." in result.output  # brackets are not markup
    assert "Tokens: entrada 200 (caché 160), salida 40." in result.output
    assert len(client.requests) == 2  # the empty line was not sent


def test_coach_end_of_input_closes_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    analysed_game()
    use_client(monkeypatch, FakeAnthropic())
    result = runner.invoke(cli.app, ["coach", "--game", "1"], input="")
    assert result.exit_code == 0, result.output


def test_coach_refusal_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    analysed_game()
    use_client(monkeypatch, FakeAnthropic(api_message(stop_reason="refusal")))
    result = runner.invoke(cli.app, ["coach", "--game", "1"], input="algo\nsalir\n")
    assert result.exit_code == 0, result.output
    assert "Prueba a reformularla" in result.output


def test_coach_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(cli.app, ["coach", "--game", "1"])
    assert result.exit_code == 1 and "no existe o no está analizada" in result.output

    analysed_game()

    class NoCredentials(FakeAnthropic):
        def _stream(self, **kwargs: object) -> object:
            raise TypeError("Could not resolve authentication method. Expected api_key")

    use_client(monkeypatch, NoCredentials())
    result = runner.invoke(cli.app, ["coach", "--game", "1"], input="hola\n")
    assert result.exit_code == 1 and "ANTHROPIC_API_KEY" in result.output

    monkeypatch.setenv("TEACHESS_EFFORT", "turbo")
    result = runner.invoke(cli.app, ["coach", "--game", "1"])
    assert result.exit_code == 1 and "TEACHESS_EFFORT" in result.output
