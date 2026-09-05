from pathlib import Path

import chess
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


@pytest.mark.parametrize(
    "pgn, problem",
    [
        ("1. e4# *", "noncanonical SAN"),
        ("1. e4+ *", "noncanonical SAN"),
        ("1. e2e4 *", "noncanonical SAN"),
        ("1. e4 (1. d4+ d5) e5 *", "noncanonical SAN"),
        ("1. e4 (1. d4# d5) e5 *", "noncanonical SAN"),
        ("1. e4 (1. d2d4 d5) e5 *", "noncanonical SAN"),
        ("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7 1-0", "noncanonical SAN"),
    ],
)
def test_rejects_noncanonical_san_in_mainline_and_variations(pgn: str, problem: str) -> None:
    with pytest.raises(ImportError, match=problem):
        import_pgn_text(pgn)


def test_accepts_canonical_check_mate_castle_and_promotion_san() -> None:
    check = import_pgn_text("1. e4 e5 2. Qh5 Nc6 3. Qxe5+ *")
    mate = import_pgn_text("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0")
    castle = import_pgn_text("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O *")
    promotion = import_pgn_text(
        '[SetUp "1"]\n[FEN "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"]\n\n1. a8=Q+ *'
    )

    assert check.games[0].end().board().is_check()
    assert mate.games[0].end().board().is_checkmate()
    assert castle.games[0].end().board().king(chess.WHITE) == chess.G1
    assert promotion.games[0].end().board().piece_at(chess.A8).symbol() == "Q"
