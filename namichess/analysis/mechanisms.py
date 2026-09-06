"""Bounded structural mechanisms observed immediately after one move."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from namichess.analysis.consequences import (
    RawFactKind,
    RawFactRef,
    _opened_line_facts,
)
from namichess.analysis.static import ContactKind, MoveDelta, PieceContact, PositionFacts
from namichess.domain.models import PieceId, PositionId, SquareRef


class CheckKind(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"


class CheckerRole(str, Enum):
    DIRECT = "direct"
    DISCOVERED = "discovered"


@dataclass(frozen=True, slots=True)
class Checker:
    piece: PieceId
    square: SquareRef
    role: CheckerRole
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class CheckMechanism:
    kind: CheckKind
    checked_king: PieceId
    king_square: SquareRef
    checkers: tuple[Checker, ...]
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class MechanismAttack:
    actor: PieceId
    actor_square: SquareRef
    target: PieceId
    target_square: SquareRef
    contact: PieceContact
    established_by_move: bool
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class StructuralFork:
    actor: PieceId
    actor_square: SquareRef
    targets: tuple[MechanismAttack, ...]
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class MoveMechanisms:
    before: PositionId
    after: PositionId
    uci: str
    check: CheckMechanism | None
    attacks: tuple[MechanismAttack, ...]
    forks: tuple[StructuralFork, ...]


def move_mechanisms(
    delta: MoveDelta,
    after: PositionFacts,
) -> MoveMechanisms:
    """Project checks and multi-target geometry without claiming tactical wins."""
    if (
        after.position_id != delta.after
    ):
        raise ValueError("mechanism inputs must describe the same resulting move")

    added_indexes = {
        (contact.controller, contact.subject, contact.kind): index
        for index, contact in enumerate(delta.contacts_added)
    }
    attacks_by_actor: dict[PieceId, list[MechanismAttack]] = {}
    new_nonking_attacks: list[MechanismAttack] = []
    for contact in after.contacts:
        if contact.kind is not ContactKind.ATTACK:
            continue
        target_is_king = contact.subject.original_piece_type == "king"
        if target_is_king and contact.subject != delta.checked_king:
            continue
        index = added_indexes.get((contact.controller, contact.subject, contact.kind))
        sources = (
            (_ref(delta, RawFactKind.CONTACT_ADDED, index),)
            if index is not None else ()
        )
        attack = MechanismAttack(
            contact.controller,
            contact.controller_square,
            contact.subject,
            contact.subject_square,
            contact,
            index is not None,
            sources,
        )
        attacks_by_actor.setdefault(contact.controller, []).append(attack)
        if index is not None and not target_is_king:
            new_nonking_attacks.append(attack)

    check = _check_mechanism(delta, attacks_by_actor)
    forks = []
    for actor, targets in attacks_by_actor.items():
        if len(targets) < 2 or not any(target.established_by_move for target in targets):
            continue
        targets.sort(key=lambda item: (
            item.target != delta.checked_king,
            _piece_key(item.target),
        ))
        sources = tuple(
            source
            for target in targets
            for source in target.supporting_facts
        )
        forks.append(StructuralFork(
            actor,
            targets[0].actor_square,
            tuple(targets),
            tuple(dict.fromkeys(sources)),
        ))

    new_nonking_attacks.sort(key=lambda item: (
        item.actor.color != delta.moved.piece.color,
        _piece_key(item.actor),
        _piece_key(item.target),
    ))
    forks.sort(key=lambda item: (
        item.actor.color != delta.moved.piece.color,
        not any(target.target == delta.checked_king for target in item.targets),
        _piece_key(item.actor),
        tuple(_piece_key(target.target) for target in item.targets),
    ))

    return MoveMechanisms(
        delta.before,
        delta.after,
        delta.uci,
        check,
        tuple(new_nonking_attacks),
        tuple(forks),
    )


def _check_mechanism(
    delta: MoveDelta,
    attacks_by_actor: dict[PieceId, list[MechanismAttack]],
) -> CheckMechanism | None:
    if delta.checked_king is None or delta.checked_king_square is None or not delta.checkers:
        return None
    moved_pieces = {delta.moved.piece}
    if delta.castling_rook is not None:
        moved_pieces.add(delta.castling_rook.piece)
    square_by_checker = dict(zip(delta.checkers, delta.checker_squares, strict=True))
    checkers = []
    for piece in delta.checkers:
        role = CheckerRole.DIRECT if piece in moved_pieces else CheckerRole.DISCOVERED
        sources = [
            source
            for attack in attacks_by_actor.get(piece, ())
            if attack.target == delta.checked_king
            for source in attack.supporting_facts
        ]
        if role is CheckerRole.DIRECT:
            sources.append(_ref(
                delta,
                RawFactKind.CASTLING_ROOK
                if delta.castling_rook is not None and piece == delta.castling_rook.piece
                else RawFactKind.MOVED,
            ))
        else:
            sources.extend(_opened_line_sources(delta, piece, delta.checked_king))
        checkers.append(Checker(
            piece,
            square_by_checker[piece],
            role,
            tuple(dict.fromkeys(sources)),
        ))
    check_ref = _ref(delta, RawFactKind.CHECK)
    return CheckMechanism(
        CheckKind.DOUBLE if len(checkers) > 1 else CheckKind.SINGLE,
        delta.checked_king,
        delta.checked_king_square,
        tuple(checkers),
        (check_ref,),
    )


def _opened_line_sources(
    delta: MoveDelta,
    checker: PieceId,
    king: PieceId,
) -> tuple[RawFactRef, ...]:
    contact_index = next((
        index for index, contact in enumerate(delta.contacts_added)
        if contact.controller == checker and contact.subject == king
    ), None)
    if contact_index is None:
        return ()
    opened = _opened_line_facts(delta, contact_index)
    return opened[1] if opened is not None else ()


def _ref(delta: MoveDelta, kind: RawFactKind, index: int | None = None) -> RawFactRef:
    return RawFactRef(delta.before, delta.after, delta.uci, kind, index)


def _piece_key(piece: PieceId) -> tuple[str, str, str]:
    return piece.color, piece.origin_square, piece.original_piece_type
