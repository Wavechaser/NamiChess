import chess
import pytest

from namichess.domain.notation import resolve_legal_move


def test_relaxed_san_requires_a_unique_legal_move() -> None:
    board = chess.Board("4k3/8/8/8/8/8/R6R/4K3 w - - 0 1")

    with pytest.raises(ValueError, match="unambiguous"):
        resolve_legal_move(board, "rd2")

    assert resolve_legal_move(board, "rhd2").uci() == "h2d2"
