"""Identity-bearing geometric facts for a selected chess position."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import chess

from namichess.domain.models import PieceId, PiecePlacement, PositionContext, PositionId, SquareRef
from namichess.domain.position import replay_position


@dataclass(frozen=True, slots=True)
class Attack:
    attacker: PieceId
    source: SquareRef
    target: SquareRef


class ContactKind(str, Enum):
    ATTACK = "attack"
    DEFEND = "defend"


@dataclass(frozen=True, slots=True)
class PieceContact:
    controller: PieceId
    controller_square: SquareRef
    subject: PieceId
    subject_square: SquareRef
    kind: ContactKind


@dataclass(frozen=True, slots=True)
class GeometricallyUndefended:
    piece: PieceId
    square: SquareRef
    attackers: tuple[PieceId, ...]


@dataclass(frozen=True, slots=True)
class LatentRay:
    slider: PieceId
    source: SquareRef
    direction: str
    blocker: PieceId
    blocker_square: SquareRef
    beyond: tuple[SquareRef, ...]
    target: PieceId | None


@dataclass(frozen=True, slots=True)
class LegalMove:
    uci: str
    san: str
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
    contacts: tuple[PieceContact, ...]
    geometrically_undefended: tuple[GeometricallyUndefended, ...]
    latent_rays: tuple[LatentRay, ...]
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
    san: str
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
    contacts_added: tuple[PieceContact, ...]
    contacts_removed: tuple[PieceContact, ...]
    geometrically_undefended_added: tuple[GeometricallyUndefended, ...]
    geometrically_undefended_removed: tuple[GeometricallyUndefended, ...]
    latent_rays_added: tuple[LatentRay, ...]
    latent_rays_removed: tuple[LatentRay, ...]
    pins_added: tuple[AbsolutePin, ...]
    pins_removed: tuple[AbsolutePin, ...]
    gives_check: bool
    before_pieces: tuple[PiecePlacement, ...]
    after_pieces: tuple[PiecePlacement, ...]


_SLIDERS = {"bishop", "rook", "queen"}
_RAY_DIRECTIONS = (
    ("n", 0, 1),
    ("ne", 1, 1),
    ("e", 1, 0),
    ("se", 1, -1),
    ("s", 0, -1),
    ("sw", -1, -1),
    ("w", -1, 0),
    ("nw", -1, 1),
)


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
    contacts = _piece_contacts(attacks, by_square)
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
        contacts=contacts,
        geometrically_undefended=_geometrically_undefended(placements, contacts, pid),
        latent_rays=_latent_rays(board, by_square, pid),
        legal_moves=legal_moves,
        pins=pins,
        checked_king=by_square[king_square].piece_id if board.is_check() and king_square is not None else None,
        checkers=checkers,
    )


def move_delta(before_context: PositionContext, after_context: PositionContext) -> MoveDelta:
    """Compare contexts separated by exactly one legal move."""
    _validate_delta_contexts(before_context, after_context)
    return _move_delta_from_facts(
        before_context,
        after_context,
        position_facts(before_context),
        position_facts(after_context),
    )


def _move_delta_from_facts(
    before_context: PositionContext,
    after_context: PositionContext,
    before: PositionFacts,
    after: PositionFacts,
) -> MoveDelta:
    """Assemble a one-move delta from trusted facts computed for these exact contexts."""
    _validate_delta_contexts(before_context, after_context)
    if before.position_id != before_context.position_id or after.position_id != after_context.position_id:
        raise ValueError("position facts must belong to the supplied contexts")

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
    contacts_added, contacts_removed = _fact_changes(before.contacts, after.contacts, _contact_key)
    undefended_added, undefended_removed = _fact_changes(
        before.geometrically_undefended,
        after.geometrically_undefended,
        lambda item: item.piece,
    )
    rays_added, rays_removed = _fact_changes(before.latent_rays, after.latent_rays, _latent_ray_key)
    before_types = {item.piece_id: item.piece_type for item in before.pieces}
    after_types = {item.piece_id: item.piece_type for item in after.pieces}
    return MoveDelta(
        uci=uci,
        san=legal.san,
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
        contacts_added=contacts_added,
        contacts_removed=contacts_removed,
        geometrically_undefended_added=undefended_added,
        geometrically_undefended_removed=undefended_removed,
        latent_rays_added=rays_added,
        latent_rays_removed=rays_removed,
        pins_added=_pin_difference(after.pins, before.pins),
        pins_removed=_pin_difference(before.pins, after.pins),
        gives_check=after.checked_king is not None,
        before_pieces=before.pieces,
        after_pieces=after.pieces,
    )


def _validate_delta_contexts(before_context: PositionContext, after_context: PositionContext) -> None:
    if after_context.moves[:-1] != before_context.moves or len(after_context.moves) != len(before_context.moves) + 1:
        raise ValueError("after context must extend before context by exactly one move")
    if (before_context.document_id, before_context.game_number) != (
        after_context.document_id,
        after_context.game_number,
    ):
        raise ValueError("contexts must belong to the same game")
    if before_context.starting_fen != after_context.starting_fen:
        raise ValueError("contexts must have the same root position")


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
        san=board.san(move),
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


def _piece_contacts(
    attacks: tuple[Attack, ...],
    by_square: dict[chess.Square, PiecePlacement],
) -> tuple[PieceContact, ...]:
    placements = {item.square: item for item in by_square.values()}
    result = []
    for attack in attacks:
        subject = placements.get(attack.target.square)
        if subject is None:
            continue
        result.append(
            PieceContact(
                controller=attack.attacker,
                controller_square=attack.source,
                subject=subject.piece_id,
                subject_square=attack.target,
                kind=ContactKind.DEFEND if attack.attacker.color == subject.color else ContactKind.ATTACK,
            )
        )
    return tuple(result)


def _geometrically_undefended(
    placements: tuple[PiecePlacement, ...],
    contacts: tuple[PieceContact, ...],
    pid: PositionId,
) -> tuple[GeometricallyUndefended, ...]:
    defended = {contact.subject for contact in contacts if contact.kind == ContactKind.DEFEND}
    attackers: dict[PieceId, list[PieceId]] = {}
    for contact in contacts:
        if contact.kind == ContactKind.ATTACK:
            attackers.setdefault(contact.subject, []).append(contact.controller)
    return tuple(
        GeometricallyUndefended(
            piece=item.piece_id,
            square=SquareRef(pid, item.square),
            attackers=tuple(sorted(attackers.get(item.piece_id, ()), key=_piece_key)),
        )
        for item in placements
        if item.piece_type != "king" and item.piece_id not in defended
    )


def _latent_rays(
    board: chess.Board,
    by_square: dict[chess.Square, PiecePlacement],
    pid: PositionId,
) -> tuple[LatentRay, ...]:
    result = []
    for source, placement in sorted(by_square.items()):
        directions = _slider_directions(placement.piece_type)
        for name, file_step, rank_step in directions:
            squares = _squares_in_direction(source, file_step, rank_step)
            blocker_index = next((index for index, square in enumerate(squares) if board.piece_at(square)), None)
            if blocker_index is None or blocker_index + 1 >= len(squares):
                continue
            blocker_square = squares[blocker_index]
            beyond = []
            target = None
            for square in squares[blocker_index + 1 :]:
                beyond.append(SquareRef(pid, chess.square_name(square)))
                if square in by_square:
                    target = by_square[square].piece_id
                    break
            result.append(
                LatentRay(
                    slider=placement.piece_id,
                    source=SquareRef(pid, chess.square_name(source)),
                    direction=name,
                    blocker=by_square[blocker_square].piece_id,
                    blocker_square=SquareRef(pid, chess.square_name(blocker_square)),
                    beyond=tuple(beyond),
                    target=target,
                )
            )
    return tuple(result)


def _slider_directions(piece_type: str) -> tuple[tuple[str, int, int], ...]:
    if piece_type == "bishop":
        return tuple(item for item in _RAY_DIRECTIONS if item[1] and item[2])
    if piece_type == "rook":
        return tuple(item for item in _RAY_DIRECTIONS if not item[1] or not item[2])
    if piece_type == "queen":
        return _RAY_DIRECTIONS
    return ()


def _squares_in_direction(source: chess.Square, file_step: int, rank_step: int) -> tuple[chess.Square, ...]:
    file_index = chess.square_file(source) + file_step
    rank_index = chess.square_rank(source) + rank_step
    result = []
    while 0 <= file_index < 8 and 0 <= rank_index < 8:
        result.append(chess.square(file_index, rank_index))
        file_index += file_step
        rank_index += rank_step
    return tuple(result)


def _piece_key(piece: PieceId) -> tuple[str, str]:
    return piece.color, piece.origin_square


def _contact_key(contact: PieceContact) -> tuple[PieceId, PieceId, ContactKind]:
    return contact.controller, contact.subject, contact.kind


def _latent_ray_key(ray: LatentRay) -> tuple[object, ...]:
    return (
        ray.slider,
        ray.source.square,
        ray.direction,
        ray.blocker,
        ray.blocker_square.square,
        tuple(square.square for square in ray.beyond),
        ray.target,
    )


def _fact_changes(before, after, key):
    before_keys = {key(item): item for item in before}
    after_keys = {key(item): item for item in after}
    added_keys = after_keys.keys() - before_keys.keys()
    removed_keys = before_keys.keys() - after_keys.keys()
    return (
        tuple(item for item in after if key(item) in added_keys),
        tuple(item for item in before if key(item) in removed_keys),
    )


def _pin_difference(left: tuple[AbsolutePin, ...], right: tuple[AbsolutePin, ...]) -> tuple[AbsolutePin, ...]:
    def key(pin: AbsolutePin) -> tuple[PieceId, tuple[str, ...]]:
        return pin.piece, tuple(square.square for square in pin.ray)

    right_keys = {key(pin) for pin in right}
    return tuple(pin for pin in left if key(pin) not in right_keys)


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"
