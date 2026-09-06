from __future__ import annotations

import pytest

from namichess.analysis.consequences import resolve_raw_fact
from namichess.application.attention import (
    AttentionKind,
    resolve_position_fact,
    select_attention,
)
from namichess.application.session import Session


@pytest.mark.parametrize(
    "fen",
    (
        "7k/8/8/8/8/8/r7/R6K w - - 0 1",
        "r6k/R7/8/8/8/8/8/7K b - - 0 1",
    ),
)
def test_import_attention_surfaces_attacked_undefended_side_to_move_piece(fen: str) -> None:
    view = Session().load_fen(fen)
    item = next(item for item in view.attention.items if item.kind is AttentionKind.ATTACKED_UNDEFENDED)

    assert view.previous_move is None and view.move_account is None
    assert item.subject.color == view.turn
    assert item.square.position_id == view.position.position_id
    assert all(resolve_position_fact(view.facts, source) is not None for source in item.position_sources)


def test_attention_is_bounded_and_reports_omitted_current_facts() -> None:
    view = Session().load_fen("7k/3n2n1/8/8/n2Q2n1/8/8/n6K w - - 0 1")

    assert len(view.attention.items) == 3
    assert view.attention.omitted_count == 2
    assert all(item.kind is AttentionKind.ATTACKED_UNDEFENDED for item in view.attention.items)


def test_move_attention_merges_lost_defense_with_current_undefended_fact() -> None:
    session = Session()
    session.load_fen("7k/8/8/1n6/2b5/3B4/8/K7 w - - 0 1")
    view = session.play("Bxc4")
    knight = next(item.piece_id for item in view.facts.pieces if item.square == "b5")
    matching = [item for item in view.attention.items if item.subject == knight]

    assert len(matching) == 1
    assert matching[0].kind is AttentionKind.LOST_DEFENSE_UNDER_ATTACK
    assert matching[0].square.square == "b5"
    assert matching[0].position_sources and matching[0].move_sources
    assert all(resolve_position_fact(view.facts, source) is not None for source in matching[0].position_sources)
    assert all(resolve_raw_fact(view.previous_move, source) is not None for source in matching[0].move_sources)


def test_move_attention_merges_new_pin_with_current_pin_fact() -> None:
    session = Session()
    session.load_fen("4k3/4n3/8/8/8/8/4B3/4R2K w - - 0 1")
    view = session.play("Bb5+")
    knight = next(item.piece_id for item in view.facts.pieces if item.square == "e7")
    matching = [
        item for item in view.attention.items
        if item.kind is AttentionKind.PINNED and item.subject == knight
    ]

    assert len(matching) == 1
    assert matching[0].square.square == "e7"
    assert matching[0].position_sources and matching[0].move_sources


def test_pinned_geometric_defender_does_not_create_undefended_attention() -> None:
    session = Session()
    session.load_fen("4rr1k/8/8/8/8/8/4RP2/4K3 b - - 0 1")
    view = session.play("Rf4")
    pawn = next(item.piece_id for item in view.facts.pieces if item.square == "f2")

    assert all(
        item.subject != pawn
        for item in view.attention.items
        if item.kind in (
            AttentionKind.ATTACKED_UNDEFENDED,
            AttentionKind.LOST_DEFENSE_UNDER_ATTACK,
        )
    )


def test_terminal_attention_keeps_check_without_phantom_material_urgency() -> None:
    view = Session().load_fen("7k/6Q1/7K/8/8/8/8/8 b - - 0 1")
    assert [item.kind for item in view.attention.items] == [AttentionKind.CHECK]

    stalemate = Session().load_fen("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
    assert stalemate.attention.items == ()


def test_unattacked_newly_undefended_piece_is_not_attention() -> None:
    session = Session()
    session.load_fen("7k/8/8/8/8/8/8/R1R4K w - - 0 1")
    view = session.play("Rc2")
    assert all(item.kind is not AttentionKind.LOST_DEFENSE_UNDER_ATTACK for item in view.attention.items)


def test_blocker_remaining_on_ray_does_not_create_opened_line_attention() -> None:
    session = Session()
    session.load_fen("r6k/8/8/8/8/8/P7/R6K w - - 0 1")
    view = session.play("a3")
    assert all(item.kind is not AttentionKind.OPENED_LINE for item in view.attention.items)


def test_ordinary_geometric_attack_is_not_a_pin() -> None:
    session = Session()
    session.load_fen("4k3/4n3/8/8/8/2B5/8/7K w - - 0 1")
    view = session.play("Bb4")
    assert all(item.kind is not AttentionKind.PINNED for item in view.attention.items)


def test_navigation_rebuilds_attention_for_exact_selected_position() -> None:
    session = Session()
    loaded = session.load_pgn("1. e4 e5 *\n")
    end_id = loaded.position.position_id
    root = session.start()
    first = session.next()
    end = session.next()

    assert root.attention.position_id == root.position.position_id
    assert first.attention.position_id == first.position.position_id
    assert end.attention.position_id == end_id
    assert session.back().attention.position_id == first.position.position_id


def test_attention_rejects_stale_move_account() -> None:
    session = Session()
    root = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
    moved = session.play("Ra2")

    with pytest.raises(ValueError, match="must end"):
        select_attention(root.facts, moved.move_account)
