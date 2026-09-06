"""Environment and package smoke tests."""

import chess

import namichess
from namichess.composition import _settings_path


def test_package_and_python_chess_are_available() -> None:
    board = chess.Board()

    assert namichess.__version__ == "0.0.0"
    assert chess.__version__ == "1.11.2"
    assert len(tuple(board.legal_moves)) == 20


def test_empty_localappdata_uses_user_local_application_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setattr("namichess.composition.Path.home", lambda: tmp_path)

    assert _settings_path() == tmp_path / "AppData" / "Local" / "NamiChess" / "settings.json"
