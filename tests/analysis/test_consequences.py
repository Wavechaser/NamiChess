from __future__ import annotations

import chess
import pytest
from dataclasses import replace

from namichess.analysis.consequences import (
    ConsequenceKind,
    move_account,
    resolve_raw_fact,
)
from namichess.analysis.static import move_delta
from namichess.domain.models import PositionContext


def contexts(fen: str, uci: str) -> tuple[PositionContext, PositionContext]:
    board = chess.Board(fen)
    board.push_uci(uci)
    before = PositionContext(7, 1, (), fen, (), fen, False)
    after = PositionContext(7, 1, (0,), fen, (uci,), board.fen(en_passant="fen"), True)
    return before, after


def account(fen: str, uci: str, *, maximum: int = 20):
    before, after = contexts(fen, uci)
    delta = move_delta(before, after)
    return delta, move_account(delta, max_consequences=maximum)


@pytest.mark.parametrize(
    ("fen", "uci"),
    [
        ("7k/8/8/3p4/4P3/8/8/K7 w - - 0 1", "e4d5"),
        ("K7/8/8/8/4pP2/8/8/7k b - f3 0 1", "e4f3"),
    ],
)
def test_capture_and_en_passant_have_resolvable_captured_piece_sources(fen: str, uci: str) -> None:
    delta, result = account(fen, uci)
    capture = next(item for item in result.consequences if item.kind is ConsequenceKind.CAPTURE)

    assert capture.subject == delta.captured.piece_id
    assert capture.target is not None and capture.target.position_id == delta.before
    assert all(resolve_raw_fact(delta, reference) is not None for reference in capture.supporting_facts)


@pytest.mark.parametrize("promotion", ("q", "r", "b", "n"))
def test_every_promotion_type_records_the_resulting_piece_and_check_truth(promotion: str) -> None:
    delta, result = account("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8" + promotion)
    kinds = {item.kind for item in result.consequences}

    assert ConsequenceKind.PROMOTION in kinds
    assert delta.moved.after.piece_type == chess.piece_name(chess.PIECE_SYMBOLS.index(promotion))
    assert (ConsequenceKind.CHECK in kinds) is delta.gives_check


def test_castling_account_identifies_the_rook_and_sources() -> None:
    delta, result = account("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1")
    castling = next(item for item in result.consequences if item.kind is ConsequenceKind.CASTLING)

    assert delta.castling_rook is not None
    assert castling.subject == delta.castling_rook.piece
    assert all(resolve_raw_fact(delta, reference) is not None for reference in castling.supporting_facts)


def test_moving_a_blocker_along_the_same_ray_is_not_an_opened_line() -> None:
    _, result = account("r6k/8/8/8/8/8/P7/R6K w - - 0 1", "a2a3")
    assert ConsequenceKind.OPENED_LINE not in {item.kind for item in result.consequences}


@pytest.mark.parametrize(
    ("fen", "uci"),
    [
        ("r6k/8/8/8/8/8/B7/R6K w - - 0 1", "a2b3"),
        ("r6k/b7/8/8/8/8/8/R6K b - - 0 1", "a7b6"),
    ],
)
def test_moving_a_blocker_off_a_ray_connects_the_stationary_slider_to_occupied_target(
    fen: str, uci: str,
) -> None:
    delta, result = account(fen, uci)
    opened = next(item for item in result.consequences if item.kind is ConsequenceKind.OPENED_LINE)

    assert opened.actor != delta.moved.piece
    assert opened.related_piece == delta.moved.piece
    assert opened.subject is not None
    assert {reference.kind.value for reference in opened.supporting_facts} == {
        "latent_rays_removed", "contacts_added",
    }


def test_captured_subject_contact_removals_are_suppressed() -> None:
    delta, result = account("7k/8/8/1p6/2n5/3B4/8/K7 w - - 0 1", "d3c4")
    captured = delta.captured.piece_id
    assert all(
        item.subject != captured
        for item in result.consequences
        if item.kind in (ConsequenceKind.LOST_DEFENSE, ConsequenceKind.LOST_CONTROL)
    )


def test_captured_defender_can_leave_a_surviving_piece_undefended() -> None:
    delta, result = account("7k/8/8/1n6/2b5/3B4/8/K7 w - - 0 1", "d3c4")
    lost = next(item for item in result.consequences if item.kind is ConsequenceKind.LOST_DEFENSE)

    assert lost.actor == delta.captured.piece_id
    assert lost.subject in {item.piece_id for item in delta.after_pieces}
    assert len(lost.supporting_facts) == 2
    assert all(resolve_raw_fact(delta, reference) is not None for reference in lost.supporting_facts)


def test_same_relationship_after_mover_coordinate_change_is_not_lost_defense() -> None:
    _, result = account("7k/8/8/8/8/8/8/R1R4K w - - 0 1", "c1d1")
    assert ConsequenceKind.LOST_DEFENSE not in {item.kind for item in result.consequences}


def test_new_pin_uses_piece_identity_and_does_not_hide_independent_check() -> None:
    delta, result = account("4k3/4n3/8/8/8/8/4B3/4R2K w - - 0 1", "e2b5")
    kinds = {item.kind for item in result.consequences}

    assert ConsequenceKind.PINNED in kinds
    assert (ConsequenceKind.CHECK in kinds) is delta.gives_check
    pin = next(item for item in result.consequences if item.kind is ConsequenceKind.PINNED)
    assert pin.actor is None
    assert pin.related_piece is not None
    assert {reference.kind.value for reference in pin.supporting_facts} == {
        "pins_added", "latent_rays_removed", "contacts_added",
    }
    assert ConsequenceKind.OPENED_LINE not in kinds


def test_discovered_check_does_not_assign_the_mover_as_checker() -> None:
    _, result = account("4k3/8/8/8/8/8/4B3/4R2K w - - 0 1", "e2c4")
    check = next(item for item in result.consequences if item.kind is ConsequenceKind.CHECK)

    assert check.actor is None
    assert check.source is None


def test_lost_defense_targets_the_subjects_resulting_square() -> None:
    _, result = account("7k/8/8/8/8/8/8/R1R4K w - - 0 1", "c1c2")
    lost = next(item for item in result.consequences if item.kind is ConsequenceKind.LOST_DEFENSE)

    assert lost.target is not None
    assert lost.target.square == "c2"


def test_captured_former_pinned_piece_is_not_reported_as_unpinned() -> None:
    delta, result = account("4r2k/8/8/8/8/8/4B3/4K3 b - - 0 1", "e8e2")

    assert delta.captured is not None
    assert all(
        item.subject != delta.captured.piece_id
        for item in result.consequences
        if item.kind is ConsequenceKind.UNPINNED
    )


def test_pinned_geometric_defender_does_not_become_undefended_by_policy() -> None:
    delta, result = account("4rr1k/8/8/8/8/8/4RP2/4K3 b - - 0 1", "f8f4")
    pawn = next(item.piece_id for item in delta.after_pieces if item.square == "f2")

    assert pawn not in {item.piece for item in delta.geometrically_undefended_added}
    assert all(
        item.subject != pawn
        for item in result.consequences
        if item.kind is ConsequenceKind.LOST_DEFENSE
    )


def test_selection_is_bounded_ordered_and_reports_omissions() -> None:
    delta, result = account(chess.STARTING_FEN, "e2e4", maximum=3)
    complete = move_account(delta, max_consequences=100)

    assert len(result.consequences) <= 3
    assert result.consequences == complete.consequences[:3]
    assert result.omitted_count == len(complete.consequences) - len(result.consequences)
    assert all(
        resolve_raw_fact(delta, reference) is not None
        for item in complete.consequences
        for reference in item.supporting_facts
    )


def test_raw_fact_reference_is_scoped_to_exact_root_delta_and_rejects_negative_index() -> None:
    first_before, first_after = contexts(chess.STARTING_FEN, "e2e4")
    second_before, second_after = contexts(chess.STARTING_FEN, "d2d4")
    first = move_delta(first_before, first_after)
    second = move_delta(second_before, second_after)
    reference = move_account(first, max_consequences=20).consequences[-1].supporting_facts[0]

    with pytest.raises(ValueError, match="different move delta"):
        resolve_raw_fact(second, reference)
    indexed = next(
        source
        for event in move_account(first, max_consequences=20).consequences
        for source in event.supporting_facts
        if source.index is not None
    )
    with pytest.raises(ValueError, match="out of range"):
        resolve_raw_fact(first, replace(indexed, index=-1))
