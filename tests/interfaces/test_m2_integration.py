from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import chess
import pytest

from namichess.analysis.engine import EngineCandidate, EngineReport, EngineScore, EngineStatus, ScoreBound
from namichess.analysis.local import LocalLimits
from namichess.application.analysis import AnalysisController, AnalysisPolicy, AnalysisState
from namichess.application.imports import ImportError as ChessImportError
from namichess.application.preview import preview_candidate_line
from namichess.application.session import Session
from namichess.domain.position import replay_position
from namichess.interfaces.cli import execute, execute_async, render_json
from namichess.interfaces.orientation import BoardDisplayState, ResolvedOrientation
from namichess.interfaces.settings import SettingsStore


PGN = '''[Event "Unicode integration"]
[Result "*"]

1. e4 (1. d4 d5) e5 2. Nf3 *

[Event "Capture promotion"]
[SetUp "1"]
[FEN "r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1"]
[Result "*"]

1. bxa8=Q+ *
'''


class TrackingEngine:
    """Cooperative fake used to observe controller bounds through real commands."""

    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.cancel_count = 0
        self.closed = False

    async def prepare(self) -> str:
        return "bounded-fake"

    async def analyze(self, context, policy, *, progress=None) -> EngineReport:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            if self.fail_once:
                self.fail_once = False
                return EngineReport(EngineStatus.FAILED, message="injected engine failure")
            board, _ = replay_position(context)
            requested = policy.root_moves or tuple(move.uci() for move in list(board.legal_moves)[:2])
            candidates = tuple(
                EngineCandidate(
                    EngineScore(12 - index, None, None, ScoreBound.EXACT),
                    (uci,), 4, 8, 0.001,
                )
                for index, uci in enumerate(requested)
            )
            return EngineReport(EngineStatus.COMPLETED, candidates, engine_name="bounded-fake")
        finally:
            self.active -= 1

    async def cancel(self) -> None:
        self.cancel_count += 1
        await asyncio.sleep(0)

    async def close(self) -> None:
        self.closed = True


def _controller(engine: TrackingEngine) -> AnalysisController:
    limits = LocalLimits(seconds=0, max_depth=1, node_limit=1)
    return AnalysisController(
        engine,
        policy=AnalysisPolicy(
            seconds=0.05,
            survey_seconds=0.01,
            candidate_limit=2,
            comparison_limit=2,
            total_candidate_limit=2,
            local=limits,
            focused_seconds=0.05,
            focused_local=limits,
        ),
    )


def test_unicode_multigame_workflow_preserves_source_and_canonical_shared_state(tmp_path: Path) -> None:
    async def exercise() -> None:
        source = tmp_path / "棋局 多游戏.pgn"
        source.write_text(PGN, encoding="utf-8")
        digest = hashlib.sha256(source.read_bytes()).digest()
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('{"version":1,"orientation":"invalid"}\n', encoding="utf-8")
        settings_bytes = settings_path.read_bytes()
        settings = SettingsStore(settings_path)
        display = BoardDisplayState()
        engine = TrackingEngine()
        controller = _controller(engine)
        session = Session()
        try:
            output, _ = await execute_async(
                session, f'load --orientation turn "{source}"', controller=controller,
                display_state=display, settings_store=settings,
            )
            assert "Orientation: black" in output
            assert session.view().selected_game == 1 and session.view().selected_ply == 3
            assert hashlib.sha256(source.read_bytes()).digest() == digest
            orientation, _ = await execute_async(
                session, "orientation", controller=controller,
                display_state=display, settings_store=settings,
            )
            assert "default fallback: white" in orientation and "must be white, black, or turn" in orientation
            assert settings_path.read_bytes() == settings_bytes

            await execute_async(session, "start", controller=controller, display_state=display)
            variations, _ = await execute_async(session, "variations", controller=controller, display_state=display)
            assert variations.splitlines() == ["1: e4", "2: d4"]
            await execute_async(session, "variation 2", controller=controller, display_state=display)
            inspected, _ = await execute_async(session, "inspect d4", controller=controller, display_state=display)
            changes, _ = await execute_async(session, "changes", controller=controller, display_state=display)
            assert "white pawn" in inspected and "d2→d4" in changes

            before_flip = render_json(session.analysis_view(controller))
            revision = session.view().revision
            await execute_async(session, "flip", controller=controller, display_state=display)
            assert display.orientation is ResolvedOrientation.WHITE
            assert session.view().revision == revision
            assert render_json(session.analysis_view(controller)) == before_flip

            await execute_async(session, "game 2", controller=controller, display_state=display)
            await execute_async(session, "back", controller=controller, display_state=display)
            root = session.view()
            await execute_async(session, "move bxa8=N", controller=controller, display_state=display)
            assert session.view().previous_move is not None
            assert session.view().previous_move.promoted
            assert next(piece for piece in session.view().pieces if piece.square == "a8").piece_type == "knight"
            await execute_async(session, "back", controller=controller, display_state=display)
            assert session.view().position == root.position

            await execute_async(session, "compare bxa8=Q+ bxa8=N", controller=controller, display_state=display)
            compared = await controller.wait()
            assert compared is not None and compared.state is AnalysisState.COMPLETED
            shared = session.analysis_view(controller)
            snapshot_before = render_json(shared)
            scores_before = tuple(candidate.score for candidate in compared.candidates)
            queen_number = next(
                index for index, candidate in enumerate(compared.candidates, 1)
                if candidate.uci == "b7a8q"
            )
            for ply in (0, 1):
                preview = preview_candidate_line(shared, queen_number, ply)
                assert preview.source_position_id == shared.position.position_id
                assert preview.revision == shared.revision
                assert preview.candidate.uci == "b7a8q"
            assert render_json(session.analysis_view(controller)) == snapshot_before
            assert session.view().position == root.position
            await execute_async(session, "flip", controller=controller, display_state=display)
            assert tuple(candidate.score for candidate in controller.latest.candidates) == scores_before  # type: ignore[union-attr]
            assert render_json(session.analysis_view(controller)) == snapshot_before

            await execute_async(session, "probe move bxa8=Q+", controller=controller, display_state=display)
            assert (await controller.wait()).subject.move == "b7a8q"  # type: ignore[union-attr]
            await execute_async(session, "probe piece b7", controller=controller, display_state=display)
            piece_probe = await controller.wait()
            assert piece_probe is not None and piece_probe.subject is not None
            assert piece_probe.subject.piece == next(piece.piece_id for piece in root.pieces if piece.square == "b7")
            assert hashlib.sha256(source.read_bytes()).digest() == digest
        finally:
            await controller.close()
        assert engine.closed and engine.active == 0

    asyncio.run(exercise())


def test_fifty_rapid_command_replacements_retain_only_current_bounded_work() -> None:
    async def exercise() -> None:
        engine = TrackingEngine()
        controller = _controller(engine)
        session = Session()
        session.load_fen(chess.STARTING_FEN)
        max_pending = 0
        for index in range(50):
            board, _ = replay_position(session.view().position)
            command = f"probe move {next(iter(board.legal_moves)).uci()}" if index % 2 == 0 else "analyze"
            await execute_async(session, command, controller=controller)
            max_pending = max(max_pending, int(controller._pending is not None))
            if index % 5 == 4:
                await execute_async(session, "move Nf3" if session.view().selected_ply == 0 else "back", controller=controller)
        result = await asyncio.wait_for(controller.wait(), 2)
        assert result is not None and result.request_id == 60
        assert result.revision == session.view().revision
        assert session.analysis_view(controller).analysis == result
        assert len(result.candidates) <= 2
        assert result.local is not None and result.local.nodes <= 1
        assert engine.max_active == 1 and max_pending == 1
        assert controller._pending is None and controller._active_run is None
        assert controller._worker is None
        await controller.close()
        assert engine.active == 0 and engine.closed
        assert controller._pending is None and controller._active_run is None and controller._worker is None

    asyncio.run(exercise())


def test_engine_failure_retry_invalid_import_and_above_capacity_are_truthful(tmp_path: Path) -> None:
    async def exercise() -> None:
        source = tmp_path / "unchanged.pgn"
        source.write_text("1. e4 *\n", encoding="utf-8")
        digest = hashlib.sha256(source.read_bytes()).digest()
        session = Session()
        session.load_pgn(source.read_text(encoding="utf-8"))
        preserved = session.view()
        with pytest.raises(ChessImportError):
            execute(session, "fen invalid")
        assert session.view().position == preserved.position

        engine = TrackingEngine(fail_once=True)
        controller = _controller(engine)
        try:
            session.start()
            session.request_analysis(controller)
            failed = await controller.wait()
            assert failed is not None and failed.state is AnalysisState.FAILED
            assert failed.message == "injected engine failure"
            session.request_analysis(controller)
            assert (await controller.wait()).state is AnalysisState.COMPLETED  # type: ignore[union-attr]

            over = Session()
            over.load_fen("NNNNNNNk/NNNNN1NN/NNNNNN1N/NNNNNNNN/NN6/8/8/K7 w - - 0 1")
            over.request_analysis(controller)
            unsupported = await controller.wait()
            assert unsupported is not None and unsupported.state is AnalysisState.UNSUPPORTED
            assert unsupported.message is not None and "32" in unsupported.message
        finally:
            await controller.close()
        assert hashlib.sha256(source.read_bytes()).digest() == digest

    asyncio.run(exercise())
