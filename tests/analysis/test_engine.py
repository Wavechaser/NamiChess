from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os

import chess
import chess.engine
import pytest

from namichess.analysis.engine import (
    EnginePolicy,
    EngineStatus,
    ScoreBound,
    StockfishAdapter,
)
from namichess.domain.models import PositionContext


def context_for(board: chess.Board) -> PositionContext:
    root = board.root()
    return PositionContext(
        document_id=1,
        game_number=1,
        node_path=(),
        starting_fen=root.fen(en_passant="fen"),
        moves=tuple(move.uci() for move in board.move_stack),
        current_fen=board.fen(en_passant="fen"),
        has_history=bool(board.move_stack),
    )


class FakeTransport:
    def __init__(self) -> None:
        self.terminated = False
        self.on_terminate: object | None = None

    def terminate(self) -> None:
        self.terminated = True
        if self.on_terminate is not None:
            self.on_terminate()


class FakeAnalysis:
    def __init__(self, infos: list[dict[str, object]], *, wait_for_stop: bool = False) -> None:
        self._infos = iter(infos)
        self._wait_for_stop = wait_for_stop
        self._stopped = asyncio.Event()
        self.multipv = infos

    def stop(self) -> None:
        self._stopped.set()

    def __aiter__(self) -> FakeAnalysis:
        return self

    async def __anext__(self) -> dict[str, object]:
        if self._wait_for_stop:
            await self._stopped.wait()
            raise StopAsyncIteration
        try:
            return next(self._infos)
        except StopIteration:
            raise StopAsyncIteration from None


class StalledAnalysis(FakeAnalysis):
    def __init__(self) -> None:
        super().__init__([])
        self._never = asyncio.Event()

    def stop(self) -> None:
        pass

    async def __anext__(self) -> dict[str, object]:
        await self._never.wait()
        raise StopAsyncIteration


class CrashingAnalysis(FakeAnalysis):
    async def __anext__(self) -> dict[str, object]:
        raise chess.engine.EngineTerminatedError("fake engine crashed")


class ProgressThenStops(FakeAnalysis):
    def __init__(self, info: dict[str, object]) -> None:
        super().__init__([info])
        self._sent = False

    async def __anext__(self) -> dict[str, object]:
        if not self._sent:
            self._sent = True
            return self.multipv[0]
        await self._stopped.wait()
        raise StopAsyncIteration


class ProgressThenStalls(ProgressThenStops):
    def stop(self) -> None:
        pass


@dataclass
class FakeProtocol:
    analysis_factory: object
    id: dict[str, str] = field(default_factory=lambda: {"name": "fakefish"})
    configured: list[dict[str, int]] = field(default_factory=list)
    boards: list[chess.Board] = field(default_factory=list)
    root_moves: list[tuple[chess.Move, ...] | None] = field(default_factory=list)
    quit_called: bool = False

    def __post_init__(self) -> None:
        self.returncode: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def configure(self, options: dict[str, int]) -> None:
        self.configured.append(options)

    async def analysis(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int,
        game: object,
        root_moves: tuple[chess.Move, ...] | None,
    ) -> FakeAnalysis:
        self.boards.append(board.copy(stack=True))
        self.root_moves.append(root_moves)
        return self.analysis_factory(board)

    async def quit(self) -> None:
        self.quit_called = True
        if not self.returncode.done():
            self.returncode.set_result(0)


async def adapter_with(protocol: FakeProtocol, transport: FakeTransport) -> StockfishAdapter:
    async def opener(command: object) -> tuple[FakeTransport, FakeProtocol]:
        return transport, protocol

    return StockfishAdapter("fakefish", opener=opener)  # type: ignore[arg-type]


def test_reuses_configured_engine_and_preserves_history_and_scores() -> None:
    async def exercise() -> None:
        board = chess.Board()
        board.push_uci("e2e4")

        def complete(current: chess.Board) -> FakeAnalysis:
            move = next(iter(current.legal_moves))
            info: dict[str, object] = {
                "score": chess.engine.PovScore(chess.engine.Cp(37), chess.BLACK),
                "pv": [move],
                "depth": 12,
                "nodes": 123,
                "time": 0.1,
                "lowerbound": True,
            }
            return FakeAnalysis([info])

        protocol = FakeProtocol(complete)
        transport = FakeTransport()
        adapter = await adapter_with(protocol, transport)

        assert await adapter.prepare() == "fakefish"
        first = await adapter.analyze(context_for(board), EnginePolicy(0.1))
        second = await adapter.analyze(context_for(board), EnginePolicy(0.1))

        assert first.status is EngineStatus.COMPLETED
        assert second.status is EngineStatus.COMPLETED
        assert first.candidates[0].score.centipawns == -37
        assert first.candidates[0].score.bound is ScoreBound.UPPER
        assert tuple(move.uci() for move in protocol.boards[0].move_stack) == ("e2e4",)
        assert protocol.configured == [{"Threads": 1, "Hash": 64}]
        await adapter.close()
        assert protocol.quit_called

    asyncio.run(exercise())


def test_over_capacity_position_is_unsupported_without_launching_engine() -> None:
    async def exercise() -> None:
        calls = 0

        async def opener(command: object) -> object:
            nonlocal calls
            calls += 1
            raise AssertionError("engine must not launch")

        adapter = StockfishAdapter("fakefish", opener=opener)  # type: ignore[arg-type]
        board = chess.Board("qqqqqqq1/qqqqqqqq/qqqqqqqq/qqqqqqqq/8/8/8/K6k w - - 0 1")
        report = await adapter.analyze(context_for(board), EnginePolicy(0.1))

        assert report.status is EngineStatus.UNSUPPORTED
        assert calls == 0

    asyncio.run(exercise())


def test_illegal_engine_principal_variation_fails_evidence() -> None:
    async def exercise() -> None:
        board = chess.Board()

        def malformed(_: chess.Board) -> FakeAnalysis:
            return FakeAnalysis(
                [{
                    "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                    "pv": [chess.Move.from_uci("a1a8")],
                }]
            )

        protocol = FakeProtocol(malformed)
        adapter = await adapter_with(protocol, FakeTransport())
        report = await adapter.analyze(context_for(board), EnginePolicy(0.1))

        assert report.status is EngineStatus.FAILED
        assert "principal variation" in (report.message or "")
        await adapter.close()

    asyncio.run(exercise())


def test_mate_given_keeps_its_winner_when_zero_distance_loses_sign() -> None:
    async def exercise() -> None:
        board = chess.Board()

        def mate_given(current: chess.Board) -> FakeAnalysis:
            return FakeAnalysis(
                [{
                    "score": chess.engine.PovScore(chess.engine.MateGiven, chess.BLACK),
                    "pv": [next(iter(current.legal_moves))],
                }]
            )

        protocol = FakeProtocol(mate_given)
        adapter = await adapter_with(protocol, FakeTransport())
        report = await adapter.analyze(context_for(board), EnginePolicy(0.1))

        assert report.candidates[0].score.mate == 0
        assert report.candidates[0].score.mate_winner == "black"
        await adapter.close()

    asyncio.run(exercise())


def test_cancel_stops_active_search_without_terminating_responsive_child() -> None:
    async def exercise() -> None:
        board = chess.Board()
        started = asyncio.Event()
        active: list[FakeAnalysis] = []

        def pending(_: chess.Board) -> FakeAnalysis:
            started.set()
            analysis = FakeAnalysis([], wait_for_stop=True)
            active.append(analysis)
            return analysis

        protocol = FakeProtocol(pending)
        transport = FakeTransport()
        adapter = await adapter_with(protocol, transport)
        task = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await started.wait()

        await adapter.cancel()

        assert (await task).status is EngineStatus.CANCELED
        assert not transport.terminated
        await adapter.close()

    asyncio.run(exercise())


def test_direct_task_cancellation_stops_and_drains_the_active_search() -> None:
    async def exercise() -> None:
        board = chess.Board()
        started = asyncio.Event()
        active: list[FakeAnalysis] = []

        def pending(_: chess.Board) -> FakeAnalysis:
            started.set()
            analysis = FakeAnalysis([], wait_for_stop=True)
            active.append(analysis)
            return analysis

        protocol = FakeProtocol(pending)
        adapter = await adapter_with(protocol, FakeTransport())
        task = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await started.wait()

        task.cancel()

        assert (await task).status is EngineStatus.CANCELED
        assert active[0]._stopped.is_set()
        assert adapter._active_task is None
        await adapter.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), float("-inf")])
def test_engine_policy_rejects_nonfinite_search_budgets(seconds: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        EnginePolicy(seconds)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_adapter_rejects_nonfinite_timeouts(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        StockfishAdapter("fakefish", startup_timeout_seconds=timeout)
    with pytest.raises(ValueError, match="finite"):
        StockfishAdapter("fakefish", stop_grace_seconds=timeout)


def test_startup_failure_and_timeout_report_failure_without_an_active_process() -> None:
    async def exercise() -> None:
        board = chess.Board()

        async def fails(command: object) -> object:
            raise OSError("missing engine")

        failed = StockfishAdapter("missing", opener=fails)  # type: ignore[arg-type]
        assert (await failed.analyze(context_for(board), EnginePolicy(0.1))).status is EngineStatus.FAILED

        async def stalls(command: object) -> object:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        timed_out = StockfishAdapter(
            "slow", opener=stalls, startup_timeout_seconds=0.01
        )  # type: ignore[arg-type]
        assert (await timed_out.analyze(context_for(board), EnginePolicy(0.1))).status is EngineStatus.FAILED

    asyncio.run(exercise())


def test_cancel_during_startup_covers_the_entire_request() -> None:
    async def exercise() -> None:
        board = chess.Board()
        started = asyncio.Event()

        async def opener(command: object) -> object:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        adapter = StockfishAdapter("slow", opener=opener)  # type: ignore[arg-type]
        task = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await started.wait()
        await adapter.cancel()

        assert (await task).status is EngineStatus.CANCELED

    asyncio.run(exercise())


def test_cancel_during_analysis_ready_handshake_does_not_cancel_protocol_future() -> None:
    async def exercise() -> None:
        board = chess.Board()
        entered = asyncio.Event()
        release = asyncio.Event()

        def complete(current: chess.Board) -> FakeAnalysis:
            move = next(iter(current.legal_moves))
            return FakeAnalysis([{
                "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
                "pv": [move],
            }])

        protocol = FakeProtocol(complete)
        original_analysis = protocol.analysis

        async def delayed_analysis(*args: object, **kwargs: object) -> FakeAnalysis:
            entered.set()
            await release.wait()
            return await original_analysis(*args, **kwargs)  # type: ignore[arg-type]

        protocol.analysis = delayed_analysis  # type: ignore[method-assign]
        adapter = await adapter_with(protocol, FakeTransport())
        task = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await entered.wait()
        canceling = asyncio.create_task(adapter.cancel())
        await asyncio.sleep(0)
        assert not task.cancelled()
        release.set()
        await canceling
        assert (await task).status is EngineStatus.CANCELED
        assert adapter._active_task is None

    asyncio.run(exercise())


def test_finish_during_analysis_ready_handshake_stops_and_returns_evidence() -> None:
    async def exercise() -> None:
        board = chess.Board()
        entered = asyncio.Event()
        release = asyncio.Event()
        move = next(iter(board.legal_moves))
        info = {"score": chess.engine.PovScore(chess.engine.Cp(12), chess.WHITE), "pv": [move], "time": 0.07}
        protocol = FakeProtocol(lambda _: ProgressThenStops(info))
        original_analysis = protocol.analysis

        async def delayed_analysis(*args: object, **kwargs: object) -> FakeAnalysis:
            entered.set()
            await release.wait()
            return await original_analysis(*args, **kwargs)  # type: ignore[arg-type]

        protocol.analysis = delayed_analysis  # type: ignore[method-assign]
        adapter = await adapter_with(protocol, FakeTransport())
        analyzing = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await entered.wait()
        finishing = asyncio.create_task(adapter.finish())
        await asyncio.sleep(0)
        assert not finishing.done()
        release.set()
        report = await finishing
        assert report is not None and report.status is EngineStatus.COMPLETED
        assert report.candidates[0].elapsed_seconds == 0.07
        assert await analyzing == report

    asyncio.run(exercise())


def test_finish_stop_timeout_is_failed_even_when_analysis_settles_as_canceled() -> None:
    async def exercise() -> None:
        board = chess.Board()
        protocol = FakeProtocol(lambda _: StalledAnalysis())
        transport = FakeTransport()
        transport.on_terminate = lambda: (
            None if protocol.returncode.done() else protocol.returncode.set_result(1)
        )
        adapter = StockfishAdapter("fakefish", opener=lambda _: _opened(transport, protocol), stop_grace_seconds=0.01)  # type: ignore[arg-type]
        analyzing = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        while adapter._active is None:
            await asyncio.sleep(0)
        report = await adapter.finish()
        assert report is not None and report.status is EngineStatus.FAILED
        assert report.message == "engine did not stop within the grace period"
        assert (await analyzing).status is EngineStatus.CANCELED

    async def _opened(transport: FakeTransport, protocol: FakeProtocol):
        return transport, protocol

    asyncio.run(exercise())


def test_later_exact_score_clears_an_earlier_bound_snapshot() -> None:
    async def exercise() -> None:
        board = chess.Board()
        move = next(iter(board.legal_moves))
        bound = {
            "multipv": 1,
            "score": chess.engine.PovScore(chess.engine.Cp(15), chess.WHITE),
            "pv": [move],
            "lowerbound": True,
        }
        exact = {
            "multipv": 1,
            "score": chess.engine.PovScore(chess.engine.Cp(22), chess.WHITE),
            "pv": [move],
        }
        adapter = await adapter_with(FakeProtocol(lambda _: FakeAnalysis([bound, exact])), FakeTransport())
        report = await adapter.analyze(context_for(board), EnginePolicy(0.1))
        assert report.status is EngineStatus.COMPLETED
        assert report.candidates[0].score.centipawns == 22
        assert report.candidates[0].score.bound is ScoreBound.EXACT

    asyncio.run(exercise())


def test_metadata_only_updates_do_not_relabel_or_create_scored_evidence() -> None:
    async def exercise() -> None:
        board = chess.Board()
        move = next(iter(board.legal_moves))
        scored = {
            "multipv": 1,
            "score": chess.engine.PovScore(chess.engine.Cp(22), chess.WHITE),
            "pv": [move],
            "depth": 7,
            "nodes": 70,
            "time": 0.07,
        }
        metadata = {"multipv": 1, "depth": 20, "nodes": 900, "time": 0.9}
        adapter = await adapter_with(FakeProtocol(lambda _: FakeAnalysis([metadata, scored, metadata])), FakeTransport())
        report = await adapter.analyze(context_for(board), EnginePolicy(0.1))
        assert report.status is EngineStatus.COMPLETED
        assert len(report.candidates) == 1
        candidate = report.candidates[0]
        assert (candidate.depth, candidate.nodes, candidate.elapsed_seconds) == (7, 70, 0.07)

    asyncio.run(exercise())


def test_canceling_prepare_terminates_a_child_stalled_in_configuration() -> None:
    async def exercise() -> None:
        protocol = FakeProtocol(lambda _: FakeAnalysis([]))
        transport = FakeTransport()
        transport.on_terminate = lambda: (
            None if protocol.returncode.done() else protocol.returncode.set_result(1)
        )

        async def stalls_configure(options: object) -> None:
            await asyncio.Event().wait()

        protocol.configure = stalls_configure  # type: ignore[method-assign]
        adapter = await adapter_with(protocol, transport)
        task = asyncio.create_task(adapter.prepare())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.terminated

    asyncio.run(exercise())


def test_prepare_reserves_startup_and_close_settles_it() -> None:
    async def exercise() -> None:
        entered_configuration = asyncio.Event()
        protocol = FakeProtocol(lambda _: FakeAnalysis([]))
        transport = FakeTransport()
        transport.on_terminate = lambda: (
            None if protocol.returncode.done() else protocol.returncode.set_result(1)
        )

        async def stalls_configure(options: object) -> None:
            entered_configuration.set()
            await asyncio.Event().wait()

        protocol.configure = stalls_configure  # type: ignore[method-assign]
        adapter = await adapter_with(protocol, transport)
        preparing = asyncio.create_task(adapter.prepare())
        await entered_configuration.wait()

        with pytest.raises(RuntimeError, match="already running"):
            await adapter.prepare()
        with pytest.raises(RuntimeError, match="already running"):
            await adapter.analyze(context_for(chess.Board()), EnginePolicy(0.1))

        await adapter.close()

        assert preparing.done()
        with pytest.raises(asyncio.CancelledError):
            await preparing
        assert transport.terminated
        assert adapter._active_task is None

    asyncio.run(exercise())


def test_stream_crash_reports_failure_and_next_request_restarts_engine() -> None:
    async def exercise() -> None:
        board = chess.Board()
        transport = FakeTransport()
        openings = 0

        async def opener(command: object) -> tuple[FakeTransport, FakeProtocol]:
            nonlocal openings
            openings += 1

            def complete(current: chess.Board) -> FakeAnalysis:
                return FakeAnalysis([{
                    "score": chess.engine.PovScore(chess.engine.Cp(1), chess.WHITE),
                    "pv": [next(iter(current.legal_moves))],
                }])

            protocol = FakeProtocol(
                (lambda _: CrashingAnalysis([])) if openings == 1 else complete
            )
            if openings == 1:
                protocol.returncode.set_result(1)
            return transport, protocol

        adapter = StockfishAdapter("fakefish", opener=opener)  # type: ignore[arg-type]
        assert (await adapter.analyze(context_for(board), EnginePolicy(0.1))).status is EngineStatus.FAILED
        assert (await adapter.analyze(context_for(board), EnginePolicy(0.1))).status is EngineStatus.COMPLETED
        assert openings == 2
        await adapter.close()

    asyncio.run(exercise())


def test_stalled_stop_and_quit_terminate_only_the_owned_child() -> None:
    async def exercise() -> None:
        board = chess.Board()
        protocol = FakeProtocol(lambda _: StalledAnalysis())
        transport = FakeTransport()
        transport.on_terminate = lambda: (
            None if protocol.returncode.done() else protocol.returncode.set_result(1)
        )
        adapter = await adapter_with(protocol, transport)
        adapter._stop_grace_seconds = 0.01
        task = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await asyncio.sleep(0)

        await adapter.cancel()

        assert transport.terminated
        assert (await task).status is EngineStatus.CANCELED
        assert task.done()

        hanging_protocol = FakeProtocol(lambda _: FakeAnalysis([]))
        hanging_transport = FakeTransport()
        hanging_transport.on_terminate = lambda: (
            None
            if hanging_protocol.returncode.done()
            else hanging_protocol.returncode.set_result(1)
        )

        async def never_quit() -> None:
            await asyncio.Event().wait()

        hanging_protocol.quit = never_quit  # type: ignore[method-assign]
        closing = await adapter_with(hanging_protocol, hanging_transport)
        await closing.analyze(context_for(board), EnginePolicy(0.1))
        closing._stop_grace_seconds = 0.01
        await closing.close()
        assert hanging_transport.terminated

    asyncio.run(exercise())


def test_overlap_is_rejected_before_a_second_engine_command_starts() -> None:
    async def exercise() -> None:
        board = chess.Board()
        started = asyncio.Event()

        def pending(_: chess.Board) -> FakeAnalysis:
            started.set()
            return FakeAnalysis([], wait_for_stop=True)

        protocol = FakeProtocol(pending)
        adapter = await adapter_with(protocol, FakeTransport())
        first = asyncio.create_task(adapter.analyze(context_for(board), EnginePolicy(1.0)))
        await started.wait()
        with pytest.raises(RuntimeError, match="already running"):
            await adapter.analyze(context_for(board), EnginePolicy(0.1))
        assert len(protocol.boards) == 1
        await adapter.cancel()
        await first

    asyncio.run(exercise())


def test_invalid_and_terminal_contexts_never_launch_engine() -> None:
    async def exercise() -> None:
        calls = 0

        async def opener(command: object) -> object:
            nonlocal calls
            calls += 1
            raise AssertionError("engine must not launch")

        adapter = StockfishAdapter("fakefish", opener=opener)  # type: ignore[arg-type]
        invalid = PositionContext(1, 1, (), "not a FEN", (), "not a FEN", False)
        invalid_report = await adapter.analyze(invalid, EnginePolicy(0.1))
        assert invalid_report.status is EngineStatus.FAILED

        mate = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        report = await adapter.analyze(context_for(mate), EnginePolicy(0.1))
        assert report.status is EngineStatus.UNSUPPORTED
        assert calls == 0

    asyncio.run(exercise())


def test_invalid_progress_evidence_stops_before_reporting_failure() -> None:
    async def exercise() -> None:
        board = chess.Board()
        bad_info: dict[str, object] = {
            "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
            "pv": [chess.Move.from_uci("a1a8")],
        }
        progress_analysis = ProgressThenStops(bad_info)
        protocol = FakeProtocol(lambda _: progress_analysis)
        adapter = await adapter_with(protocol, FakeTransport())

        async def progress(_: object) -> None:
            return None

        report = await adapter.analyze(context_for(board), EnginePolicy(1.0), progress=progress)
        assert report.status is EngineStatus.FAILED
        assert progress_analysis._stopped.is_set()
        await adapter.close()

    asyncio.run(exercise())


def test_invalid_progress_evidence_terminates_a_stalled_owned_engine() -> None:
    async def exercise() -> None:
        board = chess.Board()
        bad_info: dict[str, object] = {
            "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
            "pv": [chess.Move.from_uci("a1a8")],
        }
        progress_analysis = ProgressThenStalls(bad_info)
        protocol = FakeProtocol(lambda _: progress_analysis)
        transport = FakeTransport()
        transport.on_terminate = lambda: (
            None if protocol.returncode.done() else protocol.returncode.set_result(1)
        )
        adapter = await adapter_with(protocol, transport)
        adapter._stop_grace_seconds = 0.01

        async def progress(_: object) -> None:
            return None

        report = await adapter.analyze(context_for(board), EnginePolicy(1.0), progress=progress)
        assert report.status is EngineStatus.FAILED
        assert transport.terminated

    asyncio.run(exercise())


@pytest.mark.parametrize("pv", [[], [chess.Move.from_uci("d2d4")]])
def test_root_restricted_or_empty_principal_variation_fails(pv: list[chess.Move]) -> None:
    async def exercise() -> None:
        board = chess.Board()

        def restricted(_: chess.Board) -> FakeAnalysis:
            return FakeAnalysis([{
                "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
                "pv": pv,
            }])

        protocol = FakeProtocol(restricted)
        adapter = await adapter_with(protocol, FakeTransport())
        report = await adapter.analyze(
            context_for(board), EnginePolicy(0.1, root_moves=("e2e4",))
        )
        assert report.status is EngineStatus.FAILED
        await adapter.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("multipv", [0, -1, True, 0.5, 1.5, float("nan"), float("inf")])
def test_multipv_requires_positive_integer(multipv) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        EnginePolicy(0.1, multipv=multipv)


def test_broken_pipe_on_quit_terminates_owned_transport() -> None:
    async def exercise() -> None:
        class BrokenQuit(FakeProtocol):
            async def quit(self) -> None:
                raise BrokenPipeError("closed pipe")

        protocol = BrokenQuit(lambda board: FakeAnalysis([]))
        transport = FakeTransport()
        adapter = await adapter_with(protocol, transport)
        await adapter.prepare()
        await adapter.close()
        assert transport.terminated

    asyncio.run(exercise())


@pytest.mark.skipif(
    "NAMICHESS_TEST_ENGINE" not in os.environ,
    reason="set NAMICHESS_TEST_ENGINE to run the local Stockfish integration check",
)
def test_real_stockfish_analyzes_composed_position_and_recovers_after_cancel() -> None:
    async def exercise() -> None:
        adapter = StockfishAdapter(os.environ["NAMICHESS_TEST_ENGINE"])
        ordinary = chess.Board()
        composed = chess.Board("6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1")
        try:
            report = await adapter.analyze(context_for(composed), EnginePolicy(0.1, multipv=2))
            assert report.status is EngineStatus.COMPLETED
            assert report.candidates

            pending = asyncio.create_task(
                adapter.analyze(context_for(ordinary), EnginePolicy(2.0))
            )
            await asyncio.sleep(0.05)
            await adapter.cancel()
            assert (await pending).status is EngineStatus.CANCELED

            recovered = await adapter.analyze(context_for(ordinary), EnginePolicy(0.1))
            assert recovered.status is EngineStatus.COMPLETED
            assert recovered.candidates
        finally:
            await adapter.close()

    asyncio.run(exercise())


@pytest.mark.skipif("NAMICHESS_TEST_ENGINE" not in os.environ, reason="local Stockfish is not configured")
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("fen", [
    "6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1",
    "6rk/6pp/8/8/8/QQQQQ3/QQQQQQQQ/KQQQQQQQ w - - 0 1",
    "7k/8/8/8/8/P7/PPPPPPPP/K7 w - - 0 1",
])
def test_real_stockfish_unusual_material_and_color_mirrors(fen: str, mirrored: bool) -> None:
    async def exercise() -> None:
        board = chess.Board(fen)
        if mirrored:
            board = board.mirror()
        assert len(board.piece_map()) <= 32
        adapter = StockfishAdapter(os.environ["NAMICHESS_TEST_ENGINE"])
        try:
            report = await adapter.analyze(context_for(board), EnginePolicy(0.1, multipv=2))
            assert report.status is EngineStatus.COMPLETED
            assert report.candidates
            for candidate in report.candidates:
                replay = board.copy(stack=True)
                for uci in candidate.pv:
                    move = chess.Move.from_uci(uci)
                    assert move in replay.legal_moves
                    replay.push(move)
        finally:
            await adapter.close()

    asyncio.run(exercise())
