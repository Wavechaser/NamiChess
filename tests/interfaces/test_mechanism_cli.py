from __future__ import annotations

import dataclasses
from pathlib import Path

import chess
import pytest

from namichess.application.analysis import AnalysisResult, AnalysisState, CandidateResult
from namichess.application.candidate_structure import build_root_structures
from namichess.application.preview import preview_candidate_line
from namichess.application.session import Session
from namichess.interfaces.cli import (
    render_analysis, render_board, render_details, render_line_preview,
)
from namichess.interfaces.explanations import ExplanationCatalog


CATALOG = ExplanationCatalog.load(Path(__file__).parents[2] / "namichess" / "content" / "explanations.json")


def mirrored(fen: str, uci: str) -> tuple[str, str]:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    return board.mirror().fen(en_passant="fen"), chess.Move(
        chess.square_mirror(move.from_square), chess.square_mirror(move.to_square),
        promotion=move.promotion,
    ).uci()


def candidate_result(fen: str, uci: str) -> tuple[Session, AnalysisResult]:
    session = Session()
    view = session.load_fen(fen)
    structure = build_root_structures(view.position, 3, (uci,))[uci]
    candidate = CandidateResult(
        candidate_id=f"candidate:{uci}", position_id=view.position.position_id,
        uci=uci, san=chess.Board(fen).san(chess.Move.from_uci(uci)),
        mover_color=view.turn, rank=1, score=None, pv=(uci,), provisional=False,
        explanation_refs=(), evidence_refs=(), root_structure=structure,
    )
    return session, AnalysisResult(3, view.revision, AnalysisState.COMPLETED, (candidate,))


@pytest.mark.parametrize("mirror", (False, True))
def test_candidate_and_preview_name_double_check_roles_and_geometric_fork(mirror: bool) -> None:
    fen = "8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1"
    uci = "c3e5"
    if mirror:
        fen, uci = mirrored(fen, uci)
    session, result = candidate_result(fen, uci)

    summary = render_analysis(result, CATALOG)
    details = render_details(result, 1, CATALOG)
    shared = dataclasses.replace(session.view(), analysis=result)
    preview = render_line_preview(preview_candidate_line(shared, 1, 1), CATALOG)

    for output in (summary, details, preview):
        assert "double check" in output
        assert "(discovered)" in output
        assert "geometrically forks" in output
        assert "king " in output and "queen " in output
        assert "wins" not in output and "can capture" not in output
    assert preview.count("double check") == 1


@pytest.mark.parametrize("mirror", (False, True))
def test_discovered_check_keeps_complementary_bishop_attack_separate(mirror: bool) -> None:
    fen = "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1"
    uci = "c3f6"
    if mirror:
        fen, uci = mirrored(fen, uci)
    session, _ = candidate_result(fen, uci)
    view = session.play(uci)

    output = render_board(view, catalog=CATALOG)

    checker = "queen c8" if mirror else "queen c1"
    king = "king c2" if mirror else "king c7"
    assert f"opens {checker}'s check on {king}" in output
    assert ("bishop f3" if mirror else "bishop f6") in output
    assert "now geometrically attacks queen" in output
    assert "geometrically forks" not in output
    assert output.count("check on") == 1


def test_single_check_fork_includes_king_without_claiming_a_win() -> None:
    session = Session()
    session.load_fen("8/2k5/8/8/8/2B5/3P3r/K7 w - - 0 1")

    output = render_board(session.play("c3e5"), catalog=CATALOG)

    assert "bishop e5 checks king c7" in output
    assert "bishop e5 geometrically forks" in output
    assert "king c7" in output and "rook h2" in output
    assert "wins" not in output and "capturable" not in output


def test_pinned_attacker_fork_stays_geometric_while_pin_remains_structured() -> None:
    session = Session()
    session.load_fen("4r2k/8/8/8/8/2n3r1/4R3/4K3 w - - 0 1")

    view = session.play("e2e3")
    output = render_board(view, catalog=CATALOG)

    assert "rook e3 geometrically forks" in output
    assert "knight c3" in output and "rook g3" in output
    assert any(pin.piece == view.previous_move.moved.piece for pin in view.facts.pins)
    assert "wins" not in output and "can capture" not in output


def test_imported_double_check_names_both_checkers_without_inferring_roles() -> None:
    session = Session()
    view = session.load_fen("4k3/8/8/1B6/8/8/4R3/K7 b - - 0 1")

    output = render_board(view, catalog=CATALOG)

    assert "Check: double check on king e8 by rook e2 and bishop b5" in output
    assert "(discovered)" not in output
