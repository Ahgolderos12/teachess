from pathlib import Path

import pytest

from teachess.config import load_settings


def test_load_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STOCKFISH_PATH", "C:/sf/stockfish.exe")
    monkeypatch.setenv("CHESSCOM_USER", "someone")
    monkeypatch.setenv("LICHESS_USER", "  ")
    settings = load_settings()
    assert settings.stockfish_path == Path("C:/sf/stockfish.exe")
    assert settings.chesscom_user == "someone"
    assert settings.lichess_user is None
