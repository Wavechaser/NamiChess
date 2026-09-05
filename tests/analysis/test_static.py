from __future__ import annotations

import json
from pathlib import Path

import chess

from namichess.analysis.static import move_delta, position_facts
from namichess.domain import PositionContext


FIXTURES = Path(__file__).parents[1] / "fixtures"


def context(fen: str, *, moves: tuple[str, ...] = (), path: tuple[int, ...] = ()) -> PositionContext:
    board = chess.Board(fen)
    for uci in moves:
        board.push_uci(uci)
    return PositionContext(7, 1, path, fen, moves, board.fen(en_passant="fen"), bool(moves))


def placement(facts, square: str):
    return next(item for item in facts.pieces if item.square == square)


def test_geometric_attacks_include_pinned_piece_but_legal_access_uses_actual_turn() -> None:
    case = json.loads((FIXTURES / "static_mirrored_pins.json").read_text(encoding="utf-8"))

    white = position_facts(context(case["white"]))
    black = position_facts(context(case["black"]))

    assert [(pin.piece, tuple(ref.square for ref in pin.ray)) for pin in white.pins] == [
        (placement(white, "e2").piece_id, ("e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"))
    ]
    assert [(pin.piece, tuple(ref.square for ref in pin.ray)) for pin in black.pins] == [
        (placement(black, "e7").piece_id, ("e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"))
    ]
    assert {edge.target.square for edge in white.attacks if edge.source.square == "e2"} == {
        "c1", "c3", "d4", "f4", "g1", "g3"
    }
    assert not [move for move in white.legal_moves if move.source.square == "e2"]
    assert not [move for move in black.legal_moves if move.source.square == "e7"]
    assert {move.mover.color for move in white.legal_moves} == {"white"}
    assert {move.mover.color for move in black.legal_moves} == {"black"}


def test_slider_attack_delta_opens_and_closes_rays_with_piece_identity() -> None:
    root = "4k3/8/8/8/8/8/P7/R3K3 w - - 0 1"
    before = context(root)
    after = context(root, moves=("a2a4",), path=(0,))

    delta = move_delta(before, after)

    rook = placement(position_facts(before), "a1").piece_id
    assert {(edge.attacker, edge.target.square) for edge in delta.slider_attacks_added} == {
        (rook, square) for square in ("a3", "a4")
    }
    assert {(edge.attacker, edge.target.square) for edge in delta.slider_attacks_removed} == set()
    assert delta.moved.before.square == "a2"
    assert delta.moved.after.square == "a4"


def test_capture_delta_removes_captured_identity() -> None:
    root = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"
    before = context(root)
    delta = move_delta(before, context(root, moves=("e4d5",), path=(0,)))

    assert delta.captured == placement(position_facts(before), "d5")
    assert delta.moved.after.square == "d5"


def test_en_passant_delta_removes_pawn_from_its_actual_square() -> None:
    root = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
    before = context(root)
    delta = move_delta(before, context(root, moves=("e5d6",), path=(0,)))

    assert delta.captured == placement(position_facts(before), "d5")
    assert delta.moved.after.square == "d6"


def test_castling_delta_tracks_rook_and_king_identities() -> None:
    root = "4k3/8/8/8/8/8/8/4K2R w K - 0 1"
    before_facts = position_facts(context(root))
    delta = move_delta(context(root), context(root, moves=("e1g1",), path=(0,)))

    assert delta.moved.piece == placement(before_facts, "e1").piece_id
    assert (delta.moved.before.square, delta.moved.after.square) == ("e1", "g1")
    assert delta.castling_rook is not None
    assert delta.castling_rook.piece == placement(before_facts, "h1").piece_id
    assert (delta.castling_rook.before.square, delta.castling_rook.after.square) == ("h1", "f1")


def test_promotion_retains_pawn_identity_and_changes_piece_type() -> None:
    root = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    before_facts = position_facts(context(root))
    delta = move_delta(context(root), context(root, moves=("a7a8q",), path=(0,)))

    assert delta.promoted
    assert delta.moved.piece == placement(before_facts, "a7").piece_id
    assert delta.moved.before.piece_type == "pawn"
    assert delta.moved.after.piece_type == "queen"
    assert delta.moved.after.promoted


def test_check_names_checked_king_and_checker_without_inferred_intent() -> None:
    root = "3k4/8/8/8/8/8/4R3/4K3 w - - 0 1"
    facts = position_facts(context(root))

    assert facts.checked_king is None
    delta = move_delta(context(root), context(root, moves=("e2d2",), path=(0,)))
    after = position_facts(context(root, moves=("e2d2",), path=(0,)))
    assert delta.gives_check
    assert after.checked_king == placement(after, "d8").piece_id
    assert after.checkers == (placement(after, "d2").piece_id,)


def test_move_delta_reports_new_absolute_pin() -> None:
    root = "4r1k1/8/8/8/8/2N5/8/4K3 w - - 0 1"
    after_context = context(root, moves=("c3e2",), path=(0,))
    delta = move_delta(context(root), after_context)

    assert len(delta.pins_added) == 1
    assert delta.pins_added[0].piece == placement(position_facts(after_context), "e2").piece_id
    assert not delta.pins_removed


def test_unusual_material_keeps_every_identity_distinct() -> None:
    facts = position_facts(context("6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1"))

    assert len(facts.pieces) == 20
    assert len({piece.piece_id for piece in facts.pieces}) == 20


def test_black_special_moves_mirror_identity_rules() -> None:
    ep_root = "4k3/8/8/8/3pP3/8/8/4K3 b - e3 0 1"
    ep_before = position_facts(context(ep_root))
    ep = move_delta(context(ep_root), context(ep_root, moves=("d4e3",), path=(0,)))
    assert ep.captured == placement(ep_before, "e4")

    castle_root = "4k2r/8/8/8/8/8/8/4K3 b k - 0 1"
    castle = move_delta(context(castle_root), context(castle_root, moves=("e8g8",), path=(0,)))
    assert castle.castling_rook is not None
    assert (castle.castling_rook.before.square, castle.castling_rook.after.square) == ("h8", "f8")

    promotion_root = "4k3/8/8/8/8/8/p7/4K3 b - - 0 1"
    promotion = move_delta(
        context(promotion_root), context(promotion_root, moves=("a2a1q",), path=(0,))
    )
    assert promotion.promoted
    assert promotion.moved.piece.color == "black"
    assert promotion.moved.after.piece_type == "queen"


def test_rejects_current_fen_that_does_not_match_root_history() -> None:
    bad = PositionContext(7, 1, (), chess.STARTING_FEN, (), chess.Board().mirror().fen(), False)
    try:
        position_facts(bad)
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("mismatched context was accepted")
