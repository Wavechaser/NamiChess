import dataclasses
import json

from namichess.application.analysis import AnalysisResult, AnalysisState, Coverage
from namichess.application.session import Session
from namichess.interfaces.cli import render_json
from namichess.interfaces.serialization import serialize_session_view


def test_shared_serializer_preserves_schema_one_session_without_analysis() -> None:
    view = Session().load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")

    serialized = serialize_session_view(view)
    payload = json.loads(serialized)

    assert payload["schema_version"] == 1
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
