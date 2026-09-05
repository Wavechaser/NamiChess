"""Environment and package smoke tests."""

import chess

import namichess


def test_package_and_python_chess_are_available() -> None:
    board = chess.Board()

    assert namichess.__version__ == "0.0.0"
    assert chess.__version__ == "1.11.2"
    assert len(tuple(board.legal_moves)) == 20
