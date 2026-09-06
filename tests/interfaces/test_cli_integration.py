from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import chess
import pytest

from namichess.analysis.engine import StockfishAdapter
from namichess.application.analysis import AnalysisController, AnalysisPolicy, AnalysisState
from namichess.application.imports import ImportError as ChessImportError
from namichess.application.session import Session, SessionError
from namichess.interfaces.cli import execute_async
from namichess.interfaces.explanations import ExplanationCatalog


ENGINE = os.environ.get("NAMICHESS_TEST_ENGINE")
CATALOG = ExplanationCatalog.load(Path(__file__).parents[2] / "namichess" / "content" / "explanations.json")


@pytest.mark.skipif(not ENGINE, reason="set NAMICHESS_TEST_ENGINE for the real CLI integration gate")
def test_real_cli_session_keeps_state_evidence_and_engine_lifecycle_coherent(tmp_path: Path) -> None:
    async def exercise() -> None:
        source = tmp_path / "分析 sample game.pgn"
        source.write_text('[Event "国际"]\n[Result "*"]\n\n1. e4 (1. d4 d5) e5 2. Nf3 *\n', encoding="utf-8")
        invalid = tmp_path / "invalid game.pgn"
        invalid.write_text("1. e4", encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).digest()

        loop = asyncio.get_running_loop()
        loop_errors: list[dict[str, object]] = []
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        adapter = StockfishAdapter(ENGINE)
        controller = AnalysisController(adapter, policy=AnalysisPolicy(seconds=0.45, survey_seconds=0.12))
        session = Session()
        try:
            await execute_async(session, f'load "{source}"', controller=controller, catalog=CATALOG)
            await execute_async(session, "start", controller=controller, catalog=CATALOG)
            variations, _ = await execute_async(session, "variations", controller=controller, catalog=CATALOG)
            assert "1: e4" in variations and "2: d4" in variations
            await execute_async(session, "next", controller=controller, catalog=CATALOG)
            await execute_async(session, "move e5", controller=controller, catalog=CATALOG)
            await execute_async(session, "back", controller=controller, catalog=CATALOG)
            inspected, _ = await execute_async(session, "inspect e4", controller=controller, catalog=CATALOG)
            assert "white pawn" in inspected

            preserved = session.view()
            with pytest.raises(ChessImportError):
                await execute_async(session, "fen invalid", controller=controller, catalog=CATALOG)
            with pytest.raises(ChessImportError):
                await execute_async(session, f'load "{invalid}"', controller=controller, catalog=CATALOG)
            assert session.view().revision == preserved.revision
            assert session.view().position.current_fen == preserved.position.current_fen
            assert hashlib.sha256(source.read_bytes()).digest() == source_hash

            await execute_async(session, "start", controller=controller, catalog=CATALOG)
            await execute_async(session, "compare e4 d4", controller=controller, catalog=CATALOG)
            compared = await controller.wait()
            assert compared is not None and compared.state is AnalysisState.COMPLETED
            assert compared.revision == session.view().revision
            assert {item.uci for item in compared.candidates} >= {"e2e4", "d2d4"}
            payload_text, _ = await execute_async(session, "json", controller=controller, catalog=CATALOG)
            payload = json.loads(payload_text)
            assert payload["analysis"]["revision"] == session.view().revision
            assert payload["analysis"]["state"] == "completed"
            assert payload["analysis"]["evidence"]

            await execute_async(session, "analyze", controller=controller, catalog=CATALOG)
            await asyncio.sleep(0.01)
            await execute_async(session, "cancel", controller=controller, catalog=CATALOG)
            await execute_async(session, "analyze", controller=controller, catalog=CATALOG)
            recovered = await controller.wait()
            assert recovered is not None and recovered.state is AnalysisState.COMPLETED

            queens = "6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1"
            for fen in (queens, chess.Board(queens).mirror().fen(en_passant="fen")):
                await execute_async(session, f"fen {fen}", controller=controller, catalog=CATALOG)
                result = await controller.wait()
                assert result is not None and result.state is AnalysisState.COMPLETED
                assert result.revision == session.view().revision and result.candidates
            await asyncio.sleep(0.05)
            assert not any("InvalidStateError" in repr(item) for item in loop_errors)
            assert loop_errors == []
        finally:
            await controller.close()
            loop.set_exception_handler(old_handler)
        assert adapter._active_task is None
        assert adapter._protocol is None and adapter._transport is None

        unsupported_adapter = StockfishAdapter(ENGINE)
        unsupported = AnalysisController(unsupported_adapter, policy=AnalysisPolicy(seconds=0.1, survey_seconds=0.05))
        try:
            over_capacity = "NNNNNNNk/NNNNN1NN/NNNNNN1N/NNNNNNNN/NN6/8/8/K7 w - - 0 1"
            over_session = Session()
            await execute_async(over_session, f"fen {over_capacity}", controller=unsupported, catalog=CATALOG)
            result = await unsupported.wait()
            assert result is not None and result.state is AnalysisState.UNSUPPORTED
            assert unsupported_adapter._protocol is None and unsupported_adapter._transport is None
        finally:
            await unsupported.close()

    asyncio.run(exercise())
