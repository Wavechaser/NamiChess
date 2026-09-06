"""Bounded local forcing exploration with truthful reply coverage."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

import chess

from namichess.analysis.exchange import ExchangeEvidence, evaluate_exchange
from namichess.analysis.static import MoveDelta, _move_delta_from_facts, move_delta, position_facts
from namichess.analysis.threats import ThreatEvidence, verify_checking_threats
from namichess.analysis.continuations import continuation_context
from namichess.domain.models import PositionContext, PositionId
from namichess.domain.position import replay_position


MAX_LOCAL_DEPTH = 4
MAX_LOCAL_NODES = 10_000
_YIELD_INTERVAL = 32


class LocalLimit(str, Enum):
    DEADLINE = "deadline"
    NODES = "nodes"


class LocalExit(str, Enum):
    EXAMINED = "examined"
    WITNESSED_MATE = "witnessed_mate"
    UNRESOLVED = "unresolved"


class LocalTermination(str, Enum):
    TERMINAL = "terminal"
    DEPTH = "depth"
    NO_FORCING_MOVE = "no_forcing_move"
    LIMIT = "limit"


@dataclass(frozen=True, slots=True)
class LocalLimits:
    seconds: float = 0.25
    max_depth: int = MAX_LOCAL_DEPTH
    node_limit: int = MAX_LOCAL_NODES

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds < 0:
            raise ValueError("local seconds must be finite and nonnegative")
        if isinstance(self.max_depth, bool) or not isinstance(self.max_depth, int) or not 1 <= self.max_depth <= MAX_LOCAL_DEPTH:
            raise ValueError(f"local depth must be between 1 and {MAX_LOCAL_DEPTH}")
        if isinstance(self.node_limit, bool) or not isinstance(self.node_limit, int) or not 1 <= self.node_limit <= MAX_LOCAL_NODES:
            raise ValueError(f"local nodes must be between 1 and {MAX_LOCAL_NODES}")


@dataclass(frozen=True, slots=True)
class LocalLine:
    moves: tuple[str, ...]
    exit: LocalExit
    deltas: tuple[MoveDelta, ...]
    branch_scope: str
    termination: LocalTermination
    reply_exchange: ExchangeEvidence | None = None


@dataclass(frozen=True, slots=True)
class LocalRootEvidence:
    root_uci: str
    legal_reply_count: int
    examined_reply_count: int
    lines: tuple[LocalLine, ...]
    exchange: ExchangeEvidence | None = None
    first_reply: str | None = None
    omitted_replies: tuple[str, ...] = ()
    threats: tuple[ThreatEvidence, ...] = ()
    root_delta: MoveDelta | None = None


@dataclass(frozen=True, slots=True)
class LocalExploration:
    position_id: PositionId
    roots: tuple[LocalRootEvidence, ...]
    nodes: int
    limits: LocalLimits
    limit_reached: LocalLimit | None
    omitted_legal_moves: tuple[str, ...]


class _Explorer:
    def __init__(self, context: PositionContext, limits: LocalLimits, deadline: float, monotonic: Callable[[], float], cancelled: Callable[[], bool], request_id: int) -> None:
        self.context = context
        self.limits = limits
        self.deadline = deadline
        self.monotonic = monotonic
        self.cancelled = cancelled
        self.request_id = request_id
        self.nodes = 0
        self.limit_reached: LocalLimit | None = None

    async def checkpoint(self) -> bool:
        if self.cancelled():
            raise asyncio.CancelledError
        if self.monotonic() >= self.deadline:
            self.limit_reached = LocalLimit.DEADLINE
            return False
        if self.nodes >= self.limits.node_limit:
            self.limit_reached = LocalLimit.NODES
            return False
        self.nodes += 1
        if self.nodes % _YIELD_INTERVAL == 0:
            await asyncio.sleep(0)
        return True

    async def line(self, board: chess.Board, prefix: tuple[str, ...], depth: int, root_color: chess.Color) -> LocalLine:
        if not await self.checkpoint():
            return self.result(prefix, LocalExit.UNRESOLVED, LocalTermination.LIMIT)
        if board.is_checkmate():
            return self.result(prefix, LocalExit.WITNESSED_MATE if board.turn == root_color else LocalExit.EXAMINED, LocalTermination.TERMINAL)
        if board.is_game_over(claim_draw=False):
            return self.result(prefix, LocalExit.EXAMINED, LocalTermination.TERMINAL)
        if depth >= self.limits.max_depth:
            return self.result(prefix, LocalExit.EXAMINED, LocalTermination.DEPTH)
        forcing = _ordered_moves(board, tuple(board.legal_moves), forcing_only=True)
        if not forcing:
            return self.result(prefix, LocalExit.EXAMINED, LocalTermination.NO_FORCING_MOVE)
        move = forcing[0]
        board.push(move)
        result = await self.line(board, (*prefix, move.uci()), depth + 1, root_color)
        board.pop()
        return result

    def result(self, prefix: tuple[str, ...], exit: LocalExit, termination: LocalTermination) -> LocalLine:
        if termination is LocalTermination.LIMIT:
            deltas: tuple[MoveDelta, ...] = ()
        else:
            deltas = _deltas(self.context, self.request_id, prefix)
            if self.monotonic() >= self.deadline:
                self.limit_reached = LocalLimit.DEADLINE
                exit, termination, deltas = LocalExit.UNRESOLVED, LocalTermination.LIMIT, ()
        return LocalLine(prefix, exit, deltas, _branch_scope(self.context, prefix), termination)


async def explore_local(
    context: PositionContext,
    *,
    limits: LocalLimits,
    deadline: float,
    monotonic: Callable[[], float],
    root_moves: tuple[str, ...] = (),
    piece_square: str | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    request_id: int = 0,
) -> LocalExploration:
    """Explore actual-side legal roots and all immediate legal replies.

    Deeper continuations are forcing examples. ``examined_reply_count`` is the
    only exhaustive-coverage signal and never derives from a PV.
    """
    if not math.isfinite(deadline):
        raise ValueError("deadline must be finite")
    board, _ = replay_position(context)
    if board.is_game_over(claim_draw=False):
        return LocalExploration(context.position_id, (), 0, limits, None, ())
    legal = tuple(board.legal_moves)
    legal_by_uci = {move.uci(): move for move in legal}
    if any(uci not in legal_by_uci for uci in root_moves):
        raise ValueError("local root move must be legal")
    selected = (
        tuple(legal_by_uci[uci] for uci in dict.fromkeys(root_moves))
        if root_moves
        else _ordered_moves(board, legal, piece_square, forcing_only=piece_square is None)
    )
    explorer = _Explorer(context, limits, deadline, monotonic, cancelled, request_id)
    if monotonic() >= deadline:
        explorer.limit_reached = LocalLimit.DEADLINE
    roots: list[LocalRootEvidence] = []
    completed_roots: set[str] = set()
    before_facts = position_facts(context) if explorer.limit_reached is None else None
    for root in selected:
        if explorer.limit_reached is not None:
            break
        if not await explorer.checkpoint():
            break
        exchange = None
        if board.is_capture(root):
            remaining_nodes = limits.node_limit - explorer.nodes
            if remaining_nodes <= 0:
                explorer.limit_reached = LocalLimit.NODES
                break
            exchange = await evaluate_exchange(
                board, root, perspective=board.turn, deadline=deadline,
                monotonic=monotonic, node_limit=min(4096, remaining_nodes),
                cooperate=explorer.checkpoint,
            )
        child = board.copy(stack=True)
        child.push(root)
        root_context = continuation_context(context, request_id, (*context.moves, root.uci()), child)
        after_facts = position_facts(root_context)
        assert before_facts is not None
        root_delta = _move_delta_from_facts(context, root_context, before_facts, after_facts)
        if monotonic() >= deadline:
            explorer.limit_reached = LocalLimit.DEADLINE
        terminal = child.is_game_over(claim_draw=False)
        replies = () if terminal else tuple(sorted(child.legal_moves, key=lambda move: move.uci()))
        threats = await verify_checking_threats(
            context=context, request_id=request_id, root_context=root_context,
            root_delta=root_delta, after_facts=after_facts, after_root=child,
            max_depth=limits.max_depth,
            checkpoint=explorer.checkpoint, deadline=deadline, monotonic=monotonic,
        )
        if explorer.limit_reached is not None:
            roots.append(LocalRootEvidence(
                root.uci(), len(replies), 0, (), exchange,
                replies[0].uci() if replies else None,
                tuple(reply.uci() for reply in replies), threats, root_delta,
            ))
            break
        lines: list[LocalLine] = []
        examined = 0
        if terminal:
            lines.append(await explorer.line(child, (root.uci(),), 1, board.turn))
        elif limits.max_depth == 1:
            lines.append(explorer.result((root.uci(),), LocalExit.EXAMINED, LocalTermination.DEPTH))
        elif not replies:
            lines.append(await explorer.line(child, (root.uci(),), 1, board.turn))
        else:
            for reply in replies:
                if explorer.limit_reached is not None:
                    break
                reply_exchange = None
                if child.is_capture(reply):
                    remaining_nodes = limits.node_limit - explorer.nodes
                    if remaining_nodes <= 0:
                        explorer.limit_reached = LocalLimit.NODES
                        break
                    reply_exchange = await evaluate_exchange(
                        child, reply, perspective=board.turn, deadline=deadline,
                        monotonic=monotonic, node_limit=min(4096, remaining_nodes),
                        cooperate=explorer.checkpoint,
                    )
                    if explorer.limit_reached is not None:
                        break
                child.push(reply)
                line = await explorer.line(child, (root.uci(), reply.uci()), 2, board.turn)
                child.pop()
                lines.append(replace(line, reply_exchange=reply_exchange))
                if lines[-1].exit is not LocalExit.UNRESOLVED:
                    examined += 1
        covered_replies = {line.moves[1] for line in lines if len(line.moves) > 1 and line.exit is not LocalExit.UNRESOLVED}
        roots.append(LocalRootEvidence(
            root.uci(), len(replies), examined, tuple(lines), exchange,
            replies[0].uci() if replies else None,
            tuple(reply.uci() for reply in replies if reply.uci() not in covered_replies),
            threats, root_delta,
        ))
        if examined == len(replies):
            completed_roots.add(root.uci())
        if explorer.limit_reached is not None:
            break
    omitted = tuple(move.uci() for move in _ordered_moves(board, legal) if move.uci() not in completed_roots)
    return LocalExploration(context.position_id, tuple(roots), explorer.nodes, limits, explorer.limit_reached, omitted)


def _ordered_moves(
    board: chess.Board,
    moves: tuple[chess.Move, ...],
    piece_square: str | None = None,
    *,
    forcing_only: bool = False,
) -> tuple[chess.Move, ...]:
    mover = board.turn
    def key(move: chess.Move) -> tuple[int, str]:
        gives_check = board.gives_check(move)
        capture_or_promotion = board.is_capture(move) or move.promotion is not None
        before_attacks = board.attacks(move.from_square)
        board.push(move)
        moved_attacks = board.attacks(move.to_square)
        direct = any(board.color_at(square) == board.turn for square in moved_attacks if square not in before_attacks)
        board.pop()
        priority = 0 if gives_check else 1 if capture_or_promotion else 2 if direct else 3
        return priority, move.uci()

    candidates = moves
    if piece_square is not None:
        square = chess.parse_square(piece_square)
        candidates = tuple(move for move in moves if move.from_square == square)
    ordered = tuple(sorted(candidates, key=key))
    return tuple(move for move in ordered if not forcing_only or key(move)[0] < 3)


def _deltas(context: PositionContext, request_id: int, line: tuple[str, ...]) -> tuple[MoveDelta, ...]:
    board, _ = replay_position(context)
    previous = context
    moves = list(context.moves)
    result: list[MoveDelta] = []
    for index, uci in enumerate(line, 1):
        board.push_uci(uci)
        moves.append(uci)
        current = continuation_context(context, request_id, tuple(moves), board)
        result.append(move_delta(previous, current))
        previous = current
    return tuple(result)


def _branch_scope(context: PositionContext, line: tuple[str, ...]) -> str:
    return f"position:{context.document_id}:{context.game_number}:{'.'.join(map(str, context.node_path)) or 'root'}:local:{'.'.join(line)}"
