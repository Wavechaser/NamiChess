from __future__ import annotations

import asyncio

import chess
import pytest

import namichess.application.candidate_structure as structure_module
from namichess.analysis.consequences import resolve_raw_fact
from namichess.analysis.engine import EngineCandidate, EngineReport, EngineScore, EngineStatus, ScoreBound
from namichess.application.analysis import AnalysisController, AnalysisState, ProbeSubject
from namichess.application.candidate_structure import build_root_structures
from namichess.domain.models import PositionContext


def context(fen: str) -> PositionContext:
    return PositionContext(1, 1, (), fen, (), fen, False)


def test_equal_defender_counts_with_different_identities_are_contrasted() -> None:
    structures = build_root_structures(
        context(chess.STARTING_FEN), 7, ("g1h3", "b1c3"),
        max_defense_changes=100,
    )
    knight = next(
        change for change in structures["g1h3"].defense_changes
        if change.subject.origin_square == "g1"
    )

    assert len(knight.after_defenders) == 1
    assert len(knight.baseline_defenders) == len(knight.after_defenders)
    assert knight.baseline_defenders != knight.after_defenders
    other = next(root for root in knight.contrasting_roots if root.uci == "b1c3")
    peer = next(
        change for change in structures[other.uci].defense_changes
        if change.subject == knight.subject
    )
    assert len(peer.after_defenders) == len(knight.after_defenders)
    assert peer.after_defenders != knight.after_defenders
    assert other.position_id == structures[other.uci].delta.after


def test_unchanged_candidate_state_is_included_when_another_root_differs() -> None:
    structures = build_root_structures(
        context(chess.STARTING_FEN), 7, ("e2e3", "e2e4", "g1f3"),
        max_defense_changes=100,
    )
    pawn = next(
        change for change in structures["e2e3"].defense_changes
        if change.subject.origin_square == "d2"
    )

    assert pawn.after_defenders == pawn.baseline_defenders
    assert [root.uci for root in pawn.contrasting_roots] == ["g1f3"]


def test_identical_changed_defense_state_across_roots_is_not_a_contrast() -> None:
    structures = build_root_structures(
        context(chess.STARTING_FEN), 7, ("g1h3", "g1f3"),
        max_defense_changes=100,
    )

    assert all(
        change.subject.origin_square != "f1"
        for structure in structures.values()
        for change in structure.defense_changes
    )


def test_piece_captured_in_one_root_is_excluded_from_all_root_comparisons() -> None:
    fen = "7k/8/8/3p4/4P3/8/8/K7 w - - 0 1"
    structures = build_root_structures(context(fen), 7, ("e4d5", "e4e5"), max_defense_changes=100)
    captured = structures["e4d5"].delta.captured

    assert captured is not None
    assert all(
        change.subject != captured.piece_id
        for structure in structures.values()
        for change in structure.defense_changes
    )


@pytest.mark.parametrize("promotion", ("q", "r", "b", "n"))
def test_root_delta_preserves_current_promotion_type(promotion: str) -> None:
    uci = "a7a8" + promotion
    structure = build_root_structures(
        context("4k3/P7/8/8/8/8/8/4K3 w - - 0 1"), 7, (uci,),
    )[uci]

    assert structure.delta.promoted
    assert structure.delta.moved.after.piece_type == chess.piece_name(chess.PIECE_SYMBOLS.index(promotion))
    assert structure.account.after == structure.delta.after


def test_root_structure_selection_is_bounded_and_raw_sources_close() -> None:
    structures = build_root_structures(
        context(chess.STARTING_FEN), 7, ("e2e3", "e2e4", "g1f3"),
    )

    assert all(len(structure.defense_changes) <= 3 for structure in structures.values())
    assert any(structure.omitted_count > 0 for structure in structures.values())
    for structure in structures.values():
        assert all(
            resolve_raw_fact(structure.delta, source) is not None
            for event in structure.account.consequences
            for source in event.supporting_facts
        )
        assert all(
            resolve_raw_fact(structure.delta, source) is not None
            for change in structure.defense_changes
            for source in change.supporting_facts
        )
        after_ids = {item.piece_id for item in structure.delta.after_pieces}
        assert all(change.subject in after_ids for change in structure.defense_changes)
        assert all(change.square.position_id == structure.delta.after for change in structure.defense_changes)


def test_mirrored_roots_preserve_comparison_shape_and_flip_color() -> None:
    white = build_root_structures(context(chess.STARTING_FEN), 7, ("g1h3", "b1c3"), max_defense_changes=100)
    mirrored_fen = chess.Board(chess.STARTING_FEN).mirror().fen(en_passant="fen")
    black = build_root_structures(context(mirrored_fen), 7, ("g8h6", "b8c6"), max_defense_changes=100)

    assert [len(white[root].defense_changes) for root in ("g1h3", "b1c3")] == [
        len(black[root].defense_changes)
        for root in ("g8h6", "b8c6")
    ]
    assert {change.subject.color for change in white["g1h3"].defense_changes} == {"white"}
    assert {change.subject.color for change in black["g8h6"].defense_changes} == {"black"}


def test_request_computes_structure_once_and_reuses_it_in_partials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_position_facts = structure_module.position_facts
    fact_calls = 0

    def counted_position_facts(position):
        nonlocal fact_calls
        fact_calls += 1
        return real_position_facts(position)

    monkeypatch.setattr(structure_module, "position_facts", counted_position_facts)

    class Engine:
        controller: AnalysisController

        def __init__(self) -> None:
            self.partials = []

        async def prepare(self): return "fixture"

        async def analyze(self, position, policy, *, progress=None):
            latest = self.controller.latest
            if latest is not None and latest.state is AnalysisState.RUNNING and latest.candidates:
                self.partials.append(latest)
            roots = policy.root_moves
            if not roots:
                return EngineReport(EngineStatus.COMPLETED, (
                    EngineCandidate(EngineScore(20, None, None, ScoreBound.EXACT), ("e2e4",), 1, 1, 0.0),
                    EngineCandidate(EngineScore(10, None, None, ScoreBound.EXACT), ("g1f3",), 1, 1, 0.0),
                ))
            return EngineReport(EngineStatus.COMPLETED, (
                EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), roots, 1, 1, 0.0),
            ))

        async def cancel(self): pass
        async def close(self): pass

    async def exercise() -> None:
        engine = Engine()
        controller = AnalysisController(engine)
        engine.controller = controller
        controller.submit_probe(context(chess.STARTING_FEN), 1, ProbeSubject.for_move("a2a3"))
        final = await controller.wait()

        assert final is not None and engine.partials
        assert fact_calls == 1 + final.coverage.requested
        final_by_uci = {item.uci: item.root_structure for item in final.candidates}
        assert all(structure is not None for structure in final_by_uci.values())
        assert any(item.provisional and item.root_structure is not None for item in engine.partials[0].candidates)
        for partial in engine.partials:
            for item in partial.candidates:
                assert item.root_structure is final_by_uci[item.uci]

    asyncio.run(exercise())
