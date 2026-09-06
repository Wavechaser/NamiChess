from pathlib import Path

import chess
import pytest

from namichess.application import imports
from namichess.application.imports import ImportError, import_pgn_text


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_imports_multiple_games_comments_nags_variations_and_composed_fen() -> None:
    document = import_pgn_text((FIXTURES / "multi_game.pgn").read_text(encoding="utf-8"))
    assert len(document.games) == 2
    assert len(document.games[0].variations) == 2
    assert document.games[1].board().piece_at(0).symbol() == "K"


def test_pgn_preparation_masks_once_and_preserves_projection_alignment_and_original_move_order(
    monkeypatch,
) -> None:
    source = '[Event "one"]\n\n1. E4 { E5 is commentary } (1. D4 d5) e5 *\n\n[Event "two"]\n\n1. NF3+ *'
    real_mask = imports._mask_non_movetext
    calls = 0

    def counted_mask(text: str) -> str:
        nonlocal calls
        calls += 1
        return real_mask(text)

    monkeypatch.setattr(imports, "_mask_non_movetext", counted_mask)
    projected, original_moves = imports._prepare_pgn(source)

    assert calls == 1
    assert len(projected) == len(source)
    assert projected == source.replace("E4", "e4", 1).replace("D4", "d4", 1).replace("NF3", "Nf3", 1)
    assert tuple(original_moves) == ("E4", "D4", "d5", "e5", "NF3+")


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


def test_import_normalizes_case_insensitive_shorthand_to_canonical_san() -> None:
    document = import_pgn_text("1. E4 e5 2. bc4 nc6 3. qh5 nf6 4. QF7 1-0")

    game = document.games[0]
    assert game.end().board().is_checkmate()
    assert str(game.mainline()).endswith("4. Qxf7#")


def test_import_accepts_mixed_case_castling_capture_and_promotion() -> None:
    castle = import_pgn_text("1. E4 E5 2. NF3 NC6 3. BC4 BC5 4. O-o *")
    promotion = import_pgn_text(
        '[SetUp "1"]\n[FEN "k7/4P3/8/8/8/8/8/7K w - - 0 1"]\n\n1. E8=q *'
    )
    capture = import_pgn_text("1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. QXF7# 1-0")

    assert castle.games[0].end().board().king(chess.WHITE) == chess.G1
    assert promotion.games[0].end().board().piece_at(chess.E8).symbol() == "Q"
    assert capture.games[0].end().board().is_checkmate()


def test_import_uses_original_token_for_pawn_bishop_capture_collision() -> None:
    headers = '[SetUp "1"]\n[FEN "7k/8/8/8/2n5/1P1B4/8/K7 w - - 0 1"]\n\n'

    assert import_pgn_text(headers + "1. bxc4 *").games[0].end().move.uci() == "b3c4"
    assert import_pgn_text(headers + "1. Bxc4 *").games[0].end().move.uci() == "d3c4"
    for shorthand in ("bc4", "bXC4"):
        with pytest.raises(ImportError, match="illegal san"):
            import_pgn_text(headers + f"1. {shorthand} *")


def test_import_does_not_skip_an_illegal_lowercase_piece_prefix() -> None:
    with pytest.raises(ImportError, match="illegal san"):
        import_pgn_text("1. qe4 *")


@pytest.mark.parametrize("move", ("Qf7+", "Qxf7+"))
def test_import_rejects_incorrect_supplied_effect_markers(move: str) -> None:
    with pytest.raises(ImportError, match="noncanonical SAN"):
        import_pgn_text(f"1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. {move} 1-0")
