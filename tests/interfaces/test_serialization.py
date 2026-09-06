import dataclasses
import asyncio
import json
from pathlib import Path

from namichess.analysis.engine import EngineCandidate, EngineReport, EngineScore, EngineStatus, ScoreBound
from namichess.analysis.local import LocalLimits
from namichess.application.analysis import AnalysisController, AnalysisPolicy, AnalysisResult, AnalysisState, Coverage
from namichess.application.session import Session
from namichess.application.preview import preview_candidate_line
from namichess.domain.position import replay_position
from namichess.interfaces.cli import render_json
from namichess.interfaces.serialization import serialize_session_view


ASSESSMENT_FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "assessments.json").read_text(encoding="utf-8")
)


def test_shared_serializer_preserves_schema_one_session_without_analysis() -> None:
    view = Session().load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")

    serialized = serialize_session_view(view)
    payload = json.loads(serialized)

    assert payload["schema_version"] == 2
    assert payload["analysis"] is None
    assert payload["session"]["analysis"] is None
    assert payload["session"]["position"]["current_fen"] == "7k/8/8/8/8/8/8/K7 w - - 0 1"
    assert payload["session"]["facts"]["turn"] == "white"
    assert serialize_session_view(view) == render_json(view)


def test_shared_serializer_detaches_analysis_at_the_existing_top_level() -> None:
    view = Session().load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    result = AnalysisResult(
        request_id=3,
        revision=view.revision,
        state=AnalysisState.RUNNING,
        coverage=Coverage(0, 0, len(view.facts.legal_moves), False),
    )

    payload = json.loads(serialize_session_view(dataclasses.replace(view, analysis=result)))

    assert payload["session"]["analysis"] is None
    assert payload["analysis"]["request_id"] == 3
    assert payload["analysis"]["state"] == "running"
    assert payload["analysis"]["coverage"]["surveyed"] == 0
    assert payload["analysis"]["coverage"]["interrupted"] is False


def test_shared_serializer_characterizes_terminal_and_promoted_positions() -> None:
    terminal = Session().load_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    terminal_payload = json.loads(serialize_session_view(terminal))
    assert terminal_payload["session"]["status"] == "checkmate"
    assert terminal_payload["session"]["outcome"] == "1-0"

    session = Session()
    session.load_fen("7k/P7/8/8/8/8/8/4K3 w - - 0 1")
    promoted = session.play("a8=N")
    promoted_payload = json.loads(serialize_session_view(promoted))
    promoted_piece = next(
        piece for piece in promoted_payload["session"]["pieces"] if piece["square"] == "a8"
    )
    assert promoted_piece["piece_type"] == "knight"
    assert promoted_piece["piece_id"]["origin_square"] == "a7"
    assert serialize_session_view(promoted) == render_json(promoted)


def test_schema_two_serializes_structural_relationships() -> None:
    view = Session().load_fen("4k3/8/8/8/3p4/2P5/3P4/2B1K3 w - - 0 1")

    payload = json.loads(serialize_session_view(view))
    facts = payload["session"]["facts"]

    assert payload["schema_version"] == 2
    assert {contact["kind"] for contact in facts["contacts"]} == {"attack", "defend"}
    assert isinstance(facts["geometrically_undefended"], list)
    assert isinstance(facts["latent_rays"], list)


def test_non_cli_consumer_resolves_immediate_navigation_references() -> None:
    session = Session()
    session.load_pgn("1. e4 e5 *\n")
    root = session.start()
    payload = json.loads(serialize_session_view(root))["session"]
    assert payload["parent_position_id"] is None
    assert len(payload["child_position_ids"]) == 1
    child = session.next()
    child_id = json.loads(json.dumps(dataclasses.asdict(child.position.position_id)))
    root_id = json.loads(json.dumps(dataclasses.asdict(root.position.position_id)))
    assert payload["child_position_ids"][0] == child_id
    assert json.loads(json.dumps(dataclasses.asdict(child.parent_position_id))) == root_id


def _assert_shared_reference_closure(payload: dict) -> set[str]:
    session = payload["session"]
    analysis = payload["analysis"]
    assert analysis is not None

    positions = {json.dumps(session["facts"]["position_id"], sort_keys=True)}
    pieces = {
        json.dumps(item["piece_id"], sort_keys=True)
        for item in session["facts"]["pieces"]
    }
    for root in analysis["local"]["roots"]:
        for line in root["lines"]:
            for delta in line["deltas"]:
                positions.update(
                    json.dumps(delta[name], sort_keys=True) for name in ("before", "after")
                )
                pieces.update(
                    json.dumps(item["piece_id"], sort_keys=True)
                    for name in ("before_pieces", "after_pieces")
                    for item in delta[name]
                )
    for evidence in analysis["evidence"]:
        consequences = evidence["consequences"]
        for index, consequence in enumerate(consequences):
            assert consequence["source"]["position_id"] == consequence["position_id"]
            if index + 1 < len(consequences):
                assert consequence["target"]["position_id"] == consequences[index + 1]["position_id"]
            positions.add(json.dumps(consequence["position_id"], sort_keys=True))
            positions.add(json.dumps(consequence["target"]["position_id"], sort_keys=True))

    def assert_references(value) -> None:
        if isinstance(value, list):
            for item in value:
                assert_references(item)
            return
        if not isinstance(value, dict):
            return
        if {"document_id", "game_number", "origin_square", "color", "original_piece_type"} <= value.keys():
            assert json.dumps(value, sort_keys=True) in pieces
            return
        if set(value) == {"position_id", "square"}:
            assert json.dumps(value["position_id"], sort_keys=True) in positions
            return
        if set(value) == {"document_id", "game_number", "node_path"}:
            assert json.dumps(value, sort_keys=True) in positions
            return
        for item in value.values():
            assert_references(item)

    assert_references(session["facts"])
    assert_references(analysis)

    evidence_ids = {item["evidence_id"] for item in analysis["evidence"]}
    explanation_ids = {item["explanation_id"] for item in analysis["explanations"]}
    assert len(evidence_ids) == len(analysis["evidence"])
    assert len(explanation_ids) == len(analysis["explanations"])
    for explanation in analysis["explanations"]:
        assert set(explanation["evidence_refs"]) <= evidence_ids
        assert all(json.dumps(piece, sort_keys=True) in pieces for piece in explanation["pieces"])
        assert all(json.dumps(square["position_id"], sort_keys=True) in positions for square in explanation["squares"])
    for candidate in analysis["candidates"]:
        assert set(candidate["evidence_refs"]) <= evidence_ids
        assert set(candidate["explanation_refs"]) <= explanation_ids
        assert candidate["position_id"] == session["facts"]["position_id"]

    roots = {root["root_uci"]: root for root in analysis["local"]["roots"]}
    kinds = set()
    assessments = (*analysis["move_safety"], *analysis["trapping"], *analysis["overload"])
    for assessment in assessments:
        for reference in assessment["evidence"]:
            kinds.add(reference["kind"])
            root = roots[reference["root_uci"]]
            if reference["kind"] == "local_line":
                assert root["lines"][reference["line_index"]]["moves"][0] == reference["root_uci"]
            elif reference["kind"] == "exchange":
                assert root["exchange"]["line"][0] == reference["root_uci"]
            else:
                reply = root["lines"][reference["line_index"]]["reply_exchange"]
                assert reply["line"][0] == root["lines"][reference["line_index"]]["moves"][1]
        for exposure in assessment.get("material_exposures", ()):
            reference = exposure["evidence"]
            assert reference["kind"] == "reply_exchange"
            root = roots[reference["root_uci"]]
            assert root["lines"][reference["line_index"]]["reply_exchange"] is not None
            kinds.add(reference["kind"])
    return kinds


def test_non_cli_snapshot_keeps_real_local_producer_assessment_references_closed() -> None:
    class Engine:
        async def prepare(self): return "fixture"
        async def analyze(self, context, policy, *, progress=None):
            board, _ = replay_position(context)
            move = policy.root_moves[0] if policy.root_moves else next(iter(board.legal_moves)).uci()
            return EngineReport(EngineStatus.COMPLETED, (
                EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (move,), 1, 1, 0.0),
            ))
        async def cancel(self): pass
        async def close(self): pass

    async def exercise() -> None:
        session = Session()
        session.load_fen("8/8/8/8/8/1r6/2k5/KR6 w - - 0 1")
        limits = LocalLimits(seconds=0.2, max_depth=2, node_limit=100)
        controller = AnalysisController(
            Engine(), policy=AnalysisPolicy(
                seconds=0.3, survey_seconds=0.05, local=limits,
                focused_seconds=0.3, focused_local=limits,
            ),
        )
        try:
            session.request_probe(controller, session.resolve_probe("move", "b1h1"))
            result = await controller.wait()
            assert result is not None and result.local is not None and result.move_safety
            shared = session.analysis_view(controller)
            complete_payload = json.loads(serialize_session_view(shared))
            payload = complete_payload["analysis"]
            assert "local_line" in _assert_shared_reference_closure(complete_payload)
            roots = {root["root_uci"]: root for root in payload["local"]["roots"]}
            assert {item["root_uci"] for item in payload["move_safety"]} <= roots.keys()
            assert any(item["evidence"] for item in payload["move_safety"])
            for assessment in payload["move_safety"]:
                root = roots[assessment["root_uci"]]
                for reference in assessment["evidence"]:
                    assert reference["root_uci"] == assessment["root_uci"]
                    if reference["kind"] == "local_line":
                        assert root["lines"][reference["line_index"]]
                    elif reference["kind"] == "exchange":
                        assert root["exchange"] is not None
                    else:
                        assert reference["kind"] == "reply_exchange"
                        assert root["lines"][reference["line_index"]]["reply_exchange"] is not None
            preview = preview_candidate_line(shared, 1, 1)
            assert preview.source_position_id == shared.position.position_id
            assert preview.context.position_id == preview.previous_move.after
            assert preview.previous_move.uci == shared.analysis.candidates[0].pv[0]
        finally:
            await controller.close()
    asyncio.run(exercise())


def test_non_cli_consumer_resolves_all_assessment_evidence_kinds() -> None:
    class Engine:
        async def prepare(self): return "fixture"
        async def analyze(self, context, policy, *, progress=None):
            board, _ = replay_position(context)
            move = policy.root_moves[0] if policy.root_moves else next(iter(board.legal_moves)).uci()
            return EngineReport(EngineStatus.COMPLETED, (
                EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (move,), 1, 1, 0.0),
            ))
        async def cancel(self): pass
        async def close(self): pass

    async def snapshot(fen: str, kind: str, value: str) -> dict:
        session = Session()
        session.load_fen(fen)
        limits = LocalLimits(seconds=1.0, max_depth=2, node_limit=10_000)
        controller = AnalysisController(
            Engine(), policy=AnalysisPolicy(
                seconds=0.2, survey_seconds=0.02, local=limits,
                focused_seconds=0.3, focused_local=limits,
            ),
        )
        try:
            session.request_probe(controller, session.resolve_probe(kind, value))
            result = await controller.wait()
            assert result is not None and result.state is AnalysisState.COMPLETED
            return json.loads(serialize_session_view(session.analysis_view(controller)))
        finally:
            await controller.close()

    async def exercise() -> None:
        exchange = await snapshot(ASSESSMENT_FIXTURES["negative_exchange_sacrifice"], "move", "e4d5")
        reply_exchange = await snapshot(ASSESSMENT_FIXTURES["quiet_material_exposure"], "piece", "e2")
        kinds = _assert_shared_reference_closure(exchange) | _assert_shared_reference_closure(reply_exchange)
        assert {"exchange", "reply_exchange"} <= kinds
        exposures = reply_exchange["analysis"]["trapping"][0]["material_exposures"]
        assert any(item["exit_uci"] == "e2e4" and item["reply_uci"] == "d5e4" for item in exposures)

    asyncio.run(exercise())
