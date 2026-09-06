from pathlib import Path

import pytest

from namichess.application.imports import ImportError
from namichess.application.analysis import AnalysisResult, AnalysisState
from namichess.application.session import Session, SessionError
from namichess.application.views import PositionStatus


FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_navigation_variations_and_trial_move_reuse() -> None:
    session = Session()
    loaded = session.load_pgn((FIXTURES / "multi_game.pgn").read_text(encoding="utf-8"))
    assert loaded.selected_game == 1
    assert loaded.selected_ply == 2
    root = session.start()
    assert root.variations == ("e4", "d4")
    branch = session.variation(2)
    assert branch.position.moves == ("d2d4",)
    end = session.end()
    assert end.position.moves == ("d2d4", "d7d5")
    session.back()
    first = session.play("d5")
    session.back()
    second = session.play("d7d5")
    assert first.position.node_path == second.position.node_path


def test_failed_load_preserves_current_session() -> None:
    session = Session()
    before = session.load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    with pytest.raises(ImportError):
        session.load_pgn("1. e4")
    after = session.view()
    assert after.position == before.position
    assert after.status is PositionStatus.STALEMATE


@pytest.mark.parametrize("pgn", ("1. e4# *", "1. e4+ *", "1. e2e4 *"))
def test_noncanonical_pgn_load_preserves_current_session(pgn: str) -> None:
    session = Session()
    before = session.load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")

    with pytest.raises(ImportError, match="noncanonical SAN"):
        session.load_pgn(pgn)

    assert session.view().position == before.position


def test_oversized_fen_counter_is_actionable_and_preserves_session() -> None:
    session = Session()
    before = session.load_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    with pytest.raises(ImportError, match="reload"):
        session.load_fen(f"7k/5Q2/6K1/8/8/8/8/8 b - - 0 {'9' * 5000}")
    assert session.view().position == before.position


def test_piece_identity_survives_promotion_and_castling() -> None:
    session = Session()
    root = session.load_fen("4k3/P7/8/8/8/8/8/4K2R w K - 0 1")
    pawn = next(piece for piece in root.pieces if piece.square == "a7")
    promoted = session.play("a8=Q")
    queen = next(piece for piece in promoted.pieces if piece.square == "a8")
    assert queen.piece_id == pawn.piece_id
    assert queen.promoted
    session.back()
    castled = session.play("O-O")
    assert {piece.square for piece in castled.pieces} >= {"g1", "f1"}


def test_unavailable_navigation_is_actionable() -> None:
    session = Session()
    session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    with pytest.raises(SessionError, match="end"):
        session.next()


def test_shared_view_exposes_position_facts_and_previous_move_delta() -> None:
    session = Session()
    root = session.load_fen("k3r3/8/8/8/8/8/4N3/4K3 w - - 0 1")
    knight = next(piece for piece in root.facts.pieces if piece.square == "e2")
    assert any(pin.piece == knight.piece_id for pin in root.facts.pins)
    assert any(attack.attacker == knight.piece_id and attack.target.square == "c3" for attack in root.facts.attacks)
    assert not any(move.mover == knight.piece_id and move.target.square == "c3" for move in root.facts.legal_moves)
    assert root.previous_move is None

    moved = session.play("Kd2")
    assert moved.previous_move is not None
    assert moved.previous_move.uci == "e1d2"
    assert moved.previous_move.san == "Kd2"
    assert moved.previous_move.before == root.facts.position_id
    assert moved.previous_move.after == moved.facts.position_id


def test_analysis_view_filters_results_from_another_revision() -> None:
    session = Session()
    first = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")

    class ControllerView:
        latest = AnalysisResult(1, first.revision, AnalysisState.COMPLETED)

    controller = ControllerView()
    assert session.analysis_view(controller).analysis == controller.latest  # type: ignore[arg-type]
    session.play("Ra2")
    assert session.analysis_view(controller).analysis is None  # type: ignore[arg-type]


def test_request_analysis_rejects_stale_supplied_view_before_submission() -> None:
    session = Session()
    stale = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
    session.play("Ra2")

    class Controller:
        latest = None
        submitted = False

        def submit(self, *args, **kwargs):
            self.submitted = True

    controller = Controller()
    with pytest.raises(SessionError, match="stale"):
        session.request_analysis(controller, view=stale)  # type: ignore[arg-type]
    assert not controller.submitted
