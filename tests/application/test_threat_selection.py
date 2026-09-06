from __future__ import annotations

import asyncio
import dataclasses
import json

import chess

from namichess.analysis.engine import EngineCandidate, EngineScore, ScoreBound
from namichess.analysis.local import LocalLimits, explore_local
from namichess.analysis.threats import ThreatConclusion
from namichess.application.analysis import AnalysisResult, AnalysisState, _assemble
from namichess.application.candidate_structure import build_root_structures
from namichess.application.session import Session
from namichess.application.threats import ThreatReference, resolve_threat, select_threats
from namichess.domain.models import PieceId, PositionId
from namichess.interfaces.serialization import serialize_session_view


FEN = "8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1"
ROOT = "c3e5"


def local_evidence(request_id: int = 3, view=None):
    view = view or Session().load_fen(FEN)
    local = asyncio.run(explore_local(
        view.position,
        limits=LocalLimits(seconds=1.0, max_depth=3, node_limit=10_000),
        deadline=10.0,
        monotonic=lambda: 0.0,
        root_moves=(ROOT,),
        request_id=request_id,
    ))
    return view, local


def test_selection_groups_response_indices_and_resolves_exact_raw_threat() -> None:
    view, local = local_evidence()

    selection = select_threats(local, view.position.position_id, ROOT)

    assert selection is not None and selection.omitted_count == 0
    assert len(selection.threats) == 1
    selected = selection.threats[0]
    raw = resolve_threat(local, selected.reference)
    assert raw is local.roots[0].threats[0]
    assert sorted(index for group in selected.response_groups for index in group.response_indices) == list(
        range(len(raw.responses))
    )
    for group in selected.response_groups:
        for index in group.response_indices:
            response = raw.responses[index]
            assert (
                response.outcome, response.roles, response.capture_actor,
                response.capture_san, response.target_square.square,
            ) == (
                group.outcome, group.roles, group.capture_actor,
                group.capture_san, group.target_square,
            )


def test_selection_prioritizes_complete_results_then_major_current_targets() -> None:
    view, local = local_evidence()
    root = local.roots[0]
    sample = root.threats[0]
    major = PieceId(1, 1, "h2", "black", "queen")
    minor = PieceId(1, 1, "g2", "black", "knight")
    threats = (
        dataclasses.replace(sample, effect=dataclasses.replace(sample.effect, target=minor)),
        dataclasses.replace(sample, effect=dataclasses.replace(sample.effect, target=major)),
        dataclasses.replace(
            sample, effect=dataclasses.replace(sample.effect, target=major),
            conclusion=ThreatConclusion.CAPTURE_AVAILABLE_SOME_REPLY,
        ),
        dataclasses.replace(
            sample, effect=dataclasses.replace(sample.effect, target=minor),
            conclusion=ThreatConclusion.INCOMPLETE,
        ),
    )
    ranked = dataclasses.replace(
        local, roots=(dataclasses.replace(root, threats=threats),),
    )

    selection = select_threats(ranked, view.position.position_id, ROOT)

    assert selection is not None and selection.omitted_count == 2
    assert [item.reference.threat_index for item in selection.threats] == [1, 0]


def test_resolver_rejects_wrong_scope_and_negative_index() -> None:
    view, local = local_evidence()
    position = view.position.position_id

    for reference, message in (
        (ThreatReference(PositionId(99, 1, ()), local.roots[0].root_delta.after, ROOT, 0), "different position"),
        (ThreatReference(position, local.roots[0].root_delta.after, "a1a2", 0), "unavailable root"),
        (ThreatReference(position, local.roots[0].root_delta.after, ROOT, -1), "out of range"),
    ):
        try:
            resolve_threat(local, reference)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("invalid threat reference was accepted")

    _, another_request = local_evidence(request_id=4, view=view)
    reference = select_threats(local, position, ROOT).threats[0].reference
    try:
        resolve_threat(another_request, reference)
    except ValueError as error:
        assert "different root position" in str(error)
    else:
        raise AssertionError("request-scoped threat reference was accepted for another request")


def test_provisional_candidate_gets_reference_selection_when_local_evidence_exists() -> None:
    view, local = local_evidence()
    board = chess.Board(FEN)
    survey = (EngineCandidate(
        EngineScore(0, None, None, ScoreBound.EXACT), (ROOT,), 1, 1, 0.0,
    ),)
    structures = build_root_structures(view.position, 3, (ROOT,))

    candidates, _, _ = _assemble(
        3, view.revision, board, view.position, (ROOT,), {}, survey, structures, local,
    )

    assert candidates[0].provisional
    assert candidates[0].threat_selection is not None
    reference = candidates[0].threat_selection.threats[0].reference
    assert resolve_threat(local, reference) is local.roots[0].threats[0]


def test_serialized_candidate_reference_closes_over_retained_local_evidence() -> None:
    view, local = local_evidence()
    board = chess.Board(FEN)
    probe = EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (ROOT,), 1, 1, 0.0)
    candidates, explanations, evidence = _assemble(
        3, view.revision, board, view.position, (ROOT,), {ROOT: probe}, (probe,),
        build_root_structures(view.position, 3, (ROOT,)), local,
    )
    result = AnalysisResult(
        3, view.revision, AnalysisState.COMPLETED, candidates,
        explanations, evidence, local=local,
    )

    payload = json.loads(serialize_session_view(dataclasses.replace(view, analysis=result)))
    serialized = payload["analysis"]["candidates"][0]["threat_selection"]
    reference = serialized["threats"][0]["reference"]

    assert reference["position_id"] == payload["analysis"]["local"]["position_id"]
    assert reference["root_uci"] == payload["analysis"]["local"]["roots"][0]["root_uci"]
    assert reference["root_position_id"] == payload["analysis"]["local"]["roots"][0]["root_delta"]["after"]
    assert reference["threat_index"] == 0
    assert "effect" not in serialized["threats"][0]
