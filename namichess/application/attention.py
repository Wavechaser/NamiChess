"""Bounded, interface-neutral attention selection from existing chess facts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from namichess.analysis.consequences import (
    ConsequenceKind,
    MoveAccount,
    RawFactRef,
)
from namichess.analysis.static import ContactKind, PositionFacts
from namichess.domain.models import PieceId, PositionId, SquareRef


class AttentionKind(str, Enum):
    CHECK = "check"
    LOST_DEFENSE_UNDER_ATTACK = "lost_defense_under_attack"
    ATTACKED_UNDEFENDED = "attacked_undefended"
    PINNED = "pinned"
    OPENED_LINE = "opened_line"
    BLOCKED_LINE = "blocked_line"


class PositionFactKind(str, Enum):
    CHECKED_KING = "checked_king"
    GEOMETRICALLY_UNDEFENDED = "geometrically_undefended"
    PIN = "pins"


@dataclass(frozen=True, slots=True)
class PositionFactRef:
    position_id: PositionId
    kind: PositionFactKind
    index: int | None = None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    kind: AttentionKind
    subject: PieceId | None
    square: SquareRef | None
    actor: PieceId | None
    related_piece: PieceId | None
    position_sources: tuple[PositionFactRef, ...] = ()
    move_sources: tuple[RawFactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class AttentionSelection:
    position_id: PositionId
    items: tuple[AttentionItem, ...]
    omitted_count: int


def select_attention(
    facts: PositionFacts,
    account: MoveAccount | None = None,
    *,
    terminal: bool = False,
    max_items: int = 3,
) -> AttentionSelection:
    """Select current geometric concerns and connected move effects."""
    if max_items < 0:
        raise ValueError("max_items must be nonnegative")
    if account is not None and account.after != facts.position_id:
        raise ValueError("move account must end at the supplied position facts")

    items: list[AttentionItem] = []
    if facts.checked_king is not None:
        items.append(AttentionItem(
            AttentionKind.CHECK,
            facts.checked_king,
            _piece_square(facts, facts.checked_king),
            None,
            None,
            (PositionFactRef(facts.position_id, PositionFactKind.CHECKED_KING),),
        ))

    if not terminal:
        if account is not None:
            _append_move_attention(items, facts, account)
        _append_current_attention(items, facts)

    def priority(item: AttentionItem) -> int:
        if item.kind is AttentionKind.PINNED:
            return 3 if item.move_sources else 6
        return {
            AttentionKind.CHECK: 0,
            AttentionKind.LOST_DEFENSE_UNDER_ATTACK: 1,
            AttentionKind.ATTACKED_UNDEFENDED: 2,
            AttentionKind.OPENED_LINE: 4,
            AttentionKind.BLOCKED_LINE: 5,
        }[item.kind]

    items.sort(key=priority)
    selected = tuple(items[:max_items])
    return AttentionSelection(facts.position_id, selected, len(items) - len(selected))


def resolve_position_fact(facts: PositionFacts, reference: PositionFactRef) -> object:
    """Resolve one attention source against its exact current-position facts."""
    if reference.position_id != facts.position_id:
        raise ValueError("position fact reference belongs to a different position")
    values = {
        PositionFactKind.CHECKED_KING: facts.checked_king,
        PositionFactKind.GEOMETRICALLY_UNDEFENDED: facts.geometrically_undefended,
        PositionFactKind.PIN: facts.pins,
    }
    value = values[reference.kind]
    if reference.index is None:
        return value
    if not isinstance(value, tuple) or reference.index < 0:
        raise ValueError("position fact reference index is out of range")
    try:
        return value[reference.index]
    except IndexError as exc:
        raise ValueError("position fact reference index is out of range") from exc


def _append_move_attention(
    items: list[AttentionItem], facts: PositionFacts, account: MoveAccount,
) -> None:
    attacked = {
        contact.subject
        for contact in facts.contacts
        if contact.kind is ContactKind.ATTACK
    }
    for consequence in account.consequences:
        kind = {
            ConsequenceKind.LOST_DEFENSE: AttentionKind.LOST_DEFENSE_UNDER_ATTACK,
            ConsequenceKind.PINNED: AttentionKind.PINNED,
            ConsequenceKind.OPENED_LINE: AttentionKind.OPENED_LINE,
            ConsequenceKind.BLOCKED_LINE: AttentionKind.BLOCKED_LINE,
        }.get(consequence.kind)
        if kind is None:
            continue
        if kind is AttentionKind.LOST_DEFENSE_UNDER_ATTACK and consequence.subject not in attacked:
            continue
        _merge_or_append(items, AttentionItem(
            kind,
            consequence.subject,
            _piece_square(facts, consequence.subject) if consequence.subject is not None else consequence.target,
            consequence.actor,
            consequence.related_piece,
            move_sources=consequence.supporting_facts,
        ))


def _append_current_attention(items: list[AttentionItem], facts: PositionFacts) -> None:
    undefended = [
        (index, item)
        for index, item in enumerate(facts.geometrically_undefended)
        if item.attackers
    ]
    undefended.sort(key=lambda pair: (
        pair[1].piece.color != facts.turn,
        pair[1].piece.color,
        pair[1].piece.origin_square,
    ))
    for index, item in undefended:
        current = AttentionItem(
            AttentionKind.ATTACKED_UNDEFENDED,
            item.piece,
            item.square,
            item.attackers[0] if len(item.attackers) == 1 else None,
            None,
            (PositionFactRef(facts.position_id, PositionFactKind.GEOMETRICALLY_UNDEFENDED, index),),
        )
        lost_index = next((
            position for position, existing in enumerate(items)
            if existing.kind is AttentionKind.LOST_DEFENSE_UNDER_ATTACK
            and existing.subject == item.piece
        ), None)
        if lost_index is not None:
            items[lost_index] = replace(
                items[lost_index],
                position_sources=current.position_sources,
            )
        else:
            _merge_or_append(items, current)

    for index, pin in enumerate(facts.pins):
        current = AttentionItem(
            AttentionKind.PINNED,
            pin.piece,
            _piece_square(facts, pin.piece),
            None,
            pin.king,
            (PositionFactRef(facts.position_id, PositionFactKind.PIN, index),),
        )
        existing_index = next((
            position for position, existing in enumerate(items)
            if existing.kind is AttentionKind.PINNED and existing.subject == pin.piece
        ), None)
        if existing_index is not None:
            items[existing_index] = replace(
                items[existing_index],
                position_sources=current.position_sources,
            )
        else:
            _merge_or_append(items, current)


def _merge_or_append(items: list[AttentionItem], candidate: AttentionItem) -> None:
    index = next((
        position for position, item in enumerate(items)
        if item.kind is candidate.kind and item.subject == candidate.subject
        and item.actor == candidate.actor and item.related_piece == candidate.related_piece
    ), None)
    if index is None:
        items.append(candidate)
        return
    current = items[index]
    items[index] = replace(
        current,
        position_sources=tuple(dict.fromkeys((*current.position_sources, *candidate.position_sources))),
        move_sources=tuple(dict.fromkeys((*current.move_sources, *candidate.move_sources))),
    )


def _piece_square(facts: PositionFacts, piece: PieceId) -> SquareRef:
    placement = next(item for item in facts.pieces if item.piece_id == piece)
    return SquareRef(facts.position_id, placement.square)
