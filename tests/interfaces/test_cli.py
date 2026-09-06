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
from namichess.application.imports import ImportError as ChessImportError
from namichess.analysis.engine import EngineCandidate, EngineProgress, EngineReport, EngineScore, EngineStatus, ScoreBound
from namichess.analysis.evidence import Evidence, Explanation, LineConsequence
from namichess.analysis.assessments import (
    AssessmentConclusion, AssessmentCoverage, CoverageUnit, EvidenceKind,
    EvidenceRef, MaterialExposure, TrappingAssessment,
)
from namichess.application.analysis import AnalysisController, AnalysisResult, AnalysisState, CandidateResult, Coverage
from namichess.domain.models import PieceId, SquareRef
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.interfaces.orientation import BoardDisplayState, Orientation, ResolvedOrientation
from namichess.interfaces.settings import SettingsStore
from namichess.interfaces.cli import execute, execute_async, render_analysis, render_details, render_json, run_cli


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
    assert "Changed: Ka2 — white king a1→a2" in output
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
    capture = Explanation("capture", "line.capture", (("san", "Kxa2"), ("material_delta_white", 1)))
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
    assert "Fact: [Ka2] After this candidate" in text
    assert text.split("#  Rank", 1)[1].count("After this candidate") == 1
    assert payload["schema_version"] == 2
    assert payload["analysis"]["candidates"][0]["candidate_id"] == "candidate:a1a2"
    assert payload["analysis"]["candidates"][0]["score"]["centipawns"] == 0
    assert payload["analysis"]["candidates"][0]["score"]["mate"] is None
    assert payload["session"]["facts"]["legal_moves"][0]["san"]


def test_concise_analysis_prioritizes_engine_mate_within_three_facts() -> None:
    explanations = tuple(
        Explanation(f"ordinary-{index}", "line.check", (("san", f"K{index}"),))
        for index in range(4)
    ) + (Explanation("zzz-mate", "engine.reported_mate", (("winner", "White"), ("moves", 2))),)
    output = render_analysis(
        AnalysisResult(1, 1, AnalysisState.COMPLETED, explanations=explanations), CATALOG,
    )
    assert output.count("Fact:") == 3
    assert "Stockfish reports that White mates in 2 moves" in output


def test_redirected_input_waits_for_latest_analysis_and_closes() -> None:
    async def exercise() -> tuple[str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        controller = AnalysisController(ImmediateEngine())
        commands = io.StringIO("fen 7k/8/8/8/8/8/8/R6K w - - 0 1\n")
        await run_cli(Session(), controller=controller, catalog=CATALOG, stdin=commands, stdout=stdout, stderr=stderr)
        return stdout.getvalue(), stderr.getvalue()

    stdout, stderr = asyncio.run(exercise())
    assert "Analysis: running" in stdout
    assert "Analysis: completed" in stdout
    assert "Ra2" in stdout
    assert stderr == ""


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
    assert "Candidate 1: Ra2 (a1a2)" in render_details(result, 1, CATALOG)


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
    assert "White material change +13" in output
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
    assert 1 <= stderr.count("Analysis progress:") <= 4


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
    assert "Changed: Ka2 — white king a1→a2" in output
