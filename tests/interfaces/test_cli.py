import asyncio
import dataclasses
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import chess
import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from namichess.application.session import Session, SessionError
from namichess.application.preview import preview_candidate_line
from namichess.application.imports import ImportError as ChessImportError
from namichess.analysis.engine import EngineCandidate, EngineProgress, EngineReport, EngineScore, EngineStatus, ScoreBound
from namichess.analysis.consequences import ConsequenceKind, MoveAccount, MoveConsequence
from namichess.analysis.evidence import Evidence, Explanation, LineConsequence
from namichess.analysis.assessments import (
    AssessmentConclusion, AssessmentCoverage, CoverageUnit, EvidenceKind,
    EvidenceRef, MaterialExposure, TrappingAssessment,
)
from namichess.application.analysis import AnalysisController, AnalysisResult, AnalysisState, CandidateResult, Coverage
from namichess.application.candidate_structure import build_root_structures
from namichess.domain.models import PieceId, PositionContext, PositionId, SquareRef
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.interfaces.orientation import BoardDisplayState, Orientation, ResolvedOrientation
from namichess.interfaces.settings import SettingsStore
from namichess.interfaces.cli import (
    execute, execute_async, render_analysis, render_board, render_changes, render_details,
    render_inspection, render_json, render_line_preview, run_cli,
)


CATALOG = ExplanationCatalog.load(Path(__file__).parents[2] / "namichess" / "content" / "explanations.json")


class ImmediateEngine:
    def __init__(self):
        self.prepares = 0

    async def prepare(self):
        self.prepares += 1
        return "fixture"

    async def analyze(self, position, policy, *, progress=None):
        move = policy.root_moves[0] if policy.root_moves else "a1a2"
        return EngineReport(
            EngineStatus.COMPLETED,
            (EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (move,), 8, 12, 0.01),),
        )

    async def cancel(self):
        pass

    async def close(self):
        pass


def test_cli_fen_board_move_and_navigation_transcript() -> None:
    session = Session()
    output, done = execute(session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1")
    assert "a b c d e f g h" in output
    assert "Turn: white" in output
    assert not done
    output, _ = execute(session, "move Ka2")
    assert "Turn: black" in output
    assert "Ka2: king a1→a2" in output
    output, _ = execute(session, "back")
    assert "Turn: white" in output


def test_cli_orientation_persists_defaults_but_local_flips_do_not_change_chess_state(tmp_path) -> None:
    settings = SettingsStore(tmp_path / "NamiChess" / "settings.json")
    settings.save_orientation(Orientation.TURN)
    session = Session()
    display = BoardDisplayState()
    output, _ = execute(
        session, "fen 7k/8/8/8/8/8/8/K7 b - - 0 1",
        display_state=display, settings_store=settings,
    )
    assert output.startswith("1 . . . . . . . K")
    assert "Orientation: black" in output
    revision = session.view().revision
    canonical = render_json(session.view())
    output, _ = execute(session, "flip", display_state=display, settings_store=settings)
    assert output.startswith("8 . . . . . . . k")
    assert display.orientation is ResolvedOrientation.WHITE
    assert session.view().revision == revision
    assert render_json(session.view()) == canonical
    execute(session, "orientation default black", display_state=display, settings_store=settings)
    assert display.orientation is ResolvedOrientation.WHITE
    output, _ = execute(
        session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1",
        display_state=display, settings_store=settings,
    )
    assert "Orientation: black" in output


def test_cli_import_orientation_precedence_and_failed_import_keep_display_state(tmp_path) -> None:
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save_orientation(Orientation.BLACK)
    session = Session()
    display = BoardDisplayState()
    output, _ = execute(
        session, "fen 7k/8/8/8/8/8/8/K7 b - - 0 1",
        display_state=display, settings_store=settings, orientation_override=Orientation.TURN,
    )
    assert "Orientation: black" in output
    output, _ = execute(
        session, "fen --orientation white 7k/8/8/8/8/8/8/K7 b - - 0 1",
        display_state=display, settings_store=settings, orientation_override=Orientation.TURN,
    )
    assert "Orientation: white" in output
    assert "saved default: black" in execute(
        session, "orientation", display_state=display, settings_store=settings,
    )[0]
    with pytest.raises(ChessImportError):
        execute(session, "fen --orientation black invalid", display_state=display, settings_store=settings)
    assert display.orientation is ResolvedOrientation.WHITE


def test_cli_orientation_reports_invalid_saved_settings_without_claiming_it_is_saved(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{", encoding="utf-8")
    output, _ = execute(
        Session(), "orientation", display_state=BoardDisplayState(), settings_store=SettingsStore(path),
    )
    assert "default fallback: white" in output
    assert "valid UTF-8 JSON" in output


def test_cli_games_lists_fen_as_one_game() -> None:
    session = Session()
    execute(session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1")
    output, _ = execute(session, "games")
    assert "* 1:" in output


def test_cli_inspect_distinguishes_geometric_attack_from_legal_access() -> None:
    session = Session()
    execute(session, "fen k3r3/8/8/8/8/8/4N3/4K3 w - - 0 1")
    output, _ = execute(session, "inspect c3")
    assert "Geometric attackers: e2 white knight" in output
    assert "Legal access (white to move): none" in output
    assert "Absolute pins: e2 white knight" in output


def test_cli_inspect_uses_current_square_for_a_moved_pinned_piece() -> None:
    session = Session()
    execute(session, "fen k3r3/8/8/8/8/2N5/8/4K3 w - - 0 1")
    execute(session, "move Ne2")
    output, _ = execute(session, "inspect d4")
    assert "Geometric attackers: e2 white knight" in output
    assert "Absolute pins: e2 white knight" in output
    assert "c3 white knight" not in output


def test_cli_inspect_uses_current_promoted_piece_type() -> None:
    session = Session()
    execute(session, "fen 4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    execute(session, "move a8=Q")
    output, _ = execute(session, "inspect b7")
    assert "Geometric attackers: a8 white queen" in output
    assert "white pawn" not in output


def test_cli_inspect_rejects_invalid_square() -> None:
    session = Session()
    execute(session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1")
    with pytest.raises(SessionError, match="inspect requires a square from a1 to h8"):
        execute(session, "inspect z9")


def test_cli_changes_and_line_dispatch_do_not_move_the_session() -> None:
    session = Session()
    view = session.load_fen("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    candidate = CandidateResult(
        "request:7:revision:1:position:test:candidate:a7a8q", view.position.position_id,
        "a7a8q", "a8=Q", "white", 1, None, ("a7a8q",), False, (), (),
    )
    shared = dataclasses.replace(view, analysis=AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)))
    controller = type("Controller", (), {"latest": shared.analysis})()

    changes, _ = execute(session, "changes", controller=controller)
    line, _ = execute(session, "line 1 1", controller=controller)

    assert changes == "No move leads into this position."
    assert "Candidate line: a8=Q (a7a8q), ply 1" in line
    assert "promoted to queen" in line
    assert session.view().position == view.position
    assert session.view().revision == view.revision


def test_changes_names_removed_defenders_and_opened_relationships_after_e4() -> None:
    session = Session()
    session.load_fen(chess.STARTING_FEN)
    execute(session, "move e4")
    output, _ = execute(session, "changes")
    assert "Contact removed: d1 white queen defends e2 white pawn" in output
    assert "Geometrically undefended after the move: e4 white pawn" in output
    assert "Latent slider ray removed: f1 white bishop nw, blocked by e2 white pawn" in output


def test_board_changes_and_preview_load_at_most_one_fallback_catalog_and_reuse_injected_catalog(
    monkeypatch,
) -> None:
    session = Session()
    session.load_fen(chess.STARTING_FEN)
    session.play("e4")
    view = session.view()
    candidate = CandidateResult(
        "candidate:e7e5", view.position.position_id, "e7e5", "e5", "black", 1,
        None, ("e7e5",), False, (), (),
    )
    shared = dataclasses.replace(
        view, analysis=AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)),
    )
    preview = preview_candidate_line(shared, 1, 1)
    loads = 0

    def load_catalog() -> ExplanationCatalog:
        nonlocal loads
        loads += 1
        return CATALOG

    monkeypatch.setattr("namichess.interfaces.cli._load_catalog", load_catalog)

    standalone_board = render_board(view)
    assert loads == 1
    standalone_changes = render_changes(view)
    assert loads == 2
    standalone_preview = render_line_preview(preview)
    assert loads == 3

    assert render_board(view, catalog=CATALOG) == standalone_board
    assert render_changes(view, CATALOG) == standalone_changes
    assert render_line_preview(preview, CATALOG) == standalone_preview
    controller = type("Controller", (), {"latest": shared.analysis})()
    execute(session, "board", controller=controller, catalog=CATALOG)
    execute(session, "line 1 1", controller=controller, catalog=CATALOG)
    assert loads == 3


def test_changes_names_an_added_absolute_pin() -> None:
    session = Session()
    session.load_fen("4r1k1/8/8/8/8/2N5/8/4K3 w - - 0 1")
    execute(session, "move Ne2")
    output, _ = execute(session, "changes")
    assert "Absolute pin added: e2 white knight to e1 white king" in output


def test_capture_promotion_distinguishes_a_removed_piece_from_new_defence() -> None:
    session = Session()
    session.load_fen("r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    execute(session, "move bxa8=Q+")
    output, _ = execute(session, "changes")
    assert "Geometrically undefended before the move: a8 black rook" in output


def test_quiet_move_uses_connected_account_and_keeps_raw_changes_in_explicit_details() -> None:
    session = Session()
    session.load_fen(chess.STARTING_FEN)
    compact, _ = execute(session, "move e4")
    detailed, _ = execute(session, "changes")

    assert "pawn e4 is now unguarded" in compact
    assert "Contact removed:" not in compact
    assert "Raw changes:" in detailed
    assert "Contact removed: d1 white queen defends e2 white pawn" in detailed


@pytest.mark.parametrize(
    ("fen", "move", "effects"),
    (
        ("7k/8/8/3p4/4P3/8/8/K7 w - - 0 1", "exd5", ("captured pawn on d5",)),
        ("K7/8/8/8/4pP2/8/8/7k b - f3 0 1", "exf3", ("captured pawn on f4",)),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O", ("rook h1→f1",)),
        ("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1", "O-O-O", ("rook a8→d8",)),
        ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a8=Q+", ("promoted to queen", "gives check")),
    ),
)
def test_compact_account_keeps_mandatory_direct_move_effects(fen, move, effects) -> None:
    session = Session()
    session.load_fen(fen)

    output, _ = execute(session, f"move {move}")

    for effect in effects:
        assert effect in output


@pytest.mark.parametrize(
    ("fen", "move", "actor"),
    (
        ("r6k/8/8/8/8/8/B7/R6K w - - 0 1", "Bb3", "rook a8"),
        ("r6k/b7/8/8/8/8/8/R6K b - - 0 1", "Bb6", "rook a1"),
    ),
)
def test_opened_line_account_is_mirrored_without_assigning_the_mover_as_actor(fen, move, actor) -> None:
    session = Session()
    session.load_fen(fen)

    output, _ = execute(session, f"move {move}")

    assert f"opens {actor}'s line attack on" in output


def test_direct_effects_remain_visible_when_three_structural_account_slots_are_saturated() -> None:
    session = Session()
    session.load_fen("r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    view = session.play("bxa8=Q+")
    delta = view.previous_move
    assert delta is not None
    queen = delta.moved.piece
    king = next(item.piece_id for item in delta.after_pieces if item.piece_type == "king" and item.color == "black")
    account = MoveAccount(
        delta.before, delta.after, delta.uci,
        (
            MoveConsequence(ConsequenceKind.LOST_DEFENSE, None, queen, None, None, None, ()),
            MoveConsequence(ConsequenceKind.PINNED, None, queen, None, None, king, ()),
            MoveConsequence(
                ConsequenceKind.GAINED_CONTROL, queen, None, None,
                SquareRef(delta.after, "b8"), None, (),
            ),
        ),
        2,
    )

    output = render_board(dataclasses.replace(view, move_account=account), catalog=CATALOG)

    assert "captured rook on a8" in output
    assert "promoted to queen" in output
    assert "gives check" in output
    assert "queen a8 is now unguarded" in output
    assert "queen a8 is pinned to king e8" in output
    assert "queen a8 now controls b8" in output
    assert "2 more move consequence(s); use changes for full raw details" in output


def test_discovered_check_does_not_name_the_moving_bishop_as_checker() -> None:
    session = Session()
    session.load_fen("4k3/8/8/8/8/8/4B3/4R2K w - - 0 1")

    output, _ = execute(session, "move Bc4")

    assert "gives check" in output
    assert "bishop gives check" not in output


@pytest.mark.parametrize(
    ("fen", "expected"),
    (
        ("7k/8/8/8/8/8/r7/R6K w - - 0 1", "rook a1 is attacked and geometrically undefended"),
        ("r6k/R7/8/8/8/8/8/7K b - - 0 1", "rook a8 is attacked and geometrically undefended"),
    ),
)
def test_import_renders_shared_attention_without_a_previous_move(fen, expected) -> None:
    output, _ = execute(Session(), f"fen {fen}")

    assert f"Attention: {expected}" in output
    assert "→" not in output


def test_back_to_root_renders_that_positions_attention_without_stale_move_account() -> None:
    session = Session()
    execute(session, "fen 7k/8/8/8/8/8/r7/R6K w - - 0 1")
    execute(session, "move Rxa2")

    output, _ = execute(session, "back")

    assert "Attention: rook a1 is attacked and geometrically undefended" in output
    assert "Rxa2:" not in output


def test_lost_defense_attention_replaces_overlapping_connected_account_clause() -> None:
    session = Session()
    session.load_fen("7k/8/8/1n6/2b5/3B4/8/K7 w - - 0 1")

    output, _ = execute(session, "move Bxc4")

    assert "Attention: knight b5 is now attacked and unguarded" in output
    assert "knight b5 is now unguarded" not in output
    assert "captured bishop on c4" in output


def test_candidate_line_preview_renders_its_shared_attention_and_deduplicates_account() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/1n6/2b5/3B4/8/K7 w - - 0 1")
    candidate = CandidateResult(
        "candidate:d3c4", view.position.position_id, "d3c4", "Bxc4", "white", 1,
        None, ("d3c4",), False, (), (),
    )
    shared = dataclasses.replace(
        view, analysis=AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)),
    )

    output = render_line_preview(preview_candidate_line(shared, 1, 1), CATALOG)

    assert "Attention: knight b5 is now attacked and unguarded" in output
    assert "knight b5 is now unguarded" not in output


def test_pinned_geometric_defender_does_not_gain_material_urgency_in_attention_text() -> None:
    session = Session()
    session.load_fen("4rr1k/8/8/8/8/8/4RP2/4K3 b - - 0 1")

    output, _ = execute(session, "move Rf4")

    assert "pawn f2 is attacked and geometrically undefended" not in output
    assert "pawn f2 is now attacked and unguarded" not in output
    assert "won" not in output and "safe" not in output


def test_explicit_check_status_does_not_repeat_checked_king_attention() -> None:
    output, _ = execute(Session(), "fen 7k/6Q1/7K/8/8/8/8/8 b - - 0 1")

    assert "Status: checkmate" in output
    assert "Attention:" not in output


def test_attention_omission_count_comes_from_shared_selection() -> None:
    output, _ = execute(Session(), "fen 7k/3n2n1/8/8/n2Q2n1/8/8/n6K w - - 0 1")

    assert output.count("is attacked and geometrically undefended") == 3
    assert "2 more attention item(s) omitted." in output


def test_cli_line_supports_ply_zero_and_renders_the_local_orientation() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    candidate = CandidateResult(
        "candidate:a1a2", view.position.position_id, "a1a2", "Ka2", "white", 1,
        None, ("a1a2",), False, (), (),
    )
    controller = type("Controller", (), {
        "latest": AnalysisResult(7, view.revision, AnalysisState.COMPLETED, (candidate,)),
    })()
    output, _ = execute(
        session, "line 1 0", controller=controller,
        display_state=BoardDisplayState(ResolvedOrientation.BLACK),
    )
    assert output.startswith("1 . . . . . . . K")
    assert "At the candidate-line root." in output
    assert "Source position:" not in output


def test_cli_probe_commands_resolve_san_and_piece_identity_without_moving_session() -> None:
    async def exercise() -> None:
        session = Session()
        before = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
        controller = AnalysisController(ImmediateEngine())
        await execute_async(session, "probe move Ra2", controller=controller, catalog=CATALOG)
        move_result = await controller.wait()
        assert move_result is not None and move_result.subject is not None
        assert move_result.subject.move == "a1a2"
        assert move_result.move_safety and move_result.move_safety[0].root_uci == "a1a2"
        await execute_async(session, "probe piece a1", controller=controller, catalog=CATALOG)
        piece_result = await controller.wait()
        assert piece_result is not None and piece_result.subject is not None
        assert piece_result.subject.piece == before.pieces[0].piece_id
        assert piece_result.trapping and piece_result.trapping[0].piece == before.pieces[0].piece_id
        concise = render_analysis(piece_result, CATALOG)
        assert "Fact: a1 white rook: Local exit assessment:" in concise
        assert "unrefuted_exit_found" not in concise
        assert concise.count("Fact:") <= 3
        inspected, _ = await execute_async(
            session, "inspect a1", controller=controller, catalog=CATALOG,
        )
        assert "Local exit assessment:" in inspected
        assert session.view().position == before.position
        assert session.view().revision == before.revision
        await controller.close()
    asyncio.run(exercise())


def test_cli_load_accepts_a_quoted_windows_path_with_spaces(tmp_path) -> None:
    source = tmp_path / "sample game.pgn"
    source.write_text("1. e4 *\n", encoding="utf-8")
    output, _ = execute(Session(), f'load "{source}"')
    assert "Turn: black" in output


def test_cli_load_treats_orientation_prefixed_filename_as_a_path(tmp_path, monkeypatch) -> None:
    source = tmp_path / "--orientation-notes.fen"
    source.write_text("7k/8/8/8/8/8/8/K7 w - - 0 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    output, _ = execute(Session(), 'load "--orientation-notes.fen"')
    assert "Turn: white" in output


def test_interactive_prompt_path_accepts_commands() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text("fen 7k/8/8/8/8/8/8/K7 w - - 0 1\nquit\n")
        result = asyncio.run(
            run_cli(Session(), stdout=stdout, stderr=stderr, prompt_input=pipe, prompt_output=DummyOutput())
        )
    assert result == 0
    assert "Turn: white" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_invalid_large_counter_keeps_session_and_cli_running() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    session = Session()
    commands = io.StringIO(
        "fen 7k/8/8/8/8/8/4P3/K7 w - - 0 1\n"
        + "fen 7k/8/8/8/8/8/4P3/K7 w - - 0 " + "9" * 5000
        + "\nboard\nquit\n"
    )
    result = asyncio.run(run_cli(session, stdin=commands, stdout=stdout, stderr=stderr))
    assert result == 0
    assert "fullmove counter" in stderr.getvalue()
    assert "1000000000" in stderr.getvalue()
    assert "correct the FEN and reload" in stderr.getvalue()
    assert stdout.getvalue().count("Turn: white") == 2
    assert session.view().revision == 1


def test_text_and_json_share_current_analysis_candidate() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    capture = Explanation(
        "capture", "line.capture",
        (("san", "Kxa2"), ("captured_color", "black"),
         ("captured_piece_type", "pawn"), ("material_delta_white", 1)),
    )
    mate = Explanation("mate", "candidate.allows_opponent_mate_in_one", (("reply_count", 1),))
    candidate = CandidateResult(
        "candidate:a1a2", view.position.position_id, "a1a2", "Ka2", "white", 1,
        EngineScore(0, None, None, ScoreBound.EXACT), ("a1a2",), False, ("capture", "mate"), (),
    )
    result = AnalysisResult(
        1, view.revision, AnalysisState.COMPLETED, (candidate,), (capture, mate),
        coverage=Coverage(1, 1, 1, False),
    )
    shared = dataclasses.replace(view, analysis=result)
    text = render_analysis(result, CATALOG)
    payload = json.loads(render_json(shared))
    assert "Ka2" in text and "+0.00" in text
    assert "After this move" in text
    assert "Fact: [Ka2]" not in text
    assert text.split("#  Rank", 1)[1].count("After this move") == 1
    assert payload["schema_version"] == 4
    assert payload["analysis"]["candidates"][0]["candidate_id"] == "candidate:a1a2"
    assert payload["analysis"]["candidates"][0]["score"]["centipawns"] == 0
    assert payload["analysis"]["candidates"][0]["score"]["mate"] is None
    assert payload["session"]["facts"]["legal_moves"][0]["san"]


def test_concise_analysis_prioritizes_engine_mate_within_three_facts() -> None:
    explanation = Explanation(
        "reported-mate", "engine.reported_mate", (("winner", "White"), ("moves", 2)),
    )
    candidate = CandidateResult(
        "candidate", PositionId(1, 1, ()), "a1a2", "Ka2", "white", 1,
        EngineScore(None, 2, "white", ScoreBound.EXACT), (), False, ("reported-mate",), (),
    )
    result = AnalysisResult(1, 1, AnalysisState.COMPLETED, (candidate,), (explanation,))

    compact = render_analysis(result, CATALOG)
    details = render_details(result, 1, CATALOG)

    assert "white mates in 2" in compact
    assert "Stockfish reports" not in compact
    assert "Stockfish reports White mates in 2 moves" in details


def test_candidate_mate_warning_outranks_repeated_engine_mate_narration_in_compact_output() -> None:
    position = PositionId(1, 1, ())
    candidates = tuple(
        CandidateResult(
            f"candidate-{index}", position, f"a1{square}", san, "white", index,
            EngineScore(None, 2 + index, "white", ScoreBound.EXACT), (), False,
            (("direct-warning", "reported-2", "reported-1")[index - 1],), (),
        )
        for index, (square, san) in enumerate((("a2", "Ka2"), ("b1", "Kb1"), ("b2", "Kb2")), 1)
    )
    explanations = (
        Explanation("reported-1", "engine.reported_mate", (("winner", "White"), ("moves", 3))),
        Explanation("reported-2", "engine.reported_mate", (("winner", "White"), ("moves", 4))),
        Explanation("direct-warning", "candidate.allows_opponent_mate_in_one", (("reply_count", 1),)),
    )

    compact = render_analysis(
        AnalysisResult(1, 1, AnalysisState.COMPLETED, candidates, explanations), CATALOG,
    )

    assert "Fact:" not in compact
    assert "Stockfish reports" not in compact
    assert "After this move, the opponent has 1 mate-in-one" in compact
    assert "white mates in 3" in compact and "white mates in 5" in compact


def _candidate_comparison(fen: str, roots: tuple[str, ...], sans: tuple[str, ...]):
    context = PositionContext(1, 1, (), fen, (), fen, False)
    structures = build_root_structures(context, 7, roots)
    return tuple(
        CandidateResult(
            f"candidate:{uci}", context.position_id, uci, san,
            "white" if chess.Board(fen).turn else "black", index,
            None, (), False, (), (), root_structure=structures[uci],
        )
        for index, (uci, san) in enumerate(zip(roots, sans), 1)
    )


def test_candidate_rows_lead_with_explicit_defense_contrasts_and_true_unchanged_state() -> None:
    fen = "4k3/8/8/3p4/4P3/8/1N6/R5K1 w - - 0 1"
    candidates = _candidate_comparison(fen, ("a1e1", "b2c4"), ("Re1", "Nc4"))

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.COMPLETED, candidates), CATALOG)

    re1 = next(line for line in output.splitlines() if "  Re1  " in line)
    nc4 = next(line for line in output.splitlines() if "  Nc4  " in line)
    assert "adds rook e1 as defender of pawn e4" in re1
    assert "rook e1 now defends pawn e4" not in re1
    assert "leaves pawn e4 defense unchanged" in nc4


def test_candidate_defense_comparison_mirrors_for_black() -> None:
    fen = chess.Board("4k3/8/8/3p4/4P3/8/1N6/R5K1 w - - 0 1").mirror().fen(en_passant="fen")
    candidates = _candidate_comparison(fen, ("a8e8", "b7c5"), ("Re8", "Nc5"))

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.COMPLETED, candidates), CATALOG)

    assert "adds rook e8 as defender of pawn e5" in output
    assert "leaves pawn e5 defense unchanged" in output


def test_equal_defender_counts_with_different_identities_render_as_replacement() -> None:
    candidates = _candidate_comparison(chess.STARTING_FEN, ("g1h3", "b1c3"), ("Nh3", "Nc3"))

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.COMPLETED, candidates), CATALOG)

    assert "replaces" in output
    replacement = next(line for line in output.splitlines() if "replaces" in line)
    assert "defense unchanged" not in replacement


def test_same_subject_pin_is_retained_when_unchanged_defense_has_no_overlapping_source() -> None:
    fen = "3bk3/4n3/8/8/8/8/4B3/3QR2K w - - 0 1"
    candidates = _candidate_comparison(fen, ("e2b5", "d1d8"), ("Bb5+", "Qxd8+"))

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.COMPLETED, candidates), CATALOG)
    bb5 = next(line for line in output.splitlines() if "  Bb5+  " in line)
    details = render_details(AnalysisResult(7, 1, AnalysisState.COMPLETED, candidates), 1, CATALOG)

    assert "leaves knight e7 defense unchanged" in bb5
    assert "knight e7 is pinned to king e8" not in bb5
    assert "knight e7 is pinned to king e8" in details
    assert "4 move consequence(s) omitted" in bb5
    summary = bb5.split("not available  ", 1)[1]
    substantive = [clause for clause in summary.split("; ") if not clause.endswith("omitted")]
    assert len(substantive) == 4


@pytest.mark.parametrize(
    ("fen", "roots", "sans", "move", "expected"),
    (
        (
            "7k/8/8/3p4/4P3/8/8/K7 w - - 0 1", ("e4d5",), ("exd5",),
            "exd5", "captures pawn on d5",
        ),
        (
            "4k3/P7/8/8/8/8/8/4K3 w - - 0 1", ("a7a8q",), ("a8=Q+",),
            "a8=Q+", "promotes to queen, gives check",
        ),
        (
            "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", ("e1g1",), ("O-O",),
            "O-O", "castles with rook h1→f1",
        ),
        (
            "4k3/8/8/8/8/8/4B3/4R2K w - - 0 1", ("e2c4",), ("Bc4+",),
            "Bc4+", "gives check",
        ),
    ),
)
def test_candidate_rows_keep_direct_root_effects_before_incidental_structure(
    fen, roots, sans, move, expected,
) -> None:
    candidate = _candidate_comparison(fen, roots, sans)[0]

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.COMPLETED, (candidate,)), CATALOG)
    row = next(line for line in output.splitlines() if f"  {move}  " in line)

    assert expected in row


def test_candidate_structure_precedes_later_pv_capture_and_capture_narration_stays_in_details() -> None:
    fen = "4k3/8/8/3p4/4P3/8/1N6/R5K1 w - - 0 1"
    candidate = dataclasses.replace(
        _candidate_comparison(fen, ("a1e1", "b2c4"), ("Re1", "Nc4"))[0],
        pv=("a1e1", "d5e4"), explanation_refs=("later-capture",),
    )
    capture = Explanation(
        "later-capture", "line.capture",
        (("san", "dxe4"), ("captured_color", "white"),
         ("captured_piece_type", "pawn"), ("material_delta_white", -1)),
    )
    result = AnalysisResult(7, 1, AnalysisState.COMPLETED, (candidate,), (capture,))

    compact = render_analysis(result, CATALOG)
    details = render_details(result, 1, CATALOG)

    assert "adds rook e1 as defender of pawn e4" in compact
    assert "dxe4 captures" not in compact
    assert "dxe4 captures white pawn" in details


def test_provisional_candidate_without_pv_still_renders_shared_root_structure() -> None:
    candidate = dataclasses.replace(
        _candidate_comparison(chess.STARTING_FEN, ("e2e3", "g1f3"), ("e3", "Nf3"))[0],
        provisional=True, pv=(),
    )

    output = render_analysis(AnalysisResult(7, 1, AnalysisState.RUNNING, (candidate,)), CATALOG)

    assert "structure unavailable" not in output
    assert "defense" in output


def test_candidate_compact_omissions_include_retained_items_and_details_show_all_retained_structure() -> None:
    candidate = _candidate_comparison(
        chess.STARTING_FEN, ("e2e3", "e2e4", "g1f3"), ("e3", "e4", "Nf3"),
    )[0]
    structure = candidate.root_structure
    assert structure is not None and len(structure.defense_changes) == 3

    result = AnalysisResult(7, 1, AnalysisState.COMPLETED, (candidate,))
    compact = render_analysis(result, CATALOG)
    details = render_details(result, 1, CATALOG)

    assert f"{structure.omitted_count + 1} defense contrast(s) omitted" in compact
    for change in structure.defense_changes:
        assert change.square.square in details
    assert "defense contrast(s) omitted" not in details or structure.omitted_count > 0


@pytest.mark.parametrize(
    ("mover", "san", "captured_color", "captured_type", "white_delta"),
    (
        ("white", "exd5", "black", "pawn", 1),
        ("black", "exd4", "white", "pawn", -1),
        ("white", "axb8=Q+", "black", "rook", 13),
        ("black", "hxg1=Q+", "white", "rook", -13),
    ),
)
def test_capture_summary_keeps_white_perspective_for_both_movers(
    mover, san, captured_color, captured_type, white_delta,
) -> None:
    explanation = Explanation(
        "capture", "line.capture",
        (("san", san), ("captured_color", captured_color),
         ("captured_piece_type", captured_type), ("material_delta_white", white_delta)),
    )
    candidate = CandidateResult(
        "candidate", PositionId(1, 1, ()), "a1a2", san, mover, 1,
        EngineScore(0, None, None, ScoreBound.EXACT), (), False, ("capture",), (),
    )
    result = AnalysisResult(1, 1, AnalysisState.COMPLETED, (candidate,), (explanation,))
    output = render_details(result, 1, CATALOG)
    assert f"Line: {san} captures {captured_color} {captured_type}" in output
    assert f"material Δ {white_delta:+d}" in output
    assert "(White)" not in output


@pytest.mark.parametrize(("centipawns", "rendered"), ((125, "+1.25"), (-125, "-1.25")))
def test_compact_scores_preserve_white_perspective_sign_without_repeating_the_convention(
    centipawns, rendered,
) -> None:
    candidate = CandidateResult(
        "candidate", PositionId(1, 1, ()), "a1a2", "Ka2", "white", 1,
        EngineScore(centipawns, None, None, ScoreBound.EXACT), (), False, (), (),
    )

    output = render_analysis(AnalysisResult(1, 1, AnalysisState.COMPLETED, (candidate,)), CATALOG)

    assert rendered in output
    assert "favors White" not in output
    assert "favors Black" not in output


def test_redirected_input_waits_for_latest_analysis_and_closes() -> None:
    async def exercise() -> tuple[str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        controller = AnalysisController(ImmediateEngine())
        commands = io.StringIO("fen 7k/8/8/8/8/8/8/R6K w - - 0 1\n")
        await run_cli(Session(), controller=controller, catalog=CATALOG, stdin=commands, stdout=stdout, stderr=stderr)
        return stdout.getvalue(), stderr.getvalue()

    stdout, stderr = asyncio.run(exercise())
    assert "Analysis: running" in stdout
    assert "Analysis: 1 root probe completed; depth 8" in stdout
    assert "Ra2" in stdout
    assert stderr == ""


@pytest.mark.parametrize(
    ("depths", "expected"),
    (
        ((12, 12), "Analysis: 2 root probes completed; depth 12"),
        ((8, 14), "Analysis: 2 root probes completed; depth range 8–14"),
        ((None, None), "Analysis: 2 root probes completed"),
        ((8, None), "Analysis: 2 root probes completed; known depth 8"),
    ),
)
def test_final_summary_counts_only_completed_root_evidence_and_reports_available_depths(
    depths, expected,
) -> None:
    evidence = (
        Evidence("survey", "engine_survey", engine_depth=20),
        *(Evidence(f"probe-{index}", "engine_line", engine_depth=depth) for index, depth in enumerate(depths)),
    )
    result = AnalysisResult(
        1, 1, AnalysisState.COMPLETED, evidence=evidence,
        coverage=Coverage(9, 2, 4, True, 20),
    )

    output = render_analysis(result, CATALOG)

    assert expected in output
    assert "Analysis: 3 root probes" not in output
    assert "depth 20" not in output
    assert "Coverage: surveyed 9; selected 4 of 20 legal moves; probed 2 (interrupted)" in output


def test_running_summary_is_a_single_acknowledgment_without_partial_probe_counts() -> None:
    result = AnalysisResult(
        1, 1, AnalysisState.RUNNING,
        evidence=(Evidence("partial", "engine_line", engine_depth=8),),
        coverage=Coverage(5, 1, 3, False, 20),
    )

    assert render_analysis(result, CATALOG) == "Analysis: running"


def test_compare_resolves_san_and_uci_without_moving_session() -> None:
    session = Session()
    before = session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    assert session.resolve_moves(("Ka2", "a1b1")) == ("a1a2", "a1b1")
    assert session.view().position == before.position


def test_over_32_piece_snapshot_keeps_static_facts_and_explains_unsupported_analysis() -> None:
    async def exercise():
        stdout = io.StringIO()
        engine = ImmediateEngine()
        controller = AnalysisController(engine)
        fen = "NNNNNNNk/NNNNN1NN/NNNNNN1N/NNNNNNNN/NN6/8/8/K7 w - - 0 1"
        await run_cli(
            Session(), controller=controller, catalog=CATALOG,
            stdin=io.StringIO(f"fen {fen}\njson\n"), stdout=stdout, stderr=io.StringIO(),
        )
        return stdout.getvalue(), engine.prepares

    output, prepares = asyncio.run(exercise())
    assert "engine analysis supports at most 32 occupied squares" in output
    assert '"pieces": [' in output
    assert prepares == 0


def test_unranked_candidate_remains_accessible_by_stable_display_number() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
    candidate = CandidateResult(
        "candidate:a1a2", view.position.position_id, "a1a2", "Ra2", "white", None,
        None, (), True, (), (),
    )
    result = AnalysisResult(3, view.revision, AnalysisState.RUNNING, (candidate,))
    output = render_details(result, 1, CATALOG)
    assert "Candidate 1: Ra2 (a1a2)" in output
    assert "Structure: unavailable" in output


def test_details_render_recapture_promotion_and_material_change() -> None:
    session = Session()
    view = session.load_fen("7k/P7/8/8/8/8/8/7K w - - 0 1")
    piece = PieceId(view.position.document_id, 1, "a7", "white", "pawn")
    captured = PieceId(view.position.document_id, 1, "a8", "black", "rook")
    consequence = LineConsequence(
        1, view.position.position_id, "a7a8q", "a8=Q+", piece,
        SquareRef(view.position.position_id, "a7"), SquareRef(view.position.position_id, "a8"),
        "white", "pawn", True, captured, SquareRef(view.position.position_id, "a8"),
        "black", "rook", True, "queen", 13,
    )
    evidence = Evidence(
        "e1", "engine_line", ("a7a8q",), ("a8=Q+",), consequences=(consequence,),
        engine_elapsed_seconds=0.25, score=EngineScore(100, None, None, ScoreBound.EXACT),
    )
    candidate = CandidateResult(
        "candidate:a7a8q", view.position.position_id, "a7a8q", "a8=Q+", "white", 1,
        EngineScore(100, None, None, ScoreBound.EXACT), ("a7a8q",), False, (), ("e1",),
    )
    result = AnalysisResult(1, view.revision, AnalysisState.COMPLETED, (candidate,), evidence=(evidence,))
    output = render_details(result, 1, CATALOG)
    assert "recapture" in output
    assert "promotes to queen" in output
    assert "material Δ +13" in output
    assert "(White)" not in output
    assert "gives check" in output
    assert "Probe score: +1.00" in output
    assert "Continuation: 1. a8=Q+" in output
    assert "elapsed=0.25s" in output


def test_details_explains_material_exposure_model_without_raw_schema_token() -> None:
    view = Session().load_fen("7k/8/8/3p4/8/8/4P3/4K3 w - - 0 1")
    pawn = next(piece for piece in view.pieces if piece.square == "e2")
    candidate = CandidateResult(
        "candidate:e2e4", view.position.position_id, "e2e4", "e4", "white", 1,
        None, ("e2e4",), False, (), (),
    )
    reference = EvidenceRef(EvidenceKind.REPLY_EXCHANGE, "e2e4", 0)
    exposure = MaterialExposure("e2e4", "d5e4", -1, reference)
    trapping = TrappingAssessment(
        view.position.position_id, pawn.piece_id, AssessmentConclusion.INCOMPLETE,
        ("e2e4",), (), ("e2e4",), (),
        AssessmentCoverage(CoverageUnit.LEGAL_EXITS, 1, 0, 0, 1),
        ("e2e4",), (exposure,),
    )
    result = AnalysisResult(
        1, view.revision, AnalysisState.COMPLETED, (candidate,),
        trapping=(trapping,), assessment_pieces=(pawn,),
    )
    output = render_details(result, 1, CATALOG)
    assert "root gains plus target-square exchanges" in output
    assert "root_gain_plus_target_square_material" not in output
    inspected = render_inspection(dataclasses.replace(view, analysis=result), "e2", CATALOG)
    detail_exposure = next(line for line in output.splitlines() if "root gains plus" in line)
    inspection_exposure = next(line for line in inspected.splitlines() if "root gains plus" in line)
    assert inspection_exposure == detail_exposure


def test_current_facts_include_mate_moves_checker_coordinates_and_failure_recovery() -> None:
    session = Session()
    view = session.load_fen("7k/8/8/8/8/8/8/K7 w - - 0 1")
    mate_evidence = Evidence("mates", "legal_mate_in_one", alternative_san_lines=(("Qg7#",), ("Qf8#",)))
    mate = Explanation("mate", "position.mate_in_one", evidence_refs=("mates",))
    check = Explanation(
        "check", "position.in_check", squares=(SquareRef(view.position.position_id, "f7"),),
    )
    completed = AnalysisResult(
        1, view.revision, AnalysisState.COMPLETED, explanations=(mate, check), evidence=(mate_evidence,),
    )
    output = render_analysis(completed, CATALOG)
    assert "Moves: Qg7#, Qf8#." in output
    assert "Checkers: f7." in output

    failed = AnalysisResult(2, view.revision, AnalysisState.FAILED, message="file not found")
    failure = render_analysis(failed, CATALOG)
    assert "--engine executable path" in failure
    assert "run analyze to retry" in failure
    assert "Board navigation remains available" in failure


def test_awaited_cancel_cannot_cancel_the_next_position_request() -> None:
    class CancelEngine(ImmediateEngine):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.cancels = 0

        async def analyze(self, position, policy, *, progress=None):
            await self.release.wait()
            return await super().analyze(position, policy, progress=progress)

        async def cancel(self):
            self.cancels += 1
            self.release.set()

    async def exercise():
        session = Session()
        engine = CancelEngine()
        controller = AnalysisController(engine)
        await execute_async(
            session, "fen 7k/8/8/8/8/8/8/R6K w - - 0 1",
            controller=controller, catalog=CATALOG,
        )
        await asyncio.sleep(0)
        await execute_async(session, "cancel", controller=controller, catalog=CATALOG)
        await execute_async(
            session, "fen 7k/8/8/8/8/8/8/R6K w - - 0 1",
            controller=controller, catalog=CATALOG,
        )
        result = await controller.wait()
        assert result is not None
        assert result.revision == session.view().revision
        assert result.state is AnalysisState.COMPLETED
        assert engine.cancels >= 1
        await controller.close()

    asyncio.run(exercise())


def test_progress_output_preserves_partially_typed_interactive_command() -> None:
    class ProgressEngine(ImmediateEngine):
        async def analyze(self, position, policy, *, progress=None):
            candidate = EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), ("a1a2",), 8, 12, 0.01)
            if progress is not None:
                progress(EngineProgress((candidate,), 0.1))
            await asyncio.sleep(0.35)
            return EngineReport(EngineStatus.COMPLETED, (candidate,))

    async def exercise() -> tuple[str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with create_pipe_input() as pipe:
            async def type_commands() -> None:
                pipe.send_text("fen 7k/8/8/8/8/8/8/R6K w - - 0 1\nbo")
                await asyncio.sleep(0.4)
                pipe.send_text("ard\n")
                await asyncio.sleep(0.5)
                pipe.send_text("quit\n")

            writer = asyncio.create_task(type_commands())
            await run_cli(
                Session(), controller=AnalysisController(ProgressEngine()), catalog=CATALOG,
                stdout=stdout, stderr=stderr, prompt_input=pipe, prompt_output=DummyOutput(),
            )
            await writer
        return stdout.getvalue(), stderr.getvalue()

    stdout, stderr = asyncio.run(exercise())
    assert stdout.count("Turn: white") >= 2
    assert stdout.count("Analysis: running") >= 1
    assert "Coverage: surveyed 0; selected 0" not in stdout
    assert "Analysis: 1 root probe completed; depth 8" in stdout
    assert stderr == ""


def test_native_process_reconfigures_cp1252_standard_streams_to_utf8() -> None:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    commands = (
        "fen 7k/8/8/8/8/8/8/K7 w - - 0 1\n"
        "move Ka2\n"
        "quit\n"
    ).encode("utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "namichess", "--engine", "missing-stockfish.exe"],
        input=commands,
        capture_output=True,
        cwd=Path(__file__).parents[2],
        env=environment,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    output = completed.stdout.decode("utf-8")
    assert "Ka2: king a1→a2" in output
