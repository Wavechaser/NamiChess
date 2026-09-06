from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import chess
import pytest

from namichess.analysis.assessments import (
    AssessmentConclusion,
    assess_move_safety,
    assess_overload,
    assess_trapping,
)
from namichess.analysis.local import (
    LocalExit,
    LocalExploration,
    LocalLimits,
    LocalLine,
    LocalRootEvidence,
    LocalTermination,
    explore_local,
)
from namichess.analysis.static import position_facts
from namichess.domain.models import PositionContext


FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures" / "assessments.json").read_text(encoding="utf-8"))


def context(fen: str) -> PositionContext:
    return PositionContext(7, 1, (), fen, (), fen, False)


def exploration(position: PositionContext, root: str, lines: tuple[LocalLine, ...], replies: int) -> LocalExploration:
    evidence = LocalRootEvidence(root, replies, replies, lines, first_reply=lines[0].moves[1] if lines else None)
    return LocalExploration(position.position_id, (evidence,), 1, LocalLimits(), None, ())


def line(*moves: str, exit: LocalExit = LocalExit.WITNESSED_MATE) -> LocalLine:
    return LocalLine(tuple(moves), exit, (), "selected_forcing_continuation", LocalTermination.TERMINAL)


def test_immediate_mate_is_established_but_deeper_cooperative_mate_is_only_observed() -> None:
    position = context(FIXTURES["mate_in_one_refutation"])
    immediate = exploration(position, "b1h1", (line("b1h1", "b3a3"),), 1)
    cooperative_position = context(FIXTURES["quiet_escape_counterexample"])
    deeper = exploration(
        cooperative_position, "b1b3", (line("b1b3", "b4b8", "b3b1", "b8a8"),), 1,
    )

    assert assess_move_safety(position, immediate)[0].conclusion is AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE
    assert assess_move_safety(cooperative_position, deeper)[0].conclusion is AssessmentConclusion.OBSERVED_FAILURE


def test_deeper_cooperative_mate_observation_is_color_mirrored() -> None:
    position = context(FIXTURES["quiet_escape_counterexample_black"])
    deeper = exploration(
        position, "b8b6", (line("b8b6", "b5b1", "b6b8", "b1a1"),), 1,
    )
    assert assess_move_safety(position, deeper)[0].conclusion is AssessmentConclusion.OBSERVED_FAILURE


@pytest.mark.parametrize(
    "fixture,root,reply",
    [
        ("quiet_escape_counterexample", "b1h1", "b4b8"),
        ("quiet_escape_counterexample_black", "b8h8", "b5b1"),
    ],
)
def test_quiet_counterexample_is_no_refutation_found_not_safe(fixture: str, root: str, reply: str) -> None:
    position = context(FIXTURES[fixture])
    result = exploration(
        position, root, (line(root, reply, exit=LocalExit.EXAMINED),), 1,
    )
    assessment = assess_move_safety(position, result)[0]
    assert assessment.conclusion is AssessmentConclusion.NO_REFUTATION_FOUND


def test_trapping_lists_actual_piece_exits_and_keeps_unsearched_ones_unresolved() -> None:
    position = context(FIXTURES["mate_in_one_refutation"])
    rook = next(item.mover for item in position_facts(position).legal_moves if item.uci == "b1h1")
    result = exploration(position, "b1h1", (line("b1h1", "b3a3"),), 1)

    assessment = assess_trapping(position, result, rook)
    assert assessment.conclusion is AssessmentConclusion.INCOMPLETE
    assert "b1h1" in assessment.refuted_exits
    assert assessment.unresolved_exits
    assert assessment.coverage.refuted == 1


def test_zero_legal_piece_exits_is_reported_distinctly() -> None:
    position = context(chess.STARTING_FEN)
    blocked_bishop = next(piece.piece_id for piece in position_facts(position).pieces if piece.square == "c1")
    empty = LocalExploration(position.position_id, (), 0, LocalLimits(), None, ())
    assessment = assess_trapping(position, empty, blocked_bishop)
    assert assessment.conclusion is AssessmentConclusion.NO_LEGAL_EXITS


def test_shared_defensive_contacts_are_only_an_incomplete_candidate_without_a_witness() -> None:
    position = context(FIXTURES["shared_defender_duties"])
    empty = LocalExploration(position.position_id, (), 0, LocalLimits(), None, ())
    assessments = assess_overload(position, empty)

    assert assessments
    assert all(item.conclusion is AssessmentConclusion.INCOMPLETE for item in assessments)
    assert all(len({duty.defended for duty in item.duties}) >= 2 for item in assessments)


def test_real_local_line_can_witness_conflicting_duties_without_claiming_forced_overload() -> None:
    async def run() -> None:
        position = context(FIXTURES["shared_defender_duties"])
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0, piece_square="f3",
        )
        assessments = assess_overload(position, local)
        assert any(item.conclusion is AssessmentConclusion.WITNESSED_CONFLICTING_DUTIES for item in assessments)
        assert all(item.conclusion is not AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE for item in assessments)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,root",
    [("negative_exchange_sacrifice", "e4d5"), ("negative_exchange_sacrifice_black", "e5d4")],
)
def test_negative_exchange_is_separate_evidence_not_a_move_failure(fixture: str, root: str) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0, root_moves=(root,),
        )
        assessment = assess_move_safety(position, local)[0]
        assert assessment.exchange_result == -8
        assert assessment.conclusion not in (
            AssessmentConclusion.OBSERVED_FAILURE,
            AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE,
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,square,along_ray",
    [("pinned_along_ray", "e2", "e2e8"), ("pinned_along_ray_black", "e7", "e7e1")],
)
def test_pinned_piece_retains_legal_along_ray_exits(fixture: str, square: str, along_ray: str) -> None:
    position = context(FIXTURES[fixture])
    rook = next(piece.piece_id for piece in position_facts(position).pieces if piece.square == square)
    empty = LocalExploration(position.position_id, (), 0, LocalLimits(), None, ())
    assessment = assess_trapping(position, empty, rook)
    assert along_ray in assessment.legal_exits
    assert assessment.conclusion is AssessmentConclusion.INCOMPLETE


@pytest.mark.parametrize(
    "fixture,square,root,reply",
    [
        ("quiet_material_exposure", "e2", "e2e4", "d5e4"),
        ("quiet_material_exposure_black", "e7", "e7e5", "d4e5"),
    ],
)
def test_quiet_exit_material_exposure_is_model_qualified_and_mirrored(
    fixture: str, square: str, root: str, reply: str,
) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        piece = next(item.piece_id for item in position_facts(position).pieces if item.square == square)
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=(root,),
        )
        assessment = assess_trapping(position, local, piece)
        exposure = next(item for item in assessment.material_exposures if item.reply_uci == reply)
        assert exposure.material_result == -1
        assert exposure.model == "root_gain_plus_target_square_material"
        assert root in assessment.material_exposed_exits
        assert root not in assessment.refuted_exits
        assert assessment.conclusion is AssessmentConclusion.INCOMPLETE

    asyncio.run(run())


def test_beneficial_root_capture_is_not_material_exposed_when_mover_is_taken() -> None:
    async def run() -> None:
        position = context(FIXTURES["beneficial_root_capture"])
        rook = next(item.piece_id for item in position_facts(position).pieces if item.square == "e2")
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("e2e5",),
        )
        assessment = assess_trapping(position, local, rook)
        assert "e2e5" not in assessment.material_exposed_exits
        assert not assessment.material_exposures

    asyncio.run(run())


def test_reply_capture_of_another_piece_does_not_describe_the_selected_exit() -> None:
    async def run() -> None:
        position = context(FIXTURES["reply_captures_other_piece"])
        pawn = next(item.piece_id for item in position_facts(position).pieces if item.square == "e2")
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("e2e3",),
        )
        assessment = assess_trapping(position, local, pawn)
        assert "e2e3" not in assessment.material_exposed_exits

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,root,reply",
    [
        ("mate_in_one_refutation", "b1h1", "b3a3"),
        ("mate_in_one_refutation_black", "b8h8", "b6a6"),
    ],
)
def test_immediate_mate_failure_is_color_mirrored(fixture: str, root: str, reply: str) -> None:
    position = context(FIXTURES[fixture])
    local = exploration(position, root, (line(root, reply),), 1)
    assert assess_move_safety(position, local)[0].conclusion is AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE


@pytest.mark.parametrize(
    "fixture,square,root,mating_reply",
    [
        ("mate_in_one_refutation", "b1", "b1h1", "b3a3"),
        ("mate_in_one_refutation_black", "b8", "b8h8", "b6a6"),
    ],
)
def test_real_local_producer_preserves_mate_reply_coverage(
    fixture: str, square: str, root: str, mating_reply: str,
) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        piece = next(item.piece_id for item in position_facts(position).pieces if item.square == square)
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=(root,),
        )
        root_evidence = local.roots[0]
        board = chess.Board(position.current_fen)
        board.push_uci(root)
        assert root_evidence.legal_reply_count == len(tuple(board.legal_moves))
        assert root_evidence.examined_reply_count == root_evidence.legal_reply_count
        assert any(line.moves[:2] == (root, mating_reply) for line in root_evidence.lines)
        assert assess_move_safety(position, local)[0].conclusion is AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE
        trapped = assess_trapping(position, local, piece)
        assert root in trapped.refuted_exits
        assert root not in trapped.unresolved_exits

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,square,root",
    [
        ("mate_in_one_refutation", "b1", "b1h1"),
        ("mate_in_one_refutation_black", "b8", "b8h8"),
    ],
)
def test_limit_cutoff_cannot_be_laundered_into_a_refuted_exit(fixture: str, square: str, root: str) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        piece = next(item.piece_id for item in position_facts(position).pieces if item.square == square)
        local = await explore_local(
            position, limits=LocalLimits(node_limit=1), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=(root,),
        )
        assert local.roots[0].examined_reply_count == 0
        assert local.roots[0].lines[0].exit is LocalExit.UNRESOLVED
        assessment = assess_trapping(position, local, piece)
        assert root not in assessment.refuted_exits
        assert root in assessment.unresolved_exits

    asyncio.run(run())


def test_line_associated_with_the_wrong_root_is_rejected() -> None:
    position = context(FIXTURES["mate_in_one_refutation"])
    malformed = exploration(position, "b1b2", (line("b1h1", "b3a3"),), 1)
    with pytest.raises(ValueError, match="different root"):
        assess_move_safety(position, malformed)


@pytest.mark.parametrize(
    "fixture,piece_square",
    [("shared_defender_duties", "f3"), ("shared_defender_duties_black", "f6")],
)
def test_witnessed_conflicting_duties_are_color_mirrored(fixture: str, piece_square: str) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            piece_square=piece_square,
        )
        assert any(
            item.conclusion is AssessmentConclusion.WITNESSED_CONFLICTING_DUTIES
            for item in assess_overload(position, local)
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,piece_square",
    [
        ("overload_relieved_by_countercheck", "f3"),
        ("overload_relieved_by_countercheck_black", "f6"),
    ],
)
def test_countercheck_prevents_the_near_identical_duty_exploitation(fixture: str, piece_square: str) -> None:
    async def run() -> None:
        position = context(FIXTURES[fixture])
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            piece_square=piece_square,
        )
        assessments = assess_overload(position, local)
        assert assessments
        assert all(item.conclusion is not AssessmentConclusion.WITNESSED_CONFLICTING_DUTIES for item in assessments)

    asyncio.run(run())


def test_visible_moves_cannot_be_reassociated_with_stale_deltas() -> None:
    async def run() -> None:
        position = context(FIXTURES["shared_defender_duties"])
        local = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            piece_square="f3",
        )
        root_index = next(index for index, root in enumerate(local.roots) if root.root_uci == "f3g5")
        root = local.roots[root_index]
        line_index = next(index for index, item in enumerate(root.lines) if item.moves[1] == "c5d4")
        stale = root.lines[line_index]
        wrong_moves = (stale.moves[0], "c5a3", *stale.moves[2:])
        bad_lines = (*root.lines[:line_index], replace(stale, moves=wrong_moves), *root.lines[line_index + 1:])
        bad_root = replace(root, lines=bad_lines)
        malformed = replace(local, roots=(*local.roots[:root_index], bad_root, *local.roots[root_index + 1:]))

        with pytest.raises(ValueError, match="deltas do not match"):
            assess_overload(position, malformed)

    asyncio.run(run())
