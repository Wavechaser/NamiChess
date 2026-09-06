from __future__ import annotations

import chess
import pytest

from namichess.analysis.consequences import move_account, resolve_raw_fact
from namichess.analysis.mechanisms import CheckKind, CheckerRole, move_mechanisms
from namichess.analysis.static import move_delta, position_facts
from namichess.domain.models import PositionContext


def mechanisms(fen: str, uci: str):
    board = chess.Board(fen)
    board.push_uci(uci)
    before = PositionContext(11, 1, (), fen, (), fen, False)
    after = PositionContext(
        11, 1, (0,), fen, (uci,), board.fen(en_passant="fen"), True,
    )
    delta = move_delta(before, after)
    facts = position_facts(after)
    return delta, move_mechanisms(delta, facts)


def mirrored(fen: str, uci: str) -> tuple[str, str]:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    return (
        board.mirror().fen(en_passant="fen"),
        chess.Move(
            chess.square_mirror(move.from_square),
            chess.square_mirror(move.to_square),
            promotion=move.promotion,
        ).uci(),
    )


@pytest.mark.parametrize("mirror", (False, True))
def test_be5_groups_direct_and_discovered_checkers_with_the_bishop_fork(mirror: bool) -> None:
    fen = "8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1"
    uci = "c3e5"
    if mirror:
        fen, uci = mirrored(fen, uci)

    delta, result = mechanisms(fen, uci)

    assert result.check is not None and result.check.kind is CheckKind.DOUBLE
    assert {checker.role for checker in result.check.checkers} == {
        CheckerRole.DIRECT, CheckerRole.DISCOVERED,
    }
    fork = next(item for item in result.forks if item.actor == delta.moved.piece)
    assert result.forks[0] is fork
    assert {target.target.original_piece_type for target in fork.targets} == {"king", "queen"}
    assert all(target.target_square.position_id == delta.after for target in fork.targets)


@pytest.mark.parametrize("mirror", (False, True))
def test_bf6_keeps_discovered_check_and_bishop_attack_without_inventing_a_fork(mirror: bool) -> None:
    fen = "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1"
    uci = "c3f6"
    if mirror:
        fen, uci = mirrored(fen, uci)

    delta, result = mechanisms(fen, uci)

    assert result.check is not None and result.check.kind is CheckKind.SINGLE
    assert [checker.role for checker in result.check.checkers] == [CheckerRole.DISCOVERED]
    assert any(
        attack.actor == delta.moved.piece
        and attack.target.original_piece_type == "queen"
        for attack in result.attacks
    )
    assert result.attacks[0].actor == delta.moved.piece
    assert all(fork.actor != delta.moved.piece for fork in result.forks)


@pytest.mark.parametrize("mirror", (False, True))
def test_be5_single_bishop_check_is_also_a_king_rook_fork(mirror: bool) -> None:
    fen = "8/2k5/8/8/8/2B5/3P3r/K7 w - - 0 1"
    uci = "c3e5"
    if mirror:
        fen, uci = mirrored(fen, uci)

    delta, result = mechanisms(fen, uci)

    assert result.check is not None and result.check.kind is CheckKind.SINGLE
    assert [checker.role for checker in result.check.checkers] == [CheckerRole.DIRECT]
    fork = next(item for item in result.forks if item.actor == delta.moved.piece)
    assert result.forks[0] is fork
    assert {target.target.original_piece_type for target in fork.targets} == {"king", "rook"}


def test_quiet_move_can_establish_a_structural_fork() -> None:
    delta, result = mechanisms(
        "7k/8/3r4/6q1/8/2N5/8/K7 w - - 0 1", "c3e4",
    )

    assert result.check is None
    fork = next(item for item in result.forks if item.actor == delta.moved.piece)
    assert {target.target.original_piece_type for target in fork.targets} == {"rook", "queen"}
    assert all(target.established_by_move for target in fork.targets)


def test_pinned_attacker_fork_remains_geometry_with_resolvable_sources() -> None:
    delta, result = mechanisms(
        "4r2k/8/8/8/8/2n3r1/4R3/4K3 w - - 0 1", "e2e3",
    )

    fork = next(item for item in result.forks if item.actor == delta.moved.piece)
    assert {target.target.original_piece_type for target in fork.targets} == {"knight", "rook"}
    assert not hasattr(fork, "winning")
    assert all(resolve_raw_fact(delta, source) is not None for source in fork.supporting_facts)


def test_relocation_preserving_the_same_two_attack_relationships_is_not_a_new_fork() -> None:
    delta, result = mechanisms(
        "7k/8/6n1/8/4B3/3n4/8/K7 w - - 0 1", "e4f5",
    )

    assert all(fork.actor != delta.moved.piece for fork in result.forks)
    assert all(attack.actor != delta.moved.piece for attack in result.attacks)


def test_mechanism_inputs_must_share_the_exact_result_position() -> None:
    fen = "7k/8/8/8/8/2N5/8/K7 w - - 0 1"
    delta, _ = mechanisms(fen, "c3e4")
    other_board = chess.Board(fen)
    other_board.push_uci("c3b5")
    other = PositionContext(
        11, 1, (1,), fen, ("c3b5",), other_board.fen(en_passant="fen"), True,
    )

    with pytest.raises(ValueError, match="same resulting move"):
        move_mechanisms(delta, position_facts(other))


def test_discovered_checker_provenance_does_not_depend_on_account_display_cap() -> None:
    delta, result = mechanisms(
        "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6",
    )
    assert move_account(delta, max_consequences=0).consequences == ()

    assert result.check is not None
    checker = result.check.checkers[0]
    assert {source.kind.value for source in checker.supporting_facts} >= {
        "contacts_added", "latent_rays_removed",
    }
    assert all(resolve_raw_fact(delta, source) is not None for source in checker.supporting_facts)


def test_castling_rook_direct_check_has_role_evidence_when_account_is_empty() -> None:
    delta, result = mechanisms(
        "5k2/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1",
    )
    assert move_account(delta, max_consequences=0).consequences == ()

    assert result.check is not None
    checker = result.check.checkers[0]
    assert checker.role is CheckerRole.DIRECT
    assert {source.kind.value for source in checker.supporting_facts} == {
        "castling_rook", "contacts_added",
    }
    assert all(resolve_raw_fact(delta, source) is not None for source in checker.supporting_facts)


def test_en_passant_discovered_check_retains_both_cleared_blocker_sources() -> None:
    delta, result = mechanisms(
        "8/8/8/R2pP2k/8/8/8/K7 w - d6 0 1", "e5d6",
    )

    assert result.check is not None
    checker = result.check.checkers[0]
    assert checker.role is CheckerRole.DISCOVERED
    assert {source.kind.value for source in checker.supporting_facts} == {
        "moved", "latent_rays_removed", "contacts_added",
    }
    removed_ray = next(
        resolve_raw_fact(delta, source)
        for source in checker.supporting_facts
        if source.kind.value == "latent_rays_removed"
    )
    assert removed_ray.blocker == delta.captured.piece_id
