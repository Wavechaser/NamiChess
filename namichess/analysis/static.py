"""Identity-bearing geometric facts for a selected chess position."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from namichess.domain.models import PieceId, PiecePlacement, PositionContext, PositionId, SquareRef
from namichess.domain.position import replay_position


@dataclass(frozen=True, slots=True)
class Attack:
    attacker: PieceId
    source: SquareRef
    target: SquareRef


@dataclass(frozen=True, slots=True)
class LegalMove:
    uci: str
    mover: PieceId
    source: SquareRef
    target: SquareRef
    captured: PieceId | None
    promotion: str | None
    castling_rook: PieceId | None


@dataclass(frozen=True, slots=True)
class AbsolutePin:
    piece: PieceId
    king: PieceId
    ray: tuple[SquareRef, ...]


@dataclass(frozen=True, slots=True)
class PositionFacts:
    position_id: PositionId
    turn: str
    pieces: tuple[PiecePlacement, ...]
    attacks: tuple[Attack, ...]
    legal_moves: tuple[LegalMove, ...]
    pins: tuple[AbsolutePin, ...]
    checked_king: PieceId | None
    checkers: tuple[PieceId, ...]


@dataclass(frozen=True, slots=True)
class PlacementChange:
    piece: PieceId
    before: PiecePlacement
    after: PiecePlacement


@dataclass(frozen=True, slots=True)
class MoveDelta:
    uci: str
    before: PositionId
    after: PositionId
    moved: PlacementChange
    captured: PiecePlacement | None
    castling_rook: PlacementChange | None
    promoted: bool
    attacks_added: tuple[Attack, ...]
    attacks_removed: tuple[Attack, ...]
    slider_attacks_added: tuple[Attack, ...]
    slider_attacks_removed: tuple[Attack, ...]
    pins_added: tuple[AbsolutePin, ...]
    pins_removed: tuple[AbsolutePin, ...]
    gives_check: bool


_SLIDERS = {"bishop", "rook", "queen"}


def position_id(context: PositionContext) -> PositionId:
    return context.position_id


def position_facts(context: PositionContext) -> PositionFacts:
    board, placements = replay_position(context)
    pid = position_id(context)
    by_square = {chess.parse_square(item.square): item for item in placements}

    attacks = tuple(
        Attack(
            attacker=by_square[source].piece_id,
            source=SquareRef(pid, chess.square_name(source)),
            target=SquareRef(pid, chess.square_name(target)),
        )
        for source in sorted(board.piece_map())
        for target in sorted(board.attacks(source))
    )
    legal_moves = tuple(_legal_move(board, move, by_square, pid) for move in board.legal_moves)
    pins = tuple(
        AbsolutePin(
            piece=placement.piece_id,
            king=by_square[board.king(color)].piece_id,
            ray=tuple(
                SquareRef(pid, chess.square_name(square))
                for square in sorted(board.pin(color, square))
            ),
        )
        for color in (chess.WHITE, chess.BLACK)
        for square, placement in sorted(by_square.items())
        if board.color_at(square) == color and board.piece_type_at(square) != chess.KING
        if board.is_pinned(color, square)
    )
    king_square = board.king(board.turn)
    checkers = tuple(by_square[square].piece_id for square in sorted(board.checkers()))
    return PositionFacts(
        position_id=pid,
        turn=_color_name(board.turn),
        pieces=placements,
        attacks=attacks,
        legal_moves=legal_moves,
        pins=pins,
        checked_king=by_square[king_square].piece_id if board.is_check() and king_square is not None else None,
        checkers=checkers,
    )


def move_delta(before_context: PositionContext, after_context: PositionContext) -> MoveDelta:
    """Compare contexts separated by exactly one legal move."""
    if after_context.moves[:-1] != before_context.moves or len(after_context.moves) != len(before_context.moves) + 1:
        raise ValueError("after context must extend before context by exactly one move")
    if (before_context.document_id, before_context.game_number) != (
        after_context.document_id,
        after_context.game_number,
    ):
        raise ValueError("contexts must belong to the same game")
    if before_context.starting_fen != after_context.starting_fen:
        raise ValueError("contexts must have the same root position")

    before = position_facts(before_context)
    after = position_facts(after_context)
    uci = after_context.moves[-1]
    legal = next((item for item in before.legal_moves if item.uci == uci), None)
    if legal is None:
        raise ValueError(f"move {uci!r} is not legal in the before position")

    before_by_id = {item.piece_id: item for item in before.pieces}
    after_by_id = {item.piece_id: item for item in after.pieces}
    moved = PlacementChange(legal.mover, before_by_id[legal.mover], after_by_id[legal.mover])
    rook_change = None
    if legal.castling_rook is not None:
        rook_change = PlacementChange(
            legal.castling_rook,
            before_by_id[legal.castling_rook],
            after_by_id[legal.castling_rook],
        )

    added, removed = _attack_changes(before.attacks, after.attacks)
    before_types = {item.piece_id: item.piece_type for item in before.pieces}
    after_types = {item.piece_id: item.piece_type for item in after.pieces}
    return MoveDelta(
        uci=uci,
        before=before.position_id,
        after=after.position_id,
        moved=moved,
        captured=before_by_id.get(legal.captured) if legal.captured is not None else None,
        castling_rook=rook_change,
        promoted=moved.before.piece_type != moved.after.piece_type,
        attacks_added=added,
        attacks_removed=removed,
        slider_attacks_added=tuple(a for a in added if after_types[a.attacker] in _SLIDERS),
        slider_attacks_removed=tuple(a for a in removed if before_types[a.attacker] in _SLIDERS),
        pins_added=_pin_difference(after.pins, before.pins),
        pins_removed=_pin_difference(before.pins, after.pins),
        gives_check=after.checked_king is not None,
    )


def _legal_move(
    board: chess.Board,
    move: chess.Move,
    by_square: dict[chess.Square, PiecePlacement],
    pid: PositionId,
) -> LegalMove:
    capture_square = move.to_square
    if board.is_en_passant(move):
        capture_square += -8 if board.turn == chess.WHITE else 8
    captured = by_square.get(capture_square)
    castling_rook = None
    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        rook_square = chess.square(7 if move.to_square > move.from_square else 0, rank)
        castling_rook = by_square[rook_square].piece_id
    return LegalMove(
        uci=move.uci(),
        mover=by_square[move.from_square].piece_id,
        source=SquareRef(pid, chess.square_name(move.from_square)),
        target=SquareRef(pid, chess.square_name(move.to_square)),
        captured=captured.piece_id if captured else None,
        promotion=chess.piece_name(move.promotion) if move.promotion is not None else None,
        castling_rook=castling_rook,
    )


def _attack_changes(before: tuple[Attack, ...], after: tuple[Attack, ...]) -> tuple[tuple[Attack, ...], tuple[Attack, ...]]:
    def key(attack: Attack) -> tuple[PieceId, str]:
        return attack.attacker, attack.target.square

    before_keys = {key(attack): attack for attack in before}
    after_keys = {key(attack): attack for attack in after}
    added = tuple(after_keys[item] for item in sorted(after_keys.keys() - before_keys.keys(), key=_attack_key))
    removed = tuple(before_keys[item] for item in sorted(before_keys.keys() - after_keys.keys(), key=_attack_key))
    return added, removed


def _attack_key(item: tuple[PieceId, str]) -> tuple[str, str, str]:
    piece, square = item
    return piece.color, piece.origin_square, square


def _pin_difference(left: tuple[AbsolutePin, ...], right: tuple[AbsolutePin, ...]) -> tuple[AbsolutePin, ...]:
    def key(pin: AbsolutePin) -> tuple[PieceId, tuple[str, ...]]:
        return pin.piece, tuple(square.square for square in pin.ray)

    right_keys = {key(pin) for pin in right}
    return tuple(pin for pin in left if key(pin) not in right_keys)


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"
