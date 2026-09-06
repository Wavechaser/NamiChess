import pytest

from namichess.domain.validation import PositionValidationError, parse_fen


def test_accepts_composed_position_with_excess_material() -> None:
    board = parse_fen("6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1")
    assert len(board.piece_map()) == 20


@pytest.mark.parametrize(
    "fen",
    [
        "8/8/8/8/8/8/4k3/4K3 w - - 0 0",
        "8/8/8/8/8/8/4k3/4K~3 w - - 0 1",
        "8/8/8/8/8/8/4k3/4K3 w KK - 0 1",
        "8/8/8/8/8/8/4k3/4K3 w - - ٠ 1",
        "8/8/8/8/8/8/4k3/4K3 w - - 0",
        "8/8/8/8/8/8/4k3/4K3 w - - 00 01",
        f"8/8/8/8/8/8/4k3/4K3 w - - 0 {'9' * 5000}",
    ],
)
def test_rejects_incomplete_or_normalized_fen(fen: str) -> None:
    with pytest.raises(PositionValidationError, match="reload"):
        parse_fen(fen)
