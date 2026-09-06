"""Bounded asynchronous Stockfish analysis behind typed evidence values."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Protocol, Sequence

import chess
import chess.engine

from namichess.domain.models import PositionContext
from namichess.domain.validation import PositionValidationError, parse_fen


MAX_ENGINE_PIECES = 32


class EngineStatus(Enum):
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ScoreBound(Enum):
    EXACT = "exact"
    LOWER = "lower"
    UPPER = "upper"


@dataclass(frozen=True)
class EnginePolicy:
    seconds: float
    multipv: int = 1
    root_moves: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("seconds must be finite and positive")
        if type(self.multipv) is not int or self.multipv <= 0:
            raise ValueError("multipv must be a positive integer")


@dataclass(frozen=True)
class EngineScore:
    """A score from White's perspective, independent of the side to move."""

    centipawns: int | None
    mate: int | None
    mate_winner: str | None
    bound: ScoreBound


@dataclass(frozen=True)
class EngineCandidate:
    score: EngineScore
    pv: tuple[str, ...]
    depth: int | None
    nodes: int | None
    elapsed_seconds: float | None


@dataclass(frozen=True)
class EngineProgress:
    candidates: tuple[EngineCandidate, ...]
    elapsed_seconds: float


@dataclass(frozen=True)
class EngineReport:
    status: EngineStatus
    candidates: tuple[EngineCandidate, ...] = ()
    engine_name: str | None = None
    message: str | None = None


class EngineEvidenceError(ValueError):
    """An engine response cannot be supported by legal chess evidence."""


class UciProtocol(Protocol):
    id: dict[str, str]
    returncode: asyncio.Future[int]

    async def configure(self, options: dict[str, int]) -> None: ...

    async def analysis(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int,
        game: object,
        root_moves: Sequence[chess.Move] | None,
    ) -> chess.engine.AnalysisResult: ...

    async def quit(self) -> None: ...


UciOpener = Callable[[Sequence[str]], Awaitable[tuple[asyncio.SubprocessTransport, UciProtocol]]]
ProgressCallback = Callable[[EngineProgress], Awaitable[None] | None]


async def _open_uci(command: Sequence[str]) -> tuple[asyncio.SubprocessTransport, UciProtocol]:
    transport, protocol = await chess.engine.popen_uci(list(command))
    return transport, protocol


class StockfishAdapter:
    """Owns one UCI child process and at most one active analysis."""

    def __init__(
        self,
        command: str | Path,
        *,
        opener: UciOpener = _open_uci,
        monotonic: Callable[[], float] = time.monotonic,
        startup_timeout_seconds: float = 5.0,
        stop_grace_seconds: float = 2.0,
        threads: int = 1,
        hash_mb: int = 64,
    ) -> None:
        if (
            not math.isfinite(startup_timeout_seconds)
            or startup_timeout_seconds <= 0
            or not math.isfinite(stop_grace_seconds)
            or stop_grace_seconds <= 0
        ):
            raise ValueError("timeouts must be finite and positive")
        self._command = (str(command),)
        self._opener = opener
        self._monotonic = monotonic
        self._startup_timeout_seconds = startup_timeout_seconds
        self._stop_grace_seconds = stop_grace_seconds
        self._options = {"Threads": threads, "Hash": hash_mb}
        self._transport: asyncio.SubprocessTransport | None = None
        self._protocol: UciProtocol | None = None
        self._active: chess.engine.AnalysisResult | None = None
        self._active_task: asyncio.Task[EngineReport] | None = None
        self._was_canceled = False
        self._finish_requested = False
        self._closing = False

    async def analyze(
        self,
        context: PositionContext,
        policy: EnginePolicy,
        *,
        progress: ProgressCallback | None = None,
    ) -> EngineReport:
        """Analyze one context. Call ``cancel`` before replacing active work."""
        if self._closing:
            raise RuntimeError("engine is closing")
        if self._active_task is not None:
            raise RuntimeError("analysis is already running")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("analysis requires an asyncio task")
        self._active_task = task
        self._was_canceled = False
        self._finish_requested = False
        try:
            board = self._reconstruct_board(context)
            if len(board.piece_map()) > MAX_ENGINE_PIECES:
                return EngineReport(
                    EngineStatus.UNSUPPORTED,
                    message=f"engine analysis supports at most {MAX_ENGINE_PIECES} occupied squares",
                )
            if board.is_game_over():
                return EngineReport(EngineStatus.UNSUPPORTED, message="terminal positions have no engine search")

            protocol = await self._ensure_protocol()
            root_moves = self._parse_root_moves(board, policy.root_moves)
            analysis = await protocol.analysis(
                board,
                chess.engine.Limit(time=policy.seconds),
                multipv=policy.multipv,
                game=(context.document_id, context.game_number),
                root_moves=root_moves or None,
            )
            self._active = analysis
            if self._was_canceled:
                await self._stop_and_drain(analysis)
                return EngineReport(EngineStatus.CANCELED)
            if self._finish_requested:
                analysis.stop()
            started = self._monotonic()
            last_progress = started - 0.25
            progress_error: Exception | None = None
            snapshots: dict[int, dict[str, object]] = {}
            async for info in analysis:
                self._merge_snapshot(snapshots, info)
                now = self._monotonic()
                if progress is not None and now - last_progress >= 0.25:
                    try:
                        await self._publish(
                            progress, self._ordered_snapshots(snapshots), board, now - started, root_moves
                        )
                    except Exception as error:
                        progress_error = error
                        await self._stop_and_drain(analysis)
                        break
                    last_progress = now
            if progress_error is not None:
                raise progress_error
            candidates = self._candidates(self._ordered_snapshots(snapshots), board, root_moves=root_moves)
            if self._was_canceled:
                return EngineReport(EngineStatus.CANCELED)
            return EngineReport(
                EngineStatus.COMPLETED,
                candidates=candidates,
                engine_name=protocol.id.get("name"),
            )
        except (
            EngineEvidenceError,
            OSError,
            chess.engine.EngineError,
            asyncio.TimeoutError,
        ) as error:
            if self._was_canceled:
                return EngineReport(EngineStatus.CANCELED)
            return EngineReport(EngineStatus.FAILED, message=str(error))
        except asyncio.CancelledError:
            if self._active is not None:
                await self._stop_and_drain(self._active)
            else:
                await self._terminate_owned_process()
            return EngineReport(EngineStatus.CANCELED)
        finally:
            self._active = None
            self._active_task = None

    async def prepare(self) -> str | None:
        """Start and configure the reusable engine before an outer search budget."""
        if self._closing:
            raise RuntimeError("engine is closing")
        if self._active_task is not None:
            raise RuntimeError("analysis is already running")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("preparation requires an asyncio task")
        self._active_task = task
        try:
            protocol = await self._ensure_protocol()
            return protocol.id.get("name")
        finally:
            self._active_task = None

    async def cancel(self) -> None:
        """Stop active analysis before any replacement starts."""
        if self._active_task is None:
            return
        task = self._active_task
        self._was_canceled = True
        if task is asyncio.current_task():
            return
        if self._active is not None:
            self._active.stop()
        try:
            await asyncio.wait_for(
                asyncio.shield(task), self._stop_grace_seconds
            )
        except asyncio.TimeoutError:
            await self._terminate_owned_process()
            task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass

    async def finish(self) -> EngineReport | None:
        """Stop an active timed search and retain its final legal evidence."""
        task = self._active_task
        if task is None:
            return None
        if task is asyncio.current_task():
            raise RuntimeError("an active search cannot finish itself")
        self._finish_requested = True
        if self._active is not None:
            self._active.stop()
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), self._stop_grace_seconds
            )
        except asyncio.TimeoutError:
            await self._terminate_owned_process()
            task.cancel()
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
            return EngineReport(EngineStatus.FAILED, message="engine did not stop within the grace period")

    async def close(self) -> None:
        """Release the owned child process, even after a stalled stop/quit."""
        if self._closing:
            raise RuntimeError("engine is closing")
        self._closing = True
        try:
            await self.cancel()
            protocol = self._protocol
            if protocol is None:
                return
            try:
                await asyncio.wait_for(protocol.quit(), self._stop_grace_seconds)
            except (asyncio.TimeoutError, chess.engine.EngineError, OSError):
                await self._terminate_owned_process()
        finally:
            self._transport = None
            self._protocol = None
            self._closing = False

    def _reconstruct_board(self, context: PositionContext) -> chess.Board:
        try:
            board = parse_fen(context.starting_fen)
            selected_board = parse_fen(context.current_fen)
            for move_text in context.moves:
                move = chess.Move.from_uci(move_text)
                if move not in board.legal_moves:
                    raise EngineEvidenceError("position history contains an illegal move")
                board.push(move)
        except (PositionValidationError, ValueError) as error:
            raise EngineEvidenceError("position context contains invalid FEN or UCI") from error
        if board.fen(en_passant="fen") != selected_board.fen(en_passant="fen"):
            raise EngineEvidenceError("position history does not match the selected position")
        return board

    async def _ensure_protocol(self) -> UciProtocol:
        if self._protocol is not None and not self._protocol.returncode.done():
            return self._protocol
        self._transport = None
        self._protocol = None
        try:
            async with asyncio.timeout(self._startup_timeout_seconds):
                transport, protocol = await self._opener(self._command)
                self._transport = transport
                self._protocol = protocol
                await protocol.configure(self._options)
        except BaseException:
            await self._terminate_owned_process()
            raise
        return protocol

    async def _terminate_owned_process(self) -> None:
        transport = self._transport
        protocol = self._protocol
        if transport is not None:
            transport.terminate()
        if protocol is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(protocol.returncode), self._stop_grace_seconds
                )
            except asyncio.TimeoutError:
                pass
        self._transport = None
        self._protocol = None

    async def _stop_and_drain(self, analysis: chess.engine.AnalysisResult) -> None:
        analysis.stop()
        try:
            async with asyncio.timeout(self._stop_grace_seconds):
                async for _ in analysis:
                    pass
        except TimeoutError:
            await self._terminate_owned_process()

    def _parse_root_moves(
        self, board: chess.Board, root_moves: Sequence[str]
    ) -> tuple[chess.Move, ...]:
        parsed = []
        for move_text in root_moves:
            try:
                move = chess.Move.from_uci(move_text)
            except ValueError as error:
                raise EngineEvidenceError("root move is not valid UCI") from error
            if move not in board.legal_moves:
                raise EngineEvidenceError("root move is illegal in the selected position")
            parsed.append(move)
        return tuple(parsed)

    async def _publish(
        self,
        callback: ProgressCallback,
        infos: Sequence[dict[str, object]],
        board: chess.Board,
        elapsed_seconds: float,
        root_moves: Sequence[chess.Move],
    ) -> None:
        candidates = self._candidates(
            infos, board, allow_missing=True, root_moves=root_moves
        )
        value = callback(EngineProgress(candidates, elapsed_seconds))
        if inspect.isawaitable(value):
            await value

    def _candidates(
        self,
        infos: Sequence[dict[str, object]],
        board: chess.Board,
        *,
        allow_missing: bool = False,
        root_moves: Sequence[chess.Move] = (),
    ) -> tuple[EngineCandidate, ...]:
        candidates: list[EngineCandidate] = []
        for info in infos:
            if "score" not in info or "pv" not in info:
                if allow_missing:
                    continue
                raise EngineEvidenceError("engine result omitted score or principal variation")
            score = info["score"]
            pv = info["pv"]
            if not isinstance(score, chess.engine.PovScore) or not isinstance(pv, list):
                raise EngineEvidenceError("engine result has invalid score or principal variation")
            candidates.append(
                EngineCandidate(
                    score=self._score(score, info),
                    pv=self._validate_pv(board, pv, root_moves=root_moves),
                    depth=self._integer(info.get("depth")),
                    nodes=self._integer(info.get("nodes")),
                    elapsed_seconds=self._number(info.get("time")),
                )
            )
        if not candidates and not allow_missing:
            raise EngineEvidenceError("engine result has no candidate evidence")
        return tuple(candidates)

    @staticmethod
    def _score(score: chess.engine.PovScore, info: dict[str, object]) -> EngineScore:
        white = score.white()
        mate = white.mate()
        if mate is None:
            mate_winner = None
        elif isinstance(white, chess.engine.MateGivenType) or mate > 0:
            mate_winner = "white"
        else:
            mate_winner = "black"
        lower = info.get("lowerbound") is True
        upper = info.get("upperbound") is True
        if score.turn == chess.BLACK:
            lower, upper = upper, lower
        return EngineScore(
            centipawns=None if mate is not None else white.score(),
            mate=mate,
            mate_winner=mate_winner,
            bound=(
                ScoreBound.LOWER
                if lower
                else ScoreBound.UPPER
                if upper
                else ScoreBound.EXACT
            ),
        )

    @staticmethod
    def _validate_pv(
        board: chess.Board,
        pv: Sequence[object],
        *,
        root_moves: Sequence[chess.Move],
    ) -> tuple[str, ...]:
        if not pv:
            raise EngineEvidenceError("engine principal variation is empty")
        replay = board.copy(stack=True)
        result: list[str] = []
        for move in pv:
            if not isinstance(move, chess.Move) or move not in replay.legal_moves:
                raise EngineEvidenceError("engine principal variation is illegal")
            if not result and root_moves and move not in root_moves:
                raise EngineEvidenceError("engine principal variation ignores root move restriction")
            result.append(move.uci())
            replay.push(move)
        return tuple(result)

    @staticmethod
    def _integer(value: object) -> int | None:
        return value if isinstance(value, int) else None

    @staticmethod
    def _number(value: object) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        converted = float(value)
        return converted if math.isfinite(converted) else None

    @staticmethod
    def _merge_snapshot(
        snapshots: dict[int, dict[str, object]], info: dict[str, object]
    ) -> None:
        index_value = info.get("multipv", 1)
        index = index_value if isinstance(index_value, int) and index_value > 0 else 1
        if "score" in info and "pv" in info:
            snapshots[index] = dict(info)

    @staticmethod
    def _ordered_snapshots(
        snapshots: dict[int, dict[str, object]],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            snapshots[index]
            for index in sorted(snapshots)
            if "score" in snapshots[index] and "pv" in snapshots[index]
        )
