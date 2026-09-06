"""Typed, legally replayed evidence used by candidate explanations."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from namichess.analysis.engine import EngineScore
from namichess.domain.models import PieceId, PositionId, SquareRef
from namichess.analysis.static import MoveDelta


@dataclass(frozen=True, slots=True)
class LineConsequence:
    ply: int
    position_id: PositionId
    uci: str
    san: str
    mover: PieceId
    source: SquareRef
    target: SquareRef
    mover_color: str
    mover_piece_type: str
    gives_check: bool
    capture: PieceId | None
    capture_square: SquareRef | None
    captured_color: str | None
    captured_piece_type: str | None
    recapture: bool
    promotion: str | None
    material_delta_white: int
    checked_king: PieceId | None = None
    checked_king_square: SquareRef | None = None
    checkers: tuple[PieceId, ...] = ()
    checker_squares: tuple[SquareRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    kind: str
    line: tuple[str, ...] = ()
    san_line: tuple[str, ...] = ()
    alternative_lines: tuple[tuple[str, ...], ...] = ()
    alternative_san_lines: tuple[tuple[str, ...], ...] = ()
    consequences: tuple[LineConsequence, ...] = ()
    engine_depth: int | None = None
    engine_nodes: int | None = None
    engine_elapsed_seconds: float | None = None
    score: EngineScore | None = None


@dataclass(frozen=True, slots=True)
class Explanation:
    explanation_id: str
    catalog_id: str
    values: tuple[tuple[str, str | int | bool], ...] = ()
    pieces: tuple[PieceId, ...] = ()
    squares: tuple[SquareRef, ...] = ()
    moves: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def line_consequences(board: chess.Board, pv: tuple[str, ...], deltas: tuple[MoveDelta, ...]) -> tuple[LineConsequence, ...]:
    """Describe only facts witnessed while legally replaying a PV."""
    if len(pv) != len(deltas):
        raise ValueError("principal variation and move deltas must have equal length")
    replay = board.copy(stack=True)
    result: list[LineConsequence] = []
    previous_destination: chess.Square | None = None
    for ply, (uci, delta) in enumerate(zip(pv, deltas), 1):
        move = chess.Move.from_uci(uci)
        if move not in replay.legal_moves:
            raise ValueError("principal variation contains an illegal move")
        san = replay.san(move)
        captured_placement = delta.captured
        capture_square = chess.parse_square(captured_placement.square) if captured_placement else None
        mover_before = delta.moved.before
        captured_value = _VALUES.get(chess.PIECE_NAMES.index(captured_placement.piece_type), 0) if captured_placement else 0
        promotion_gain = _VALUES.get(chess.PIECE_NAMES.index(delta.moved.after.piece_type), 0) - _VALUES.get(chess.PIECE_NAMES.index(mover_before.piece_type), 0)
        white_delta = (captured_value + promotion_gain) * (1 if mover_before.color == "white" else -1)
        result.append(LineConsequence(
            ply=ply,
            position_id=delta.before,
            uci=uci,
            san=san,
            mover=mover_before.piece_id,
            source=SquareRef(delta.before, mover_before.square),
            target=SquareRef(delta.after, delta.moved.after.square),
            mover_color=mover_before.color,
            mover_piece_type=mover_before.piece_type,
            gives_check=delta.gives_check,
            capture=captured_placement.piece_id if captured_placement else None,
            capture_square=SquareRef(delta.before, captured_placement.square) if captured_placement else None,
            captured_color=captured_placement.color if captured_placement else None,
            captured_piece_type=captured_placement.piece_type if captured_placement else None,
            recapture=capture_square is not None and capture_square == previous_destination,
            promotion=delta.moved.after.piece_type if delta.promoted else None,
            material_delta_white=white_delta,
            checked_king=delta.checked_king,
            checked_king_square=delta.checked_king_square,
            checkers=delta.checkers,
            checker_squares=delta.checker_squares,
        ))
        previous_destination = move.to_square
        replay.push(move)
    return tuple(result)
