from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
import chess

from namichess.analysis.engine import EngineCandidate, EngineReport, EngineScore, EngineStatus, ScoreBound, StockfishAdapter
from namichess.analysis.evidence import line_consequences
from namichess.analysis.static import move_delta
from namichess.application.analysis import AnalysisController, AnalysisPolicy, AnalysisState, _current_tactics, _pv_deltas
from namichess.domain.models import PieceId, PositionContext
from namichess.domain.validation import parse_fen


FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures" / "m1_05_counterexamples.json").read_text())


def context(fen: str) -> PositionContext:
    return PositionContext(1, 1, (), fen, (), fen, False)


def candidate(uci: str, cp: int, *, bound: ScoreBound = ScoreBound.EXACT) -> EngineCandidate:
    return EngineCandidate(EngineScore(cp, None, None, bound), (uci,), 10, 100, 0.1)


class FakeEngine:
    def __init__(self) -> None:
        self.calls = []
        self.prepares = 0
        self.cancel_count = 0

    async def prepare(self):
        self.prepares += 1
        return "fake"

    async def analyze(self, position, policy, *, progress=None):
        self.calls.append(policy)
        if not policy.root_moves:
            return EngineReport(EngineStatus.COMPLETED, (candidate("g1f3", 10), candidate("e2e4", 20)))
        cp = {"e2e4": 30, "g1f3": 30}.get(policy.root_moves[0], 5)
        return EngineReport(EngineStatus.COMPLETED, (candidate(policy.root_moves[0], cp),))

    async def cancel(self):
        self.cancel_count += 1

    async def close(self):
        pass


def test_candidate_ids_are_uci_sorted_and_equal_scores_tie_break_by_uci() -> None:
    async def exercise():
        engine = FakeEngine()
        controller = AnalysisController(engine)
        controller.submit(context("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"), 4)
        result = await controller.wait()
        assert result is not None
        assert [(item.candidate_id, item.rank) for item in result.candidates] == [
            ("request:1:revision:4:position:1:1:root:candidate:e2e4", 1),
            ("request:1:revision:4:position:1:1:root:candidate:g1f3", 2),
        ]
        assert [call.root_moves for call in engine.calls] == [(), ("e2e4",), ("g1f3",)]
    asyncio.run(exercise())


def test_terminal_position_never_prepares_engine() -> None:
    async def exercise():
        engine = FakeEngine()
        controller = AnalysisController(engine)
        controller.submit(context("7k/5Q2/7K/8/8/8/8/8 b - - 0 1"), 1)
        result = await controller.wait()
        assert result is not None and result.state is AnalysisState.COMPLETED
        assert engine.prepares == 0
    asyncio.run(exercise())


def test_bound_only_candidate_is_provisional_and_unranked() -> None:
    class BoundEngine(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            if not policy.root_moves:
                return EngineReport(EngineStatus.COMPLETED, (candidate("e2e4", 20),))
            return EngineReport(EngineStatus.COMPLETED, (candidate("e2e4", 25, bound=ScoreBound.LOWER),))

    async def exercise():
        controller = AnalysisController(BoundEngine())
        controller.submit(context("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"), 1)
        result = await controller.wait()
        assert result is not None
        assert result.candidates[0].provisional
        assert result.candidates[0].rank is None
    asyncio.run(exercise())


@pytest.mark.parametrize("name", tuple(FIXTURES))
def test_counterexample_fixture_is_a_legal_composed_position(name: str) -> None:
    board = parse_fen(FIXTURES[name])
    assert board.king(True) is not None and board.king(False) is not None


def test_counterexamples_encode_the_specific_legal_traps_and_limits() -> None:
    poisoned = parse_fen(FIXTURES["poisoned_capture"])
    poisoned.push_uci("d1d2")
    assert chess.Move.from_uci("d8d2") in poisoned.legal_moves

    sacrifice = parse_fen(FIXTURES["sound_sacrifice"])
    assert sacrifice.is_capture(chess.Move.from_uci("d3h7"))

    pinned = parse_fen(FIXTURES["pinned_recapture"])
    assert pinned.is_pinned(chess.BLACK, chess.E7)

    evasion = parse_fen(FIXTURES["forced_evasion"])
    assert evasion.is_check()
    assert all(move.from_square == chess.E1 for move in evasion.legal_moves)

    capped = parse_fen(FIXTURES["capped_choice"])
    assert sum(1 for _ in capped.legal_moves) > 5

    for name in ("mate_over_material", "mate_over_material_mirror"):
        board = parse_fen(FIXTURES[name])
        assert any((board.push(move), board.is_checkmate(), board.pop())[1] for move in list(board.legal_moves))


def test_explicit_move_outside_survey_is_included_and_duplicates_are_unique() -> None:
    async def exercise():
        engine = FakeEngine()
        controller = AnalysisController(engine)
        controller.submit(context(FIXTURES["capped_choice"]), 1, ("a2a3", "a2a3"))
        result = await controller.wait()
        assert result is not None
        assert [item.uci for item in result.candidates] == ["a2a3", "e2e4", "g1f3"]
        assert result.coverage.requested == 3
    asyncio.run(exercise())


def test_static_opponent_mate_refutes_a_contradictory_exact_top_score() -> None:
    class MateBlindEngine(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            if not policy.root_moves:
                return EngineReport(EngineStatus.COMPLETED, (candidate("f2f3", 900), candidate("h4f3", 0)))
            return EngineReport(EngineStatus.COMPLETED, (candidate(policy.root_moves[0], 900 if policy.root_moves[0] == "f2f3" else 0),))
    async def exercise():
        controller = AnalysisController(MateBlindEngine())
        controller.submit(context(FIXTURES["mate_blunder"]), 8)
        result = await controller.wait()
        assert result is not None
        blunder = next(item for item in result.candidates if item.uci == "f2f3")
        assert blunder.rank is None and blunder.provisional
        assert any(item.catalog_id == "candidate.allows_opponent_mate_in_one" for item in result.explanations)
        mate_evidence = next(item for item in result.evidence if item.kind == "legal_opponent_mate_in_one")
        assert mate_evidence.line == ()
        for line in mate_evidence.alternative_lines:
            replay = parse_fen(FIXTURES["mate_blunder"])
            for uci in line:
                move = chess.Move.from_uci(uci)
                assert move in replay.legal_moves
                replay.push(move)
            assert replay.is_checkmate()
    asyncio.run(exercise())


def test_failure_requires_an_explicit_retry_and_completed_cancel_is_noop() -> None:
    class Flaky(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            if len(self.calls) == 0:
                self.calls.append(policy)
                return EngineReport(EngineStatus.FAILED, message="crash")
            return await super().analyze(position, policy, progress=progress)
    async def exercise():
        engine = Flaky()
        controller = AnalysisController(engine)
        position = context(FIXTURES["capped_choice"])
        controller.submit(position, 1)
        failed = await controller.wait()
        assert failed is not None and failed.state is AnalysisState.FAILED
        assert len(engine.calls) == 1
        controller.submit(position, 1)
        completed = await controller.wait()
        assert completed is not None and completed.state is AnalysisState.COMPLETED
        await controller.cancel()
        assert controller.latest == completed
    asyncio.run(exercise())


def test_catalog_placeholders_match_typed_explanation_values() -> None:
    catalog = json.loads((Path(__file__).parents[2] / "namichess" / "content" / "explanations.json").read_text())
    assert "{winner}" in catalog["engine.reported_mate"]
    assert "{moves}" in catalog["engine.reported_mate"]
    assert "{material_delta_white}" in catalog["line.capture"]


def test_rapid_supersession_cancels_running_search_and_rejects_late_progress() -> None:
    class GateEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.first_callback = None

        async def analyze(self, position, policy, *, progress=None):
            if self.first_callback is None:
                self.first_callback = progress
                await self.release.wait()
                return EngineReport(EngineStatus.CANCELED)
            return await super().analyze(position, policy, progress=progress)

        async def cancel(self):
            self.cancel_count += 1
            self.release.set()

    async def exercise():
        engine = GateEngine()
        controller = AnalysisController(engine)
        position = context(FIXTURES["capped_choice"])
        controller.submit(position, 1)
        await asyncio.sleep(0)
        controller.submit(position, 2)
        result = await controller.wait()
        assert result is not None and result.revision == 2 and result.state is AnalysisState.COMPLETED
        current_progress = controller.progress
        assert engine.first_callback is not None
        engine.first_callback(type("Progress", (), {"candidates": (), "elapsed_seconds": 99.0})())
        assert controller.progress is current_progress
        assert engine.cancel_count == 1
    asyncio.run(exercise())


def test_cancel_between_probes_preserves_completed_probe_evidence() -> None:
    class ProbeGate(FakeEngine):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def analyze(self, position, policy, *, progress=None):
            if not policy.root_moves:
                return await super().analyze(position, policy, progress=progress)
            if policy.root_moves == ("e2e4",):
                return await super().analyze(position, policy, progress=progress)
            await self.release.wait()
            return EngineReport(EngineStatus.CANCELED)

        async def cancel(self):
            self.cancel_count += 1
            self.release.set()

    async def exercise():
        engine = ProbeGate()
        controller = AnalysisController(engine)
        controller.submit(context(FIXTURES["capped_choice"]), 1)
        while controller.latest is None or not controller.latest.evidence:
            await asyncio.sleep(0)
        await controller.cancel()
        assert controller.latest is not None and controller.latest.state is AnalysisState.CANCELED
        assert any(item.kind == "engine_line" for item in controller.latest.evidence)
        assert engine.cancel_count >= 1
    asyncio.run(exercise())


def test_supersession_during_prepare_cancels_before_search_and_close_waits() -> None:
    class Preparing(FakeEngine):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def prepare(self):
            self.prepares += 1
            await self.release.wait()
            return "fake"

        async def cancel(self):
            self.cancel_count += 1
            self.release.set()

    async def exercise():
        engine = Preparing()
        controller = AnalysisController(engine)
        position = context(FIXTURES["capped_choice"])
        controller.submit(position, 1)
        await asyncio.sleep(0)
        controller.submit(position, 2)
        result = await controller.wait()
        assert result is not None and result.revision == 2
        assert engine.cancel_count == 1 and engine.prepares == 2
        await controller.close()
        assert controller._worker is None
    asyncio.run(exercise())


def test_outer_deadline_cancels_a_stalled_individual_search() -> None:
    class Stalled(FakeEngine):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def analyze(self, position, policy, *, progress=None):
            await self.release.wait()
            return EngineReport(EngineStatus.CANCELED)

        async def cancel(self):
            self.cancel_count += 1
            self.release.set()

    async def exercise():
        engine = Stalled()
        controller = AnalysisController(engine, policy=AnalysisPolicy(seconds=0.02, survey_seconds=0.02))
        controller.submit(context(FIXTURES["capped_choice"]), 1)
        result = await asyncio.wait_for(controller.wait(), 0.3)
        assert result is not None and result.coverage.interrupted
        assert engine.cancel_count == 1
    asyncio.run(exercise())


def test_black_mover_rank_uses_black_perspective_and_mate_winner() -> None:
    class BlackEngine(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            roots = policy.root_moves
            if not roots:
                return EngineReport(EngineStatus.COMPLETED, (candidate("e7e5", -20), candidate("a7a6", -100)))
            if roots == ("e7e5",):
                value = EngineCandidate(EngineScore(None, -3, "black", ScoreBound.EXACT), roots, 8, 50, 0.1)
            else:
                value = candidate(roots[0], -500)
            return EngineReport(EngineStatus.COMPLETED, (value,))
    async def exercise():
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
        controller = AnalysisController(BlackEngine())
        controller.submit(context(fen), 1)
        result = await controller.wait()
        assert result is not None
        ranked = sorted(result.candidates, key=lambda item: item.rank or 99)
        assert ranked[0].uci == "e7e5"
        mate = next(e for e in result.explanations if e.catalog_id == "engine.reported_mate")
        assert ("winner", "black") in mate.values
    asyncio.run(exercise())


def test_more_than_two_or_illegal_comparison_moves_fail_before_prepare() -> None:
    async def exercise():
        engine = FakeEngine()
        controller = AnalysisController(engine)
        position = context(FIXTURES["capped_choice"])
        controller.submit(position, 1, ("a2a3", "b2b3", "c2c3"))
        assert (await controller.wait()).state is AnalysisState.FAILED
        controller.submit(position, 2, ("a2a5",))
        assert (await controller.wait()).state is AnalysisState.FAILED
        assert engine.prepares == 0
    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("fen", "uci", "captured_type", "promotion", "white_delta"),
    (
        ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", "e5d6", "pawn", None, 1),
        ("7k/P7/8/8/8/8/8/7K w - - 0 1", "a7a8q", None, "queen", 8),
    ),
)
def test_line_material_is_white_perspective_for_en_passant_and_promotion(fen, uci, captured_type, promotion, white_delta) -> None:
    before = context(fen)
    board = parse_fen(fen)
    board.push_uci(uci)
    after = PositionContext(1, 1, (-1, 1), fen, (uci,), board.fen(en_passant="fen"), False)
    consequence = line_consequences(parse_fen(fen), (uci,), (move_delta(before, after),))[0]
    assert consequence.captured_piece_type == captured_type
    assert consequence.promotion == promotion
    assert consequence.material_delta_white == white_delta


@pytest.mark.skipif(not os.environ.get("NAMICHESS_TEST_ENGINE"), reason="set NAMICHESS_TEST_ENGINE for the real adapter gate")
def test_real_default_controller_reuses_engine_and_finishes_all_restricted_probes() -> None:
    async def exercise():
        controller = AnalysisController(StockfishAdapter(os.environ["NAMICHESS_TEST_ENGINE"]))
        try:
            for revision in (1, 2):
                controller.submit(context(chess.STARTING_FEN), revision)
                result = await controller.wait()
                assert result is not None and result.state is AnalysisState.COMPLETED
                assert len(result.candidates) >= 1
                assert result.coverage.probed >= 1
                assert result.coverage.total_legal == 20
                for item in result.candidates:
                    if item.rank is not None:
                        assert item.score is not None and item.score.bound is ScoreBound.EXACT
                        assert not item.provisional
                    elif item.score is not None and item.score.bound is not ScoreBound.EXACT:
                        assert item.provisional
        finally:
            await controller.close()
    asyncio.run(exercise())


@pytest.mark.skipif(not os.environ.get("NAMICHESS_TEST_ENGINE"), reason="set NAMICHESS_TEST_ENGINE for the real adapter gate")
def test_real_rapid_supersession_has_no_asyncio_protocol_errors_and_recovers() -> None:
    async def exercise():
        loop = asyncio.get_running_loop()
        errors = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        adapter = StockfishAdapter(os.environ["NAMICHESS_TEST_ENGINE"])
        controller = AnalysisController(adapter, policy=AnalysisPolicy(seconds=0.35, survey_seconds=0.1))
        try:
            position = context(chess.STARTING_FEN)
            for revision in range(1, 8):
                controller.submit(position, revision)
                await asyncio.sleep(0.005)
            latest = await controller.wait()
            assert latest is not None and latest.revision == 7
            controller.submit(position, 8)
            recovered = await controller.wait()
            assert recovered is not None and recovered.state is AnalysisState.COMPLETED
            assert recovered.candidates and recovered.coverage.probed >= 1
            await asyncio.sleep(0.05)
            assert errors == []
        finally:
            await controller.close()
            loop.set_exception_handler(previous_handler)
        assert adapter._active_task is None
        assert adapter._protocol is None and adapter._transport is None
    asyncio.run(exercise())


def test_cancel_targets_captured_request_without_canceling_or_waiting_for_replacement() -> None:
    class TwoRequestEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.first_release = asyncio.Event()
            self.first_settled = asyncio.Event()
            self.second_release = asyncio.Event()
            self.analyses = 0

        async def analyze(self, position, policy, *, progress=None):
            self.analyses += 1
            if self.analyses == 1:
                await self.first_release.wait()
                await self.first_settled.wait()
                return EngineReport(EngineStatus.CANCELED)
            if self.analyses == 2:
                await self.second_release.wait()
            return await super().analyze(position, policy, progress=progress)

        async def cancel(self):
            self.cancel_count += 1
            self.first_release.set()

    async def exercise():
        engine = TwoRequestEngine()
        controller = AnalysisController(engine)
        position = context(FIXTURES["capped_choice"])
        first_id = controller.submit(position, 1)
        await asyncio.sleep(0)
        canceling = asyncio.create_task(controller.cancel())
        await engine.first_release.wait()
        second_id = controller.submit(position, 2)
        engine.first_settled.set()
        await asyncio.wait_for(canceling, 0.2)
        assert first_id != second_id
        assert controller.latest is not None and controller.latest.request_id == second_id
        assert controller.latest.state is AnalysisState.RUNNING
        engine.second_release.set()
        result = await controller.wait()
        assert result is not None and result.request_id == second_id

    asyncio.run(exercise())


def test_close_is_absorbing_idempotent_and_shared_while_cleanup_runs() -> None:
    class ClosingEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.close_entered = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_count = 0

        async def close(self):
            self.close_count += 1
            self.close_entered.set()
            await self.close_release.wait()

    async def exercise():
        engine = ClosingEngine()
        controller = AnalysisController(engine)
        first = asyncio.create_task(controller.close())
        await engine.close_entered.wait()
        second = asyncio.create_task(controller.close())
        with pytest.raises(RuntimeError, match="closed"):
            controller.submit(context(FIXTURES["capped_choice"]), 1)
        assert not first.done() and not second.done()
        engine.close_release.set()
        await asyncio.gather(first, second)
        await controller.close()
        assert engine.close_count == 1

    asyncio.run(exercise())


def test_close_immediately_after_submit_cancels_unstarted_request_without_engine_work() -> None:
    async def exercise():
        engine = FakeEngine()
        controller = AnalysisController(engine)
        request_id = controller.submit(context(FIXTURES["capped_choice"]), 1)
        await controller.close()
        assert engine.prepares == 0 and engine.calls == []
        assert controller.latest is not None
        assert controller.latest.request_id == request_id
        assert controller.latest.state is AnalysisState.CANCELED
        unchanged = controller.latest
        await controller.close()
        assert controller.latest == unchanged

    asyncio.run(exercise())


def test_close_settles_active_request_to_a_nonrunning_state() -> None:
    class ActiveEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def analyze(self, position, policy, *, progress=None):
            self.entered.set()
            await self.release.wait()
            return EngineReport(EngineStatus.CANCELED)

        async def cancel(self):
            self.cancel_count += 1
            self.release.set()

    async def exercise():
        engine = ActiveEngine()
        controller = AnalysisController(engine)
        controller.submit(context(FIXTURES["capped_choice"]), 1)
        await engine.entered.wait()
        await controller.close()
        assert controller.latest is not None
        assert controller.latest.state is not AnalysisState.RUNNING

    asyncio.run(exercise())


def test_survey_probe_sign_disagreement_preserves_both_typed_scores() -> None:
    class SignFlip(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            if not policy.root_moves:
                return EngineReport(EngineStatus.COMPLETED, (candidate("e2e4", 20),))
            return EngineReport(EngineStatus.COMPLETED, (candidate("e2e4", -25),))

    async def exercise():
        controller = AnalysisController(SignFlip())
        controller.submit(context(FIXTURES["capped_choice"]), 3)
        result = await controller.wait()
        assert result is not None
        candidate_result = result.candidates[0]
        assert candidate_result.survey_score.centipawns == 20
        assert candidate_result.score.centipawns == -25
        explanation = next(item for item in result.explanations if item.catalog_id == "engine.survey_final_disagreement")
        linked = {item.evidence_id: item.score for item in result.evidence if item.evidence_id in explanation.evidence_refs}
        assert {score.centipawns for score in linked.values()} == {20, -25}
        linked_evidence = [item for item in result.evidence if item.evidence_id in explanation.evidence_refs]
        assert all(item.san_line == ("e4",) for item in linked_evidence)
        assert all(item.engine_elapsed_seconds == 0.1 for item in linked_evidence)
    asyncio.run(exercise())


def test_principal_variations_on_different_roots_have_distinct_synthetic_positions() -> None:
    position = context(FIXTURES["capped_choice"])
    e4 = _pv_deltas(position, 7, ("e2e4", "e7e5"))
    knight = _pv_deltas(position, 7, ("g1f3", "g8f6"))
    assert e4[1].before != knight[1].before
    assert e4[1].after != knight[1].after


def test_current_check_references_the_replayed_checker_identity_and_scoped_evidence() -> None:
    position = context(FIXTURES["forced_evasion"])
    board = parse_fen(position.current_fen)
    explanations, evidence = _current_tactics(board, position, 3, 9)
    check = next(item for item in explanations if item.catalog_id == "position.in_check")
    assert check.pieces == (PieceId(1, 1, "e2", "black", "rook"),)
    assert evidence[0].evidence_id == "request:3:revision:9:position:1:1:root:current-check"
    assert check.evidence_refs == (evidence[0].evidence_id,)


def test_mate_alternatives_are_distinct_legal_lines_and_scoped_per_request() -> None:
    position = context(FIXTURES["mate_over_material"])
    board = parse_fen(position.current_fen)
    _, first = _current_tactics(board, position, 1, 4)
    _, repeated = _current_tactics(board, position, 2, 4)
    evidence = next(item for item in first if item.kind == "legal_mate_in_one")
    assert len(evidence.alternative_lines) > 1
    assert len(set(evidence.alternative_lines)) == len(evidence.alternative_lines)
    assert len(evidence.alternative_san_lines) == len(evidence.alternative_lines)
    for line in evidence.alternative_lines:
        replay = board.copy(stack=True)
        for uci in line:
            move = chess.Move.from_uci(uci)
            assert move in replay.legal_moves
            replay.push(move)
        assert replay.is_checkmate()
    assert first[0].evidence_id != repeated[0].evidence_id


def test_position_facts_precede_generic_engine_line_explanations() -> None:
    class MateEngine(FakeEngine):
        async def analyze(self, position, policy, *, progress=None):
            return EngineReport(EngineStatus.COMPLETED, (candidate("f7f8", 1000),))

    async def exercise():
        controller = AnalysisController(MateEngine())
        controller.submit(context(FIXTURES["mate_over_material"]), 1)
        result = await controller.wait()
        assert result is not None
        assert result.explanations[0].catalog_id == "position.mate_in_one"
        assert any(item.catalog_id == "line.check" for item in result.explanations[1:])

    asyncio.run(exercise())
