from pathlib import Path

import pytest

from teachess.config import DEFAULT_DB_PATH, DEFAULT_ENGINE_DEPTH, load_settings


def test_load_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "C:/sf/stockfish.exe")
    monkeypatch.setenv("CHESSCOM_USER", "someone")
    monkeypatch.setenv("LICHESS_USER", "  ")
    settings = load_settings()
    assert settings.stockfish_path == Path("C:/sf/stockfish.exe")
    assert settings.chesscom_user == "someone"
    assert settings.lichess_user is None


def test_db_and_depth_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHESS_DB", "")
    monkeypatch.setenv("TEACHESS_DEPTH", "")
    settings = load_settings()
    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.engine_depth == DEFAULT_ENGINE_DEPTH


def test_db_and_depth_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHESS_DB", "other.sqlite")
    monkeypatch.setenv("TEACHESS_DEPTH", "12")
    settings = load_settings()
    assert settings.db_path == Path("other.sqlite")
    assert settings.engine_depth == 12
