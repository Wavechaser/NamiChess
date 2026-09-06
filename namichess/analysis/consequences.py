"""Typed, source-linked consequences derived from one static move delta."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from namichess.analysis.static import ContactKind, MoveDelta
from namichess.domain.models import PieceId, PiecePlacement, PositionId, SquareRef


class ConsequenceKind(str, Enum):
    CAPTURE = "capture"
    PROMOTION = "promotion"
    CASTLING = "castling"
    CHECK = "check"
    LOST_DEFENSE = "lost_defense"
    PINNED = "pinned"
    UNPINNED = "unpinned"
    OPENED_LINE = "opened_line"
    BLOCKED_LINE = "blocked_line"
    GAINED_CONTROL = "gained_control"
    LOST_CONTROL = "lost_control"


class RawFactKind(str, Enum):
    MOVED = "moved"
    CAPTURED = "captured"
    CASTLING_ROOK = "castling_rook"
    PROMOTED = "promoted"
    CHECK = "check"
    ATTACK_ADDED = "attacks_added"
    ATTACK_REMOVED = "attacks_removed"
    CONTACT_ADDED = "contacts_added"
    CONTACT_REMOVED = "contacts_removed"
    UNDEFENDED_ADDED = "geometrically_undefended_added"
    LATENT_RAY_ADDED = "latent_rays_added"
    LATENT_RAY_REMOVED = "latent_rays_removed"
    PIN_ADDED = "pins_added"
    PIN_REMOVED = "pins_removed"


@dataclass(frozen=True, slots=True)
class RawFactRef:
    """Reference to one retained field or tuple item on the source MoveDelta."""

    before: PositionId
    after: PositionId
    uci: str
    kind: RawFactKind
    index: int | None = None


@dataclass(frozen=True, slots=True)
class MoveConsequence:
    kind: ConsequenceKind
    actor: PieceId | None
    subject: PieceId | None
    source: SquareRef | None
    target: SquareRef | None
    related_piece: PieceId | None
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class MoveAccount:
    before: PositionId
    after: PositionId
    uci: str
    consequences: tuple[MoveConsequence, ...]
    omitted_count: int


def move_account(delta: MoveDelta, *, max_consequences: int = 3) -> MoveAccount:
    """Group and select deterministic consequences without adding tactical claims."""
    if max_consequences < 0:
        raise ValueError("max_consequences must be nonnegative")
    consequences = _derive(delta)
    selected = consequences[:max_consequences]
    return MoveAccount(
        before=delta.before,
        after=delta.after,
        uci=delta.uci,
        consequences=selected,
        omitted_count=len(consequences) - len(selected),
    )


def resolve_raw_fact(delta: MoveDelta, reference: RawFactRef) -> object:
    """Resolve one consequence source against its retained move delta."""
    if (reference.before, reference.after, reference.uci) != (delta.before, delta.after, delta.uci):
        raise ValueError("raw fact reference belongs to a different move delta")
    fields = {
        RawFactKind.MOVED: delta.moved,
        RawFactKind.CAPTURED: delta.captured,
        RawFactKind.CASTLING_ROOK: delta.castling_rook,
        RawFactKind.PROMOTED: delta.promoted,
        RawFactKind.CHECK: delta.gives_check,
        RawFactKind.ATTACK_ADDED: delta.attacks_added,
        RawFactKind.ATTACK_REMOVED: delta.attacks_removed,
        RawFactKind.CONTACT_ADDED: delta.contacts_added,
        RawFactKind.CONTACT_REMOVED: delta.contacts_removed,
        RawFactKind.UNDEFENDED_ADDED: delta.geometrically_undefended_added,
        RawFactKind.LATENT_RAY_ADDED: delta.latent_rays_added,
        RawFactKind.LATENT_RAY_REMOVED: delta.latent_rays_removed,
        RawFactKind.PIN_ADDED: delta.pins_added,
        RawFactKind.PIN_REMOVED: delta.pins_removed,
    }
    value = fields[reference.kind]
    if reference.index is None:
        return value
    if not isinstance(value, tuple):
        raise ValueError("scalar raw fact references cannot have an index")
    if reference.index < 0:
        raise ValueError("raw fact reference index is out of range")
    try:
        return value[reference.index]
    except IndexError as exc:
        raise ValueError("raw fact reference index is out of range") from exc


def _derive(delta: MoveDelta) -> tuple[MoveConsequence, ...]:
    result: list[MoveConsequence] = []
    moved = delta.moved.piece
    captured = delta.captured.piece_id if delta.captured is not None else None

    if delta.captured is not None:
        result.append(_event(
            ConsequenceKind.CAPTURE, moved, captured, SquareRef(delta.before, delta.moved.before.square),
            SquareRef(delta.before, delta.captured.square), None,
            _ref(delta, RawFactKind.MOVED), _ref(delta, RawFactKind.CAPTURED),
        ))
    if delta.promoted:
        result.append(_event(
            ConsequenceKind.PROMOTION, moved, moved, SquareRef(delta.before, delta.moved.before.square),
            SquareRef(delta.after, delta.moved.after.square), None,
            _ref(delta, RawFactKind.MOVED), _ref(delta, RawFactKind.PROMOTED),
        ))
    if delta.castling_rook is not None:
        result.append(_event(
            ConsequenceKind.CASTLING, moved, delta.castling_rook.piece,
            SquareRef(delta.before, delta.moved.before.square), SquareRef(delta.after, delta.moved.after.square),
            delta.castling_rook.piece,
            _ref(delta, RawFactKind.MOVED), _ref(delta, RawFactKind.CASTLING_ROOK),
        ))
    if delta.gives_check:
        result.append(_event(
            ConsequenceKind.CHECK, None, None, None, None,
            None, _ref(delta, RawFactKind.CHECK),
        ))

    added_relationships = {
        (item.controller, item.subject, item.kind) for item in delta.contacts_added
    }
    removed_relationships = {
        (item.controller, item.subject, item.kind) for item in delta.contacts_removed
    }
    undefended = {
        item.piece: index for index, item in enumerate(delta.geometrically_undefended_added)
    }
    consumed_removed_contacts: set[int] = set()
    consumed_added_contacts: set[int] = set()

    lost_defenders: dict[PieceId, list[tuple[int, object]]] = {}
    for index, contact in enumerate(delta.contacts_removed):
        relationship = (contact.controller, contact.subject, contact.kind)
        if contact.kind is ContactKind.DEFEND and contact.subject != captured and relationship not in added_relationships and contact.subject in undefended:
            consumed_removed_contacts.add(index)
            lost_defenders.setdefault(contact.subject, []).append((index, contact))
    for subject, entries in lost_defenders.items():
        contacts = [contact for _, contact in entries]
        result.append(_event(
            ConsequenceKind.LOST_DEFENSE,
            contacts[0].controller if len(contacts) == 1 else None,
            subject,
            contacts[0].controller_square if len(contacts) == 1 else None,
            delta.geometrically_undefended_added[undefended[subject]].square,
            None,
            *(_ref(delta, RawFactKind.CONTACT_REMOVED, index) for index, _ in entries),
            _ref(delta, RawFactKind.UNDEFENDED_ADDED, undefended[subject]),
        ))

    removed_pin_pieces = {item.piece for item in delta.pins_removed}
    added_pin_pieces = {item.piece for item in delta.pins_added}
    for index, pin in enumerate(delta.pins_added):
        if pin.piece not in removed_pin_pieces:
            result.append(_event(
                ConsequenceKind.PINNED, None, pin.piece, None,
                _placement_square(delta.after, delta.after_pieces, pin.piece),
                pin.king, _ref(delta, RawFactKind.PIN_ADDED, index),
            ))
    after_ids = {item.piece_id for item in delta.after_pieces}
    for index, pin in enumerate(delta.pins_removed):
        if pin.piece not in added_pin_pieces and pin.piece in after_ids:
            result.append(_event(
                ConsequenceKind.UNPINNED, None, pin.piece, None,
                _placement_square(delta.after, delta.after_pieces, pin.piece),
                pin.king, _ref(delta, RawFactKind.PIN_REMOVED, index),
            ))

    for ray_index, ray in enumerate(delta.latent_rays_removed):
        if ray.blocker not in (moved, captured) or ray.target is None or ray.slider == moved:
            continue
        contact_index = next((
            index for index, contact in enumerate(delta.contacts_added)
            if contact.controller == ray.slider and contact.subject == ray.target
        ), None)
        if contact_index is None:
            continue
        consumed_added_contacts.add(contact_index)
        opened_facts = (
            _ref(delta, RawFactKind.LATENT_RAY_REMOVED, ray_index),
            _ref(delta, RawFactKind.CONTACT_ADDED, contact_index),
        )
        pin_index = next((
            index for index, event in enumerate(result)
            if event.kind is ConsequenceKind.PINNED and event.subject == ray.target
            and any(
                pin.piece == ray.target
                and ray.source.square in {square.square for square in pin.ray}
                for pin in delta.pins_added
            )
        ), None)
        if pin_index is not None:
            result[pin_index] = replace(
                result[pin_index],
                supporting_facts=tuple(dict.fromkeys((*result[pin_index].supporting_facts, *opened_facts))),
            )
            continue
        result.append(_event(
            ConsequenceKind.OPENED_LINE, ray.slider, ray.target, ray.source,
            delta.contacts_added[contact_index].subject_square, ray.blocker,
            *opened_facts,
        ))

    for ray_index, ray in enumerate(delta.latent_rays_added):
        if ray.blocker != moved or ray.target is None:
            continue
        contact_index = next((
            index for index, contact in enumerate(delta.contacts_removed)
            if contact.controller == ray.slider and contact.subject == ray.target
            and contact.subject != captured
        ), None)
        if contact_index is None or contact_index in consumed_removed_contacts:
            continue
        consumed_removed_contacts.add(contact_index)
        result.append(_event(
            ConsequenceKind.BLOCKED_LINE, ray.slider, ray.target, ray.source,
            delta.contacts_removed[contact_index].subject_square, ray.blocker,
            _ref(delta, RawFactKind.LATENT_RAY_ADDED, ray_index),
            _ref(delta, RawFactKind.CONTACT_REMOVED, contact_index),
        ))

    for index, contact in enumerate(delta.contacts_added):
        relationship = (contact.controller, contact.subject, contact.kind)
        if index in consumed_added_contacts or relationship in removed_relationships:
            continue
        result.append(_event(
            ConsequenceKind.GAINED_CONTROL, contact.controller, contact.subject,
            contact.controller_square, contact.subject_square, None,
            _ref(delta, RawFactKind.CONTACT_ADDED, index),
        ))
        consumed_added_contacts.add(index)
    for index, contact in enumerate(delta.contacts_removed):
        relationship = (contact.controller, contact.subject, contact.kind)
        if (
            index in consumed_removed_contacts or contact.subject == captured
            or relationship in added_relationships
        ):
            continue
        result.append(_event(
            ConsequenceKind.LOST_CONTROL, contact.controller, contact.subject,
            contact.controller_square, contact.subject_square, None,
            _ref(delta, RawFactKind.CONTACT_REMOVED, index),
        ))

    occupied_after = {item.square for item in delta.after_pieces}
    for index, attack in enumerate(delta.attacks_added):
        if attack.attacker != moved or attack.target.square in occupied_after:
            continue
        result.append(_event(
            ConsequenceKind.GAINED_CONTROL, moved, None, attack.source, attack.target,
            None, _ref(delta, RawFactKind.ATTACK_ADDED, index),
        ))
        break

    priority = {
        ConsequenceKind.CHECK: 0,
        ConsequenceKind.LOST_DEFENSE: 1,
        ConsequenceKind.PINNED: 2,
        ConsequenceKind.OPENED_LINE: 3,
        ConsequenceKind.PROMOTION: 4,
        ConsequenceKind.CAPTURE: 5,
        ConsequenceKind.CASTLING: 6,
        ConsequenceKind.UNPINNED: 7,
        ConsequenceKind.BLOCKED_LINE: 8,
        ConsequenceKind.GAINED_CONTROL: 9,
        ConsequenceKind.LOST_CONTROL: 10,
    }
    return tuple(sorted(result, key=lambda item: priority[item.kind]))


def _event(
    kind: ConsequenceKind,
    actor: PieceId | None,
    subject: PieceId | None,
    source: SquareRef | None,
    target: SquareRef | None,
    related_piece: PieceId | None,
    *supporting_facts: RawFactRef,
) -> MoveConsequence:
    return MoveConsequence(
        kind, actor, subject, source, target, related_piece,
        tuple(dict.fromkeys(supporting_facts)),
    )


def _placement_square(
    position_id: PositionId, placements: tuple[PiecePlacement, ...], piece: PieceId,
) -> SquareRef:
    placement = next(item for item in placements if item.piece_id == piece)
    return SquareRef(position_id, placement.square)


def _ref(delta: MoveDelta, kind: RawFactKind, index: int | None = None) -> RawFactRef:
    return RawFactRef(delta.before, delta.after, delta.uci, kind, index)
