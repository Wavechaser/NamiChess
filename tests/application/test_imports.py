from pathlib import Path

import pytest

from namichess.application.imports import ImportError, import_pgn_text


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_imports_multiple_games_comments_nags_variations_and_composed_fen() -> None:
    document = import_pgn_text((FIXTURES / "multi_game.pgn").read_text(encoding="utf-8"))
    assert len(document.games) == 2
    assert len(document.games[0].variations) == 2
    assert document.games[1].board().piece_at(0).symbol() == "K"


@pytest.mark.parametrize(
    "pgn, problem",
    [
        ("1. e4 e5", "missing terminating result"),
        ("1. e4 ??? *", "more than two"),
        ("1. e4 (1. d4 * ) *", "invalid san"),
        ("1. e4 (1. d4 *", "invalid san"),
        ("1. e4 -- *", "null moves"),
        ('[Event "broken"\n\n*', "malformed"),
        ('[Result "1-0"]\n\n1. e4 0-1', "does not match"),
        ('[SetUp "1"]\n\n*', "requires a FEN"),
        ('[Variant "Chess960"]\n\n*', "unsupported Variant"),
        ("1. e5 *", "illegal"),
    ],
)
def test_rejects_invalid_or_incomplete_pgn(pgn: str, problem: str) -> None:
    with pytest.raises((ImportError, ValueError), match=problem):
        import_pgn_text(pgn)


def test_accepts_check_suffix_and_comments_after_result() -> None:
    document = import_pgn_text("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0 {done}\n")
    assert document.games[0].end().board().is_checkmate()
