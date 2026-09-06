"""Bounded candidate comparison and current-position tactical evidence."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, Protocol

import chess

from namichess.analysis.assessments import (
    MoveSafetyAssessment,
    OverloadAssessment,
    TrappingAssessment,
    assess_move_safety,
    assess_overload,
    assess_trapping,
)
from namichess.analysis.engine import EngineCandidate, EnginePolicy, EngineProgress, EngineReport, EngineScore, EngineStatus, MAX_ENGINE_PIECES, ScoreBound
from namichess.analysis.evidence import Evidence, Explanation, line_consequences
from namichess.analysis.local import LocalExploration, LocalLimits, explore_local
from namichess.analysis.static import move_delta, position_facts
from namichess.analysis.continuations import continuation_context
from namichess.domain.models import PieceId, PiecePlacement, PositionContext, PositionId, SquareRef
from namichess.domain.position import replay_position


@dataclass(frozen=True, slots=True)
class AnalysisPolicy:
    seconds: float = 5.0
    survey_seconds: float = 1.0
    candidate_limit: int = 5
    comparison_limit: int = 2
    total_candidate_limit: int = 7
    local: LocalLimits = LocalLimits()
    focused_seconds: float = 15.0
    focused_local: LocalLimits = LocalLimits(seconds=1.0)


class ProbeKind(Enum):
    MOVE = "move"
    PIECE = "piece"


@dataclass(frozen=True, slots=True)
class ProbeSubject:
    kind: ProbeKind
    move: str | None = None
    piece: PieceId | None = None

    @classmethod
    def for_move(cls, uci: str) -> ProbeSubject:
        return cls(ProbeKind.MOVE, move=uci)

    @classmethod
    def for_piece(cls, piece: PieceId) -> ProbeSubject:
        return cls(ProbeKind.PIECE, piece=piece)


class AnalysisState(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate_id: str
    position_id: PositionId
    uci: str
    san: str
    mover_color: str
    rank: int | None
    score: EngineScore | None
    pv: tuple[str, ...]
    provisional: bool
    explanation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    survey_score: EngineScore | None = None


@dataclass(frozen=True, slots=True)
class Coverage:
    surveyed: int
    probed: int
    requested: int
    interrupted: bool
    total_legal: int = 0


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    request_id: int
    revision: int
    state: AnalysisState
    candidates: tuple[CandidateResult, ...] = ()
    explanations: tuple[Explanation, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    coverage: Coverage = Coverage(0, 0, 0, False)
    message: str | None = None
    engine_name: str | None = None
    subject: ProbeSubject | None = None
    local: LocalExploration | None = None
    local_limits: LocalLimits = LocalLimits()
    move_safety: tuple[MoveSafetyAssessment, ...] = ()
    trapping: tuple[TrappingAssessment, ...] = ()
    overload: tuple[OverloadAssessment, ...] = ()
    assessment_pieces: tuple[PiecePlacement, ...] = ()


class AnalysisEngine(Protocol):
    async def prepare(self) -> str | None: ...
    async def analyze(self, context: PositionContext, policy: EnginePolicy, *, progress=None) -> EngineReport: ...
    async def cancel(self) -> None: ...
    async def finish(self) -> EngineReport | None: ...
    async def close(self) -> None: ...


class AnalysisController:
    """Runs one request and retains only the latest replacement."""

    def __init__(self, engine: AnalysisEngine, *, policy: AnalysisPolicy = AnalysisPolicy(), monotonic: Callable[[], float] = time.monotonic) -> None:
        self._engine, self._policy, self._clock = engine, policy, monotonic
        self._worker: asyncio.Task[None] | None = None
        self._active_run: asyncio.Task[AnalysisResult] | None = None
        self._pending: tuple[int, int, PositionContext, tuple[str, ...], ProbeSubject | None] | None = None
        self._superseded = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._request = 0
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        self.latest: AnalysisResult | None = None
        self.progress: EngineProgress | None = None

    def submit(self, context: PositionContext, revision: int, compare: tuple[str, ...] = (), subject: ProbeSubject | None = None) -> int:
        if self._closed:
            raise RuntimeError("analysis controller is closed")
        _validate_subject(context, subject)
        self._request += 1
        item = (self._request, revision, context, compare, subject)
        limits = self._policy.focused_local if subject is not None else self._policy.local
        self.latest = AnalysisResult(self._request, revision, AnalysisState.RUNNING, subject=subject, local_limits=limits)
        self.progress = None
        self._pending = item
        self._idle.clear()
        self._superseded.set()
        if self._worker is None:
            self._worker = asyncio.create_task(self._work())
        return self._request

    def submit_probe(self, context: PositionContext, revision: int, subject: ProbeSubject) -> int:
        return self.submit(context, revision, subject=subject)

    async def wait(self) -> AnalysisResult | None:
        await self._idle.wait()
        return self.latest

    async def cancel(self) -> None:
        request_id = self._request
        active = self._active_run
        if self._worker is None and active is None:
            return
        self._pending = None
        self._superseded.set()
        if active is not None:
            await self._engine.cancel()
            if active is not asyncio.current_task():
                await asyncio.shield(active)
        if self.latest is not None and self.latest.request_id == request_id:
            self.latest = replace(self.latest, state=AnalysisState.CANCELED)

    async def close(self) -> None:
        if self._close_task is not None:
            await asyncio.shield(self._close_task)
            return
        self._closed = True
        request_id = self._request
        self._pending = None
        self._superseded.set()
        self._close_task = asyncio.create_task(self._close(request_id))
        await asyncio.shield(self._close_task)

    async def _close(self, request_id: int) -> None:
        await self._engine.cancel()
        if self._worker is not None and self._worker is not asyncio.current_task():
            await asyncio.shield(self._worker)
        await self._engine.close()
        if (
            self.latest is not None
            and self.latest.request_id == request_id
            and self.latest.state is AnalysisState.RUNNING
        ):
            self.latest = replace(self.latest, state=AnalysisState.CANCELED)

    async def _work(self) -> None:
        try:
            while self._pending is not None:
                item, self._pending = self._pending, None
                self._superseded.clear()
                self._active_run = asyncio.create_task(self._run(*item))
                result = await self._active_run
                self._active_run = None
                if item[0] == self._request:
                    self.latest = result
        finally:
            self._active_run = None
            self._worker = None
            self._idle.set()

    async def _run(self, request_id: int, revision: int, context: PositionContext, compare: tuple[str, ...], subject: ProbeSubject | None) -> AnalysisResult:
        board, _ = replay_position(context)
        limits = self._policy.focused_local if subject is not None else self._policy.local
        base = dict(request_id=request_id, revision=revision, subject=subject, local_limits=limits)
        if board.is_game_over():
            explanations, evidence = _current_tactics(board, context, request_id, revision)
            local = await self._local(request_id, context, subject, limits, self._clock() + limits.seconds)
            return AnalysisResult(**base, state=AnalysisState.COMPLETED, explanations=explanations, evidence=evidence, local=local, **_assessments(context, local, subject), message="terminal position; no engine search")
        legal = {move.uci() for move in board.legal_moves}
        compared = tuple(dict.fromkeys(compare))
        if len(compared) > self._policy.comparison_limit or any(move not in legal for move in compared):
            return AnalysisResult(**base, state=AnalysisState.FAILED, message="comparison moves must be distinct legal moves")
        try:
            local = None
            local_assessments: dict[str, tuple[object, ...]] = {}
            if len(board.piece_map()) > MAX_ENGINE_PIECES:
                if local is None:
                    local = await self._local(request_id, context, subject, limits, self._clock() + limits.seconds)
                static_explanations, static_evidence = _current_tactics(board, context, request_id, revision)
                return AnalysisResult(**base, state=AnalysisState.UNSUPPORTED, explanations=static_explanations, evidence=static_evidence, local=local, **_assessments(context, local, subject), message=f"engine analysis supports at most {MAX_ENGINE_PIECES} occupied squares")
            engine_name = await self._prepare(request_id)
            if engine_name is _SUPERSEDED:
                return AnalysisResult(**base, state=AnalysisState.CANCELED)
            deadline = self._clock() + (self._policy.focused_seconds if subject is not None else self._policy.seconds)
            if subject is not None:
                local = await self._local(request_id, context, subject, limits, min(deadline, self._clock() + limits.seconds))
                if request_id != self._request:
                    return AnalysisResult(**base, state=AnalysisState.CANCELED, local=local)
                local_assessments = _assessments(context, local, subject)
            survey_time = min(self._policy.survey_seconds, max(0.0, deadline - self._clock()))
            survey = await self._search(request_id, context, EnginePolicy(survey_time, self._policy.candidate_limit), deadline) if survey_time > 0 else None
            if survey is None:
                return AnalysisResult(**base, state=AnalysisState.COMPLETED, coverage=Coverage(0, 0, 0, True, len(legal)), engine_name=engine_name, local=local, **local_assessments)
            if survey.status not in (EngineStatus.COMPLETED,):
                return AnalysisResult(**base, state=_state(survey.status), message=survey.message, engine_name=engine_name, local=local)
            roots = {candidate.pv[0] for candidate in survey.candidates if candidate.pv}
            roots.update(compared)
            subject_roots = (
                tuple(root.root_uci for root in local.roots)
                if subject is not None and local is not None
                else _subject_roots(context, subject)
            )
            roots.update(subject_roots)
            selected = tuple(dict.fromkeys((*subject_roots, *sorted(roots))))[: self._policy.total_candidate_limit]
            probes: dict[str, EngineCandidate] = {}
            interrupted = False
            for index, move in enumerate(selected):
                remaining = deadline - self._clock()
                if remaining <= 0:
                    interrupted = True
                    break
                report = await self._search(request_id, context, EnginePolicy(remaining / (len(selected) - index), 1, (move,)), deadline)
                if report is None or report.status is EngineStatus.CANCELED:
                    interrupted = True
                    break
                if report.status is EngineStatus.FAILED:
                    return AnalysisResult(**base, state=AnalysisState.FAILED, message=report.message, engine_name=engine_name, local=local)
                if report.candidates:
                    probes[move] = report.candidates[0]
                    if request_id == self._request:
                        partial = _assemble(request_id, revision, board, context, selected, probes, survey.candidates)
                        static_explanations, static_evidence = _current_tactics(board, context, request_id, revision)
                        self.latest = AnalysisResult(**base, state=AnalysisState.RUNNING, candidates=partial[0], explanations=_order_explanations(static_explanations + partial[1]), evidence=partial[2] + static_evidence, coverage=Coverage(len(survey.candidates), len(probes), len(selected), True, len(legal)), engine_name=engine_name, local=local, **local_assessments)
            if subject is None:
                local = await explore_local(
                    context, limits=limits, deadline=self._clock() + limits.seconds,
                    monotonic=self._clock, root_moves=selected,
                    cancelled=lambda: request_id != self._request or self._closed or self._superseded.is_set(),
                    request_id=request_id,
                )
                local_assessments = _assessments(context, local, subject)
            candidates, explanations, evidence = _assemble(request_id, revision, board, context, selected, probes, survey.candidates)
            static_explanations, static_evidence = _current_tactics(board, context, request_id, revision)
            return AnalysisResult(**base, state=AnalysisState.COMPLETED, candidates=candidates, explanations=_order_explanations(static_explanations + explanations), evidence=evidence + static_evidence, coverage=Coverage(len(survey.candidates), len(probes), len(selected), interrupted, len(legal)), engine_name=engine_name, local=local, **local_assessments)
        except asyncio.CancelledError:
            if self.latest is not None and self.latest.request_id == request_id:
                return replace(self.latest, state=AnalysisState.CANCELED)
            return AnalysisResult(**base, state=AnalysisState.CANCELED)
        except Exception as error:
            return AnalysisResult(**base, state=AnalysisState.FAILED, message=str(error))

    async def _local(self, request_id: int, context: PositionContext, subject: ProbeSubject | None, limits: LocalLimits, deadline: float) -> LocalExploration:
        root_moves = (subject.move,) if subject is not None and subject.move is not None else ()
        piece_square = _piece_square(context, subject.piece) if subject is not None and subject.piece is not None else None
        return await explore_local(
            context, limits=limits, deadline=deadline, monotonic=self._clock,
            root_moves=root_moves, piece_square=piece_square,
            cancelled=lambda: request_id != self._request or self._closed or self._superseded.is_set(),
            request_id=request_id,
        )

    async def _prepare(self, request_id: int):
        task = asyncio.create_task(self._engine.prepare())
        replaced = asyncio.create_task(self._superseded.wait())
        try:
            done, _ = await asyncio.wait((task, replaced), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            await self._engine.cancel()
            await asyncio.shield(task)
            return _SUPERSEDED
        finally:
            replaced.cancel()

    async def _search(self, request_id: int, context: PositionContext, policy: EnginePolicy, deadline: float) -> EngineReport | None:
        callback = lambda progress: self._set_progress(request_id, progress)
        task = asyncio.create_task(self._engine.analyze(context, policy, progress=callback))
        replaced = asyncio.create_task(self._superseded.wait())
        try:
            timeout = min(policy.seconds, max(0.0, deadline - self._clock()))
            done, _ = await asyncio.wait((task, replaced), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return task.result()
            if replaced in done:
                await self._engine.cancel()
                return None
            finish = getattr(self._engine, "finish", None)
            if finish is not None:
                return await finish()
            await self._engine.cancel()
            return None
        finally:
            replaced.cancel()

    def _set_progress(self, request_id: int, progress: EngineProgress) -> None:
        if request_id == self._request:
            self.progress = progress


def _assessments(
    context: PositionContext, local: LocalExploration | None, subject: ProbeSubject | None,
) -> dict[str, tuple[object, ...]]:
    if local is None:
        return {}
    trapping = (
        (assess_trapping(context, local, subject.piece),)
        if subject is not None and subject.piece is not None
        else ()
    )
    overload = assess_overload(context, local)
    subjects = {
        *(item.piece for item in trapping),
        *(item.defender for item in overload),
    }
    _, placements = replay_position(context)
    return {
        "move_safety": assess_move_safety(context, local),
        "trapping": trapping,
        "overload": overload,
        "assessment_pieces": tuple(
            item for item in placements if item.piece_id in subjects
        ),
    }


_SUPERSEDED = object()


def _piece_square(context: PositionContext, piece: PieceId) -> str:
    placement = next((item for item in position_facts(context).pieces if item.piece_id == piece), None)
    if placement is None:
        raise ValueError("probe piece is not present in this position")
    return placement.square


def _subject_roots(context: PositionContext, subject: ProbeSubject | None) -> tuple[str, ...]:
    if subject is None:
        return ()
    if subject.move is not None:
        return (subject.move,)
    assert subject.piece is not None
    square = chess.parse_square(_piece_square(context, subject.piece))
    board, _ = replay_position(context)
    return tuple(sorted(move.uci() for move in board.legal_moves if move.from_square == square))


def _validate_subject(context: PositionContext, subject: ProbeSubject | None) -> None:
    if subject is None:
        return
    if (subject.move is None) == (subject.piece is None):
        raise ValueError("probe subject must identify exactly one move or piece")
    board, _ = replay_position(context)
    if subject.move is not None:
        try:
            move = chess.Move.from_uci(subject.move)
        except ValueError as exc:
            raise ValueError("probe move must be legal UCI") from exc
        if move not in board.legal_moves:
            raise ValueError("probe move must be legal UCI")
        if subject.kind is not ProbeKind.MOVE:
            raise ValueError("probe kind does not match move subject")
        return
    assert subject.piece is not None
    if subject.kind is not ProbeKind.PIECE:
        raise ValueError("probe kind does not match piece subject")
    placement = next((item for item in position_facts(context).pieces if item.piece_id == subject.piece), None)
    if placement is None:
        raise ValueError("probe piece is not present in this position")
    expected_color = "white" if board.turn else "black"
    if placement.color != expected_color:
        raise ValueError("probe piece must belong to the side to move")


def _state(status: EngineStatus) -> AnalysisState:
    return AnalysisState(status.value)


def _assemble(request_id: int, revision: int, board: chess.Board, context: PositionContext, roots: tuple[str, ...], probes: dict[str, EngineCandidate], survey: tuple[EngineCandidate, ...]):
    mating_replies_by_root: dict[str, tuple[str, ...]] = {}
    for uci in roots:
        reply_board = board.copy(stack=True)
        reply_board.push(chess.Move.from_uci(uci))
        replies = []
        for reply in reply_board.legal_moves:
            reply_board.push(reply)
            if reply_board.is_checkmate():
                replies.append(reply.uci())
            reply_board.pop()
        mating_replies_by_root[uci] = tuple(sorted(replies))
    exact = [(uci, item) for uci, item in probes.items() if item.score.bound is ScoreBound.EXACT and not mating_replies_by_root[uci]]
    mover = board.turn
    exact.sort(key=lambda pair: pair[0])
    exact.sort(key=lambda pair: _score_key(pair[1].score, mover), reverse=True)
    ranks = {uci: rank for rank, (uci, _) in enumerate(exact, 1)}
    survey_by_root = {item.pv[0]: item for item in survey if item.pv}
    candidates, explanations, evidence = [], [], []
    for uci in roots:
        scope = _scope(request_id, revision, context)
        candidate_id = f"{scope}:candidate:{uci}"
        item = probes.get(uci)
        survey_item = survey_by_root.get(uci)
        refs: list[str] = []
        exrefs: list[str] = []
        survey_evidence_id = None
        if survey_item is not None:
            survey_evidence_id = f"{candidate_id}:survey"
            evidence.append(Evidence(
                survey_evidence_id,
                "engine_survey",
                line=survey_item.pv,
                san_line=_san_lines(board, (survey_item.pv,))[0],
                engine_depth=survey_item.depth,
                engine_nodes=survey_item.nodes,
                engine_elapsed_seconds=survey_item.elapsed_seconds,
                score=survey_item.score,
            ))
            refs.append(survey_evidence_id)
        if item is not None:
            evidence_id = f"{candidate_id}:engine-line"
            consequences = line_consequences(board, item.pv, _pv_deltas(context, request_id, item.pv))
            evidence.append(Evidence(
                evidence_id,
                "engine_line",
                line=item.pv,
                san_line=_san_lines(board, (item.pv,))[0],
                consequences=consequences,
                engine_depth=item.depth,
                engine_nodes=item.nodes,
                engine_elapsed_seconds=item.elapsed_seconds,
                score=item.score,
            ))
            refs.append(evidence_id)
            for consequence in consequences:
                if consequence.capture is not None:
                    assert consequence.captured_color is not None
                    assert consequence.captured_piece_type is not None
                    eid = f"{candidate_id}:ply-{consequence.ply}:capture"
                    explanations.append(Explanation(
                        eid,
                        "line.capture",
                        (
                            ("san", consequence.san),
                            ("captured_color", consequence.captured_color),
                            ("captured_piece_type", consequence.captured_piece_type),
                            ("material_delta_white", consequence.material_delta_white),
                        ),
                        pieces=(consequence.mover, consequence.capture),
                        moves=(consequence.uci,),
                        evidence_refs=(evidence_id,),
                    ))
                    exrefs.append(eid)
                if consequence.gives_check:
                    eid = f"{candidate_id}:ply-{consequence.ply}:check"
                    explanations.append(Explanation(eid, "line.check", (("san", consequence.san),), pieces=(consequence.mover,), moves=(consequence.uci,), evidence_refs=(evidence_id,)))
                    exrefs.append(eid)
            if item.score.mate is not None:
                eid = f"{candidate_id}:reported-mate"
                explanations.append(Explanation(eid, "engine.reported_mate", (("moves", abs(item.score.mate)), ("winner", item.score.mate_winner or "unknown")), moves=(uci,), evidence_refs=(evidence_id,)))
                exrefs.append(eid)
        root_move = chess.Move.from_uci(uci)
        mating_replies = mating_replies_by_root[uci]
        if mating_replies:
            evidence_id = f"{candidate_id}:opponent-mate-in-one"
            evidence.append(Evidence(
                evidence_id,
                "legal_opponent_mate_in_one",
                alternative_lines=tuple((uci, reply) for reply in sorted(mating_replies)),
                alternative_san_lines=_san_lines(board, tuple((uci, reply) for reply in sorted(mating_replies))),
            ))
            refs.append(evidence_id)
            eid = f"{candidate_id}:opponent-mate-in-one-explanation"
            explanations.append(Explanation(eid, "candidate.allows_opponent_mate_in_one", (("reply_count", len(mating_replies)),), moves=(uci, *sorted(mating_replies)), evidence_refs=(evidence_id,)))
            exrefs.append(eid)
        if item and survey_item and _score_signature(item.score) != _score_signature(survey_item.score):
            eid = f"{candidate_id}:survey-final-disagreement"
            explanations.append(Explanation(eid, "engine.survey_final_disagreement", moves=(uci,), evidence_refs=(survey_evidence_id, f"{candidate_id}:engine-line")))
            exrefs.append(eid)
        candidates.append(CandidateResult(candidate_id, context.position_id, uci, board.san(root_move), "white" if board.turn else "black", ranks.get(uci), item.score if item else None, item.pv if item else (), item is None or item.score.bound is not ScoreBound.EXACT or bool(mating_replies), tuple(exrefs), tuple(refs), survey_item.score if survey_item else None))
    return tuple(candidates), tuple(explanations), tuple(evidence)


def _pv_deltas(context: PositionContext, request_id: int, pv: tuple[str, ...]):
    replay, _ = replay_position(context)
    previous = context
    result = []
    moves = list(context.moves)
    for ply, uci in enumerate(pv, 1):
        replay.push(chess.Move.from_uci(uci))
        moves.append(uci)
        current = continuation_context(context, request_id, tuple(moves), replay)
        result.append(move_delta(previous, current))
        previous = current
    return tuple(result)


def _current_tactics(board: chess.Board, context: PositionContext, request_id: int, revision: int) -> tuple[tuple[Explanation, ...], tuple[Evidence, ...]]:
    explanations: list[Explanation] = []
    evidence: list[Evidence] = []
    pid = context.position_id
    scope = _scope(request_id, revision, context)
    if board.is_check():
        ref = f"{scope}:current-check"
        checkers = tuple(SquareRef(pid, chess.square_name(square)) for square in sorted(board.checkers()))
        checker_ids = position_facts(context).checkers
        evidence.append(Evidence(ref, "legal_current_check"))
        explanations.append(Explanation(f"{scope}:current-check-explanation", "position.in_check", pieces=checker_ids, squares=checkers, evidence_refs=(ref,)))
    mates = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            mates.append(move.uci())
        board.pop()
    if mates:
        ref = f"{scope}:mate-in-one"
        lines = tuple((move,) for move in sorted(mates))
        evidence.append(Evidence(ref, "legal_mate_in_one", alternative_lines=lines, alternative_san_lines=_san_lines(board, lines)))
        explanations.append(Explanation(f"{scope}:mate-in-one-explanation", "position.mate_in_one", moves=tuple(sorted(mates)), evidence_refs=(ref,)))
    return tuple(explanations), tuple(evidence)


def _scope(request_id: int, revision: int, context: PositionContext) -> str:
    return f"request:{request_id}:revision:{revision}:position:{context.document_id}:{context.game_number}:{'.'.join(map(str, context.node_path)) or 'root'}"


def _san_lines(board: chess.Board, lines: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    result = []
    for line in lines:
        replay = board.copy(stack=True)
        san_line = []
        for uci in line:
            move = chess.Move.from_uci(uci)
            if move not in replay.legal_moves:
                raise ValueError("alternative evidence line contains an illegal move")
            san_line.append(replay.san(move))
            replay.push(move)
        result.append(tuple(san_line))
    return tuple(result)


def _order_explanations(explanations: tuple[Explanation, ...]) -> tuple[Explanation, ...]:
    priority = {
        "position.in_check": 0,
        "position.mate_in_one": 1,
        "candidate.allows_opponent_mate_in_one": 2,
    }
    return tuple(sorted(explanations, key=lambda item: priority.get(item.catalog_id, 3)))


def _score_signature(score: EngineScore) -> tuple[int | None, str | None, int]:
    cp_sign = None if score.centipawns is None else (1 if score.centipawns > 0 else -1 if score.centipawns < 0 else 0)
    return cp_sign, score.mate_winner, 0 if score.mate is None else (1 if score.mate > 0 else -1)


def _score_key(score: EngineScore, mover: chess.Color) -> tuple[int, int]:
    sign = 1 if mover == chess.WHITE else -1
    if score.mate_winner:
        wins = (score.mate_winner == ("white" if mover else "black"))
        return (2 if wins else -2, -(abs(score.mate or 0)) if wins else abs(score.mate or 0))
    return (0, sign * (score.centipawns or 0))
