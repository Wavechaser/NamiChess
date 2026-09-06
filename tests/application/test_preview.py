from __future__ import annotations

import dataclasses

import pytest

import namichess.application.preview as preview_module
from namichess.application.analysis import AnalysisResult, AnalysisState, CandidateResult
from namichess.application.preview import PreviewError, preview_candidate_line
from namichess.application.session import Session


def _candidate(view, uci: str, pv: tuple[str, ...]) -> CandidateResult:
    return CandidateResult(
        "request:7:revision:1:position:preview:candidate:" + uci,
        view.position.position_id,
        uci,
        uci,
        view.turn,
        1,
        None,
        pv,
        False,
        (),
        (),
    )


@pytest.mark.parametrize(
    ("fen", "uci", "expected"),
    [
        ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8q", "queen"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "rook"),
        ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", "e5d6", "pawn"),
    ],
)
def test_non_cli_preview_reconstructs_special_move_without_mutating_session(fen: str, uci: str, expected: str) -> None:
    session = Session()
    source = session.load_fen(fen)
    candidate = _candidate(source, uci, (uci,))
    shared = dataclasses.replace(source, analysis=AnalysisResult(7, source.revision, AnalysisState.COMPLETED, (candidate,)))

    root = preview_candidate_line(shared, 1, 0)
    preview = preview_candidate_line(shared, 1, 1)

    assert root.context == source.position
    assert root.parent_position_id is None
    assert preview.previous_move.uci == uci
    assert preview.mechanisms is not None
    assert preview.mechanisms.after == preview.context.position_id
    assert preview.context.document_id == source.position.document_id
    assert preview.context.game_number == source.position.game_number
    assert preview.context.starting_fen == source.position.starting_fen
    assert preview.context.moves == (*source.position.moves, uci)
    assert any(piece.piece_type == expected for piece in preview.facts.pieces)
    assert session.view().position == source.position
    assert session.view().revision == source.revision
    assert session.view().variations == source.variations


def test_preview_rejects_stale_candidate_and_invalid_ply() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    candidate = _candidate(view, "h1h2", ("h1h2",))
    stale = dataclasses.replace(view, analysis=AnalysisResult(7, view.revision - 1, AnalysisState.COMPLETED, (candidate,)))
    with pytest.raises(PreviewError, match="no current analysis"):
        preview_candidate_line(stale, 1, 0)

    current = dataclasses.replace(view, analysis=AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)))
    with pytest.raises(PreviewError, match="ply must be between 0 and 1"):
        preview_candidate_line(current, 1, 2)


def test_preview_rejects_a_pv_that_does_not_start_with_the_candidate() -> None:
    view = Session().load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    candidate = _candidate(view, "a1a2", ("a1b1",))
    current = dataclasses.replace(
        view, analysis=AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)),
    )
    with pytest.raises(PreviewError, match="begin"):
        preview_candidate_line(current, 1, 0)


def test_preview_computes_each_delta_endpoint_once(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Session().load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
    candidate = _candidate(source, "a1a2", ("a1a2",))
    shared = dataclasses.replace(
        source, analysis=AnalysisResult(7, source.revision, AnalysisState.COMPLETED, (candidate,)),
    )
    real_position_facts = preview_module.position_facts
    calls = []

    def counted_position_facts(context):
        calls.append(context.position_id)
        return real_position_facts(context)

    monkeypatch.setattr(preview_module, "position_facts", counted_position_facts)
    preview = preview_candidate_line(shared, 1, 1)

    assert preview.previous_move is not None
    assert calls == [preview.context.position_id, preview.previous_move.before]
