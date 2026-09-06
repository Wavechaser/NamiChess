from __future__ import annotations

import json
from pathlib import Path

import chess
import pytest

from namichess.analysis.static import ContactKind, move_delta, position_facts
from namichess.domain import PositionContext


FIXTURES = Path(__file__).parents[1] / "fixtures"


def context(fen: str, *, moves: tuple[str, ...] = (), path: tuple[int, ...] = ()) -> PositionContext:
    board = chess.Board(fen)
    for uci in moves:
        board.push_uci(uci)
    return PositionContext(7, 1, path, fen, moves, board.fen(en_passant="fen"), bool(moves))


def placement(facts, square: str):
    return next(item for item in facts.pieces if item.square == square)


def contact_changes(delta, controller, subject):
    return (
        [item.kind for item in delta.contacts_added if item.controller == controller and item.subject == subject],
        [item.kind for item in delta.contacts_removed if item.controller == controller and item.subject == subject],
    )


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


def test_piece_contacts_distinguish_attack_and_geometric_defence() -> None:
    facts = position_facts(context("4k3/8/8/8/3p4/2P5/3P4/2B1K3 w - - 0 1"))
    bishop = placement(facts, "c1").piece_id
    white_pawn = placement(facts, "d2").piece_id
    black_pawn = placement(facts, "d4").piece_id

    assert {
        (contact.controller, contact.subject, contact.kind)
        for contact in facts.contacts
        if contact.controller == bishop
    } == {(bishop, white_pawn, ContactKind.DEFEND)}
    assert any(
        contact.subject == black_pawn and contact.kind == ContactKind.ATTACK
        for contact in facts.contacts
    )


def test_moving_endpoint_preserves_same_identity_bearing_contact() -> None:
    root = "4k3/8/8/n7/8/8/P7/R3K3 w - - 0 1"
    before = position_facts(context(root))
    pawn = placement(before, "a2").piece_id
    rook = placement(before, "a1").piece_id

    delta = move_delta(context(root), context(root, moves=("a2a4",), path=(0,)))

    assert not [item for item in delta.contacts_added if item.controller == rook and item.subject == pawn]
    assert not [item for item in delta.contacts_removed if item.controller == rook and item.subject == pawn]


def test_losing_last_geometric_defender_marks_piece_undefended() -> None:
    root = "4k3/8/8/8/8/8/3P4/2B1K3 w - - 0 1"
    before = position_facts(context(root))
    pawn = placement(before, "d2").piece_id
    bishop = placement(before, "c1").piece_id

    delta = move_delta(context(root), context(root, moves=("d2d4",), path=(0,)))

    assert (bishop, pawn) in {
        (item.controller, item.subject) for item in delta.contacts_removed
    }
    assert [item.piece for item in delta.geometrically_undefended_added] == [pawn]
    assert not delta.geometrically_undefended_added[0].attackers


@pytest.mark.parametrize(
    "root,move,pawn_square,remaining_defender_square",
    [
        pytest.param("4k3/8/8/8/8/5N2/3P4/2B1K3 w - - 0 1", "c1b2", "d2", "f3", id="white-second-defender"),
        pytest.param("2b1k3/3p4/5n2/8/8/8/8/4K3 b - - 0 1", "c8b7", "d7", "f6", id="black-second-defender"),
    ],
)
def test_losing_one_of_two_defenders_does_not_mark_piece_undefended(
    root: str, move: str, pawn_square: str, remaining_defender_square: str
) -> None:
    before = position_facts(context(root))
    pawn = placement(before, pawn_square).piece_id
    remaining = placement(before, remaining_defender_square).piece_id

    delta = move_delta(context(root), context(root, moves=(move,), path=(0,)))

    assert not [item for item in delta.geometrically_undefended_added if item.piece == pawn]
    assert any(
        item.controller == remaining and item.subject == pawn and item.kind is ContactKind.DEFEND
        for item in position_facts(context(root, moves=(move,), path=(0,))).contacts
    )


@pytest.mark.parametrize(
    "case",
    json.loads((FIXTURES / "structural_continuity.json").read_text(encoding="utf-8"))["latent_ray"],
    ids=lambda case: str(case["name"]),
)
def test_latent_ray_names_blocker_and_changes_when_blocker_moves(case: dict[str, object]) -> None:
    root = str(case["fen"])
    before = position_facts(context(root))
    slider = placement(before, str(case["slider"])).piece_id
    blocker = placement(before, str(case["blocker_before"])).piece_id
    target = placement(before, str(case["target"])).piece_id
    direction = str(case["direction"])
    ray = next(item for item in before.latent_rays if item.slider == slider and item.direction == direction)

    assert ray.blocker == blocker
    assert [square.square for square in ray.beyond] == case["beyond_before"]
    assert ray.target == target

    move = str(case["move"])
    delta = move_delta(context(root), context(root, moves=(move,), path=(0,)))
    old_ray = next(item for item in delta.latent_rays_removed if item.slider == slider and item.direction == direction)
    new_ray = next(item for item in delta.latent_rays_added if item.slider == slider and item.direction == direction)
    assert old_ray.blocker_square.square == case["blocker_before"]
    assert new_ray.blocker == blocker
    assert new_ray.blocker_square.square == case["blocker_after"]
    assert [square.square for square in new_ray.beyond] == case["beyond_after"]
    assert new_ray.target == target


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


@pytest.mark.parametrize(
    "root,move,rook_square,mover_square,captured_square,direction",
    [
        pytest.param("4k3/8/8/3pP3/8/8/8/3RK3 w - d6 0 1", "e5d6", "d1", "e5", "d5", "n", id="white-en-passant"),
        pytest.param("4r1k1/8/8/8/3pP3/8/8/4K3 b - e3 0 1", "d4e3", "e8", "d4", "e4", "s", id="black-en-passant"),
    ],
)
def test_en_passant_recomputes_exact_contact_and_latent_ray_relationships(
    root: str, move: str, rook_square: str, mover_square: str, captured_square: str, direction: str
) -> None:
    before = position_facts(context(root))
    rook = placement(before, rook_square).piece_id
    mover = placement(before, mover_square).piece_id
    captured = placement(before, captured_square).piece_id
    delta = move_delta(context(root), context(root, moves=(move,), path=(0,)))

    assert contact_changes(delta, rook, captured) == ([], [ContactKind.ATTACK])
    assert contact_changes(delta, rook, mover) == ([ContactKind.DEFEND], [])
    removed = next(item for item in delta.latent_rays_removed if item.slider == rook and item.direction == direction)
    added = next(item for item in delta.latent_rays_added if item.slider == rook and item.direction == direction)
    assert removed.blocker == captured
    assert added.blocker == mover


def test_castling_delta_tracks_rook_and_king_identities() -> None:
    root = "4k3/8/8/8/8/8/8/4K2R w K - 0 1"
    before_facts = position_facts(context(root))
    delta = move_delta(context(root), context(root, moves=("e1g1",), path=(0,)))

    assert delta.moved.piece == placement(before_facts, "e1").piece_id
    assert (delta.moved.before.square, delta.moved.after.square) == ("e1", "g1")
    assert delta.castling_rook is not None
    assert delta.castling_rook.piece == placement(before_facts, "h1").piece_id
    assert (delta.castling_rook.before.square, delta.castling_rook.after.square) == ("h1", "f1")


@pytest.mark.parametrize(
    "root,move,king_square,rook_square,target_square,direction",
    [
        pytest.param("4k3/8/8/8/8/8/8/n3K2R w K - 0 1", "e1g1", "e1", "h1", "a1", "w", id="white-castling"),
        pytest.param("N3k2r/8/8/8/8/8/8/4K3 b k - 0 1", "e8g8", "e8", "h8", "a8", "w", id="black-castling"),
    ],
)
def test_castling_recomputes_king_rook_contacts_and_blocked_ray(
    root: str, move: str, king_square: str, rook_square: str, target_square: str, direction: str
) -> None:
    before = position_facts(context(root))
    king = placement(before, king_square).piece_id
    rook = placement(before, rook_square).piece_id
    target = placement(before, target_square).piece_id
    delta = move_delta(context(root), context(root, moves=(move,), path=(0,)))

    assert contact_changes(delta, king, rook) == ([ContactKind.DEFEND], [])
    assert contact_changes(delta, rook, target) == ([ContactKind.ATTACK], [])
    removed = next(item for item in delta.latent_rays_removed if item.slider == rook and item.direction == direction)
    assert removed.blocker == king
    assert removed.target == target


def test_promotion_retains_pawn_identity_and_changes_piece_type() -> None:
    root = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    before_facts = position_facts(context(root))
    delta = move_delta(context(root), context(root, moves=("a7a8q",), path=(0,)))

    assert delta.promoted
    assert delta.moved.piece == placement(before_facts, "a7").piece_id
    assert delta.moved.before.piece_type == "pawn"
    assert delta.moved.after.piece_type == "queen"
    assert delta.moved.after.promoted


@pytest.mark.parametrize("suffix,piece_type", [("q", "queen"), ("r", "rook"), ("b", "bishop"), ("n", "knight")])
@pytest.mark.parametrize(
    "root,uci",
    [
        ("4k2r/6P1/8/8/8/8/8/4K3 w - - 0 1", "g7h8"),
        ("4k3/8/8/8/8/8/6p1/4K2R b - - 0 1", "g2h1"),
    ],
)
def test_capture_promotions_retain_identity_and_recompute_contacts(
    suffix: str, piece_type: str, root: str, uci: str
) -> None:
    before = position_facts(context(root))
    source = uci[:2]
    target = uci[2:4]
    pawn = placement(before, source).piece_id
    captured = placement(before, target).piece_id

    delta = move_delta(context(root), context(root, moves=(uci + suffix,), path=(0,)))
    after = position_facts(context(root, moves=(uci + suffix,), path=(0,)))

    assert delta.moved.piece == pawn
    assert delta.moved.after.piece_type == piece_type
    assert delta.captured is not None and delta.captured.piece_id == captured
    assert all(contact.controller != captured and contact.subject != captured for contact in after.contacts)
    controlled = [contact for contact in after.contacts if contact.controller == pawn]
    expected_kind = [ContactKind.ATTACK] if piece_type in {"queen", "rook"} else []
    assert [contact.kind for contact in controlled] == expected_kind
    rays = [ray for ray in after.latent_rays if ray.slider == pawn and ray.direction == "w"]
    assert len(rays) == (1 if piece_type in {"queen", "rook"} else 0)


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


def test_structural_facts_support_more_than_thirty_two_pieces() -> None:
    facts = position_facts(context("krrrrrrr/pppppppp/pppppppp/8/8/PPPPPPPP/PPPPPPPP/RRRRRRRK w - - 0 1"))

    assert len(facts.pieces) == 48
    assert len({piece.piece_id for piece in facts.pieces}) == 48
    assert facts.contacts
    assert facts.latent_rays


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
