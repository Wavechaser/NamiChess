"""Bounded, legality-aware material evaluation on one capture square."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

import chess


MAX_EXCHANGE_NODES = 4096
_YIELD_INTERVAL = 32
_PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}


class ExchangeStatus(str, Enum):
    """Whether the bounded target-square model established an exact result."""

    COMPLETED = "completed"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


class ExchangeLimit(str, Enum):
    """The resource limit that prevented completion, when applicable."""

    DEADLINE = "deadline"
    NODES = "nodes"


@dataclass(frozen=True, slots=True)
class ExchangeEvidence:
    """Replayable evidence from the target-square material model."""

    status: ExchangeStatus
    line: tuple[str, ...]
    material_result: int | None
    perspective: str
    nodes: int
    node_limit: int
    limit_reached: ExchangeLimit | None = None
    model: str = "target_square_material"


@dataclass(frozen=True, slots=True)
class _SearchResult:
    status: ExchangeStatus
    score: int | None = None
    line: tuple[str, ...] = ()
    limit_reached: ExchangeLimit | None = None


class _ExchangeSearch:
    def __init__(
        self,
        *,
        perspective: chess.Color,
        target: chess.Square,
        deadline: float,
        monotonic: Callable[[], float],
        node_limit: int,
        cooperate: Callable[[], Awaitable[bool]] | None,
    ) -> None:
        self.perspective = perspective
        self.target = target
        self.deadline = deadline
        self.monotonic = monotonic
        self.node_limit = node_limit
        self.cooperate = cooperate
        self.nodes = 0

    async def evaluate(self, board: chess.Board, score: int) -> _SearchResult:
        if self.monotonic() >= self.deadline:
            return _SearchResult(ExchangeStatus.INCOMPLETE, limit_reached=ExchangeLimit.DEADLINE)
        if self.nodes >= self.node_limit:
            return _SearchResult(ExchangeStatus.INCOMPLETE, limit_reached=ExchangeLimit.NODES)

        self.nodes += 1
        if self.cooperate is not None:
            if not await self.cooperate():
                limit = ExchangeLimit.DEADLINE if self.monotonic() >= self.deadline else ExchangeLimit.NODES
                return _SearchResult(ExchangeStatus.INCOMPLETE, limit_reached=limit)
        elif self.nodes % _YIELD_INTERVAL == 0:
            await asyncio.sleep(0)

        # A terminal chess result has no legal decision to stop exchanging, and
        # its value cannot be represented by this deliberately material-only model.
        if board.outcome(claim_draw=False) is not None:
            return _SearchResult(ExchangeStatus.UNSUPPORTED)

        legal_moves = tuple(board.legal_moves)
        captures = tuple(
            sorted(
                (move for move in legal_moves if move.to_square == self.target and board.is_capture(move)),
                key=lambda move: move.uci(),
            )
        )

        outside_moves = tuple(move for move in legal_moves if move not in captures)
        if board.is_check():
            if outside_moves:
                return _SearchResult(ExchangeStatus.UNSUPPORTED)
            if not captures:
                return _SearchResult(ExchangeStatus.UNSUPPORTED)
            best_score: int | None = None
            best_line: tuple[str, ...] = ()
        elif outside_moves:
            # Declining a further capture is a legal decision in a non-checking,
            # non-terminal position. Retaining it on ties keeps evidence minimal.
            best_score = score
            best_line = ()
        else:
            best_score = None
            best_line = ()

        maximizing = board.turn == self.perspective
        for move in captures:
            child_score = score + _material_delta(board, move, self.perspective)
            board.push(move)
            child = await self.evaluate(board, child_score)
            board.pop()
            if child.status is not ExchangeStatus.COMPLETED:
                return child
            assert child.score is not None
            if best_score is None or (child.score > best_score if maximizing else child.score < best_score):
                best_score = child.score
                best_line = (move.uci(), *child.line)

        assert best_score is not None
        return _SearchResult(ExchangeStatus.COMPLETED, best_score, best_line)


async def evaluate_exchange(
    board: chess.Board,
    first_move: chess.Move,
    *,
    perspective: chess.Color,
    deadline: float,
    monotonic: Callable[[], float],
    node_limit: int = MAX_EXCHANGE_NODES,
    cooperate: Callable[[], Awaitable[bool]] | None = None,
) -> ExchangeEvidence:
    """Evaluate a forced capture and optimal legal recaptures on its target square.

    The returned integer is only the material swing along the replayable line,
    measured from ``perspective``. It is not a position evaluation and must not
    be used to reject engine candidates.
    """
    if not isinstance(perspective, bool):
        raise TypeError("perspective must be a chess color")
    if isinstance(node_limit, bool) or not isinstance(node_limit, int) or not 1 <= node_limit <= MAX_EXCHANGE_NODES:
        raise ValueError(f"node_limit must be between 1 and {MAX_EXCHANGE_NODES}")
    if not math.isfinite(deadline):
        raise ValueError("deadline must be finite")
    if first_move not in board.legal_moves:
        raise ValueError("first_move must be legal in the supplied position")
    if not board.is_capture(first_move):
        raise ValueError("first_move must be a capture")

    scratch = board.copy(stack=True)
    initial_delta = _material_delta(scratch, first_move, perspective)
    scratch.push(first_move)
    search = _ExchangeSearch(
        perspective=perspective,
        target=first_move.to_square,
        deadline=deadline,
        monotonic=monotonic,
        node_limit=node_limit,
        cooperate=cooperate,
    )
    result = await search.evaluate(scratch, initial_delta)
    perspective_name = "white" if perspective == chess.WHITE else "black"
    line = (first_move.uci(), *result.line) if result.status is ExchangeStatus.COMPLETED else ()
    return ExchangeEvidence(
        status=result.status,
        line=line,
        material_result=result.score if result.status is ExchangeStatus.COMPLETED else None,
        perspective=perspective_name,
        nodes=search.nodes,
        node_limit=node_limit,
        limit_reached=result.limit_reached,
    )


def _material_delta(board: chess.Board, move: chess.Move, perspective: chess.Color) -> int:
    if board.is_en_passant(move):
        captured_type = chess.PAWN
    else:
        captured = board.piece_at(move.to_square)
        captured_type = captured.piece_type if captured is not None else None

    gain = _PIECE_VALUES.get(captured_type, 0)
    if move.promotion is not None:
        gain += _PIECE_VALUES[move.promotion] - _PIECE_VALUES[chess.PAWN]
    return gain if board.turn == perspective else -gain
