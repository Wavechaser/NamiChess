from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import chess

from namichess.analysis.engine import EngineCandidate, EngineScore, ScoreBound
from namichess.analysis.evidence import Explanation
from namichess.analysis.local import LocalLimits, explore_local
from namichess.analysis.threats import ThreatConclusion, ThreatReplyOutcome
from namichess.application.analysis import AnalysisResult, AnalysisState, _assemble
from namichess.application.candidate_structure import build_root_structures
from namichess.application.session import Session
from namichess.application.threats import select_threats
from namichess.interfaces.cli import render_analysis, render_details
from namichess.interfaces.explanations import ExplanationCatalog


FEN = "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1"
ROOT = "c3f6"
CATALOG = ExplanationCatalog.load(Path(__file__).parents[2] / "namichess" / "content" / "explanations.json")


def result_with_threats() -> AnalysisResult:
    view = Session().load_fen(FEN)
    local = asyncio.run(explore_local(
        view.position,
        limits=LocalLimits(seconds=1.0, max_depth=3, node_limit=10_000),
        deadline=10.0,
        monotonic=lambda: 0.0,
        root_moves=(ROOT,),
        request_id=7,
    ))
    probe = EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (ROOT,), 1, 1, 0.0)
    candidates, explanations, evidence = _assemble(
        7, view.revision, chess.Board(FEN), view.position, (ROOT,), {ROOT: probe}, (probe,),
        build_root_structures(view.position, 7, (ROOT,)), local,
    )
    return AnalysisResult(
        7, view.revision, AnalysisState.COMPLETED, candidates,
        explanations, evidence, local=local,
    )


def test_compact_row_leads_with_verified_coverage_and_two_group_examples() -> None:
    result = result_with_threats()

    row = render_analysis(result, CATALOG).splitlines()[-1]

    assert "queen h4 can be captured after every legal reply (6/6)" in row
    assert "5 king replies allow Bxh4" in row
    assert "Qc4 allows Qxc4+" in row
    assert row.index("queen h4 can be captured") < row.index("opens queen c1's check")
    assert "queen won" not in row and "forced gain" not in row


def test_compact_partial_result_explicitly_denies_universal_coverage() -> None:
    result = result_with_threats()
    root = result.local.roots[0]
    threat = root.threats[0]
    response = dataclasses.replace(
        threat.responses[0], outcome=ThreatReplyOutcome.NO_IMMEDIATE_CAPTURE,
        capture_uci=None, capture_san=None, capture_actor=None,
        capture_source=None, capture_destination=None, exchange=None,
    )
    threat = dataclasses.replace(
        threat, conclusion=ThreatConclusion.CAPTURE_AVAILABLE_SOME_REPLY,
        responses=(response, *threat.responses[1:]),
    )
    local = dataclasses.replace(
        result.local, roots=(dataclasses.replace(root, threats=(threat,)),),
    )
    candidate = dataclasses.replace(
        result.candidates[0],
        threat_selection=select_threats(local, local.position_id, ROOT),
    )

    row = render_analysis(dataclasses.replace(result, candidates=(candidate,), local=local), CATALOG).splitlines()[-1]

    assert "can be captured after 5 of 6 legal replies" in row
    assert "other replies avoid an immediate capture" in row
    assert "after every legal reply" not in row
    assert "king moves allow" not in row


def test_opponent_mate_warning_precedes_threat_summary() -> None:
    result = result_with_threats()
    candidate = result.candidates[0]
    warning = Explanation(
        "warning", "candidate.allows_opponent_mate_in_one", (("reply_count", 1),),
    )
    candidate = dataclasses.replace(candidate, explanation_refs=("warning",))
    result = dataclasses.replace(
        result, candidates=(candidate,), explanations=(*result.explanations, warning),
    )

    row = render_analysis(result, CATALOG).splitlines()[-1]

    assert row.index("opponent has 1 mate-in-one") < row.index("queen h4 can be captured")


def test_details_precede_pv_and_show_every_response_role_capture_and_exchange_model() -> None:
    result = result_with_threats()

    details = render_details(result, 1, CATALOG)

    assert details.index("Checking-threat evidence:") < details.index("Evidence: engine_survey")
    assert details.count("  Response ") == 6
    assert "roles: king move" in details
    assert "Qc4 (h4c4); roles: interpose; target on c4" in details
    assert "capture available: queen c1 can play Qxc4+ [c1→c4]" in details
    assert "exchange unsupported; model target_square_material" in details
    assert "safe capture" not in details and "profitable" not in details


def test_details_include_threats_omitted_from_compact_selection() -> None:
    result = result_with_threats()
    root = result.local.roots[0]
    local = dataclasses.replace(
        result.local,
        roots=(dataclasses.replace(root, threats=(root.threats[0],) * 3),),
    )
    selection = select_threats(local, local.position_id, ROOT)
    assert selection is not None and selection.omitted_count == 1
    candidate = dataclasses.replace(result.candidates[0], threat_selection=selection)
    result = dataclasses.replace(result, candidates=(candidate,), local=local)

    row = render_analysis(result, CATALOG).splitlines()[-1]
    details = render_details(result, 1, CATALOG)

    assert "2 more threat(s) in details" in row
    assert "Threat 3:" in details
