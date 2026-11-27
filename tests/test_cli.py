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
from tests.fakes import SCHOLAR_PGN, ScriptedEngine

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
