"""Request-scoped structural comparisons for selected candidate roots."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from namichess.analysis.consequences import (
    ConsequenceKind, MoveAccount, RawFactKind, RawFactRef, move_account,
)
from namichess.analysis.continuations import continuation_context
from namichess.analysis.static import (
    ContactKind,
    MoveDelta,
    PositionFacts,
    _move_delta_from_facts,
    position_facts,
)
from namichess.domain.models import PieceId, PositionContext, PositionId, SquareRef
from namichess.domain.position import replay_position


@dataclass(frozen=True, slots=True)
class ContrastingRoot:
    uci: str
    position_id: PositionId


@dataclass(frozen=True, slots=True)
class DefenseChange:
    subject: PieceId
    square: SquareRef
    baseline_defenders: tuple[PieceId, ...]
    after_defenders: tuple[PieceId, ...]
    contrasting_roots: tuple[ContrastingRoot, ...]
    supporting_facts: tuple[RawFactRef, ...]


@dataclass(frozen=True, slots=True)
class RootStructure:
    delta: MoveDelta
    account: MoveAccount
    defense_changes: tuple[DefenseChange, ...]
    omitted_count: int
    omitted_direct_count: int


def build_root_structures(
    context: PositionContext,
    request_id: int,
    roots: tuple[str, ...],
    *,
    max_defense_changes: int = 3,
) -> dict[str, RootStructure]:
    """Compute immutable root structure once for one selected request."""
    if max_defense_changes < 0:
        raise ValueError("max_defense_changes must be nonnegative")
    if len(set(roots)) != len(roots):
        raise ValueError("candidate roots must be distinct")
    if not roots:
        return {}

    board, _ = replay_position(context)
    before = position_facts(context)
    after_by_root: dict[str, tuple[PositionContext, PositionFacts]] = {}
    for uci in roots:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise ValueError(f"candidate root {uci!r} is invalid") from exc
        if move not in board.legal_moves:
            raise ValueError(f"candidate root {uci!r} is not legal")
        after_board = board.copy(stack=True)
        after_board.push(move)
        after_context = continuation_context(
            context, request_id, (*context.moves, uci), after_board,
        )
        after_by_root[uci] = (after_context, position_facts(after_context))

    common = _common_piece_ids(tuple(facts for _, facts in after_by_root.values()))
    baseline = _defenders(before)
    defenders_by_root = {
        uci: _defenders(facts) for uci, (_, facts) in after_by_root.items()
    }
    relevant = tuple(
        piece
        for piece in sorted(common, key=_piece_key)
        if len({defenders_by_root[root].get(piece, ()) for root in roots}) > 1
    )
    baseline_attacked = _attacked(before)
    mover_color = before.turn
    structures: dict[str, RootStructure] = {}
    for uci in roots:
        after_context, after = after_by_root[uci]
        delta = _move_delta_from_facts(context, after_context, before, after)
        own_defenders = defenders_by_root[uci]
        attacked = baseline_attacked | _attacked(after)
        changes = [
            DefenseChange(
                subject=piece,
                square=_piece_square(after, piece),
                baseline_defenders=baseline.get(piece, ()),
                after_defenders=own_defenders.get(piece, ()),
                contrasting_roots=tuple(
                    ContrastingRoot(other, after_by_root[other][0].position_id)
                    for other in roots
                    if defenders_by_root[other].get(piece, ()) != own_defenders.get(piece, ())
                ),
                supporting_facts=_defense_sources(
                    delta, piece, baseline.get(piece, ()), own_defenders.get(piece, ()),
                ),
            )
            for piece in relevant
        ]
        changes.sort(key=lambda item: (
            item.subject not in attacked,
            not (
                item.subject.color == mover_color
                and item.after_defenders != item.baseline_defenders
            ),
            _piece_key(item.subject),
        ))
        selected = tuple(changes[:max_defense_changes])
        account = move_account(delta)
        direct_kinds = {
            ConsequenceKind.CAPTURE, ConsequenceKind.PROMOTION,
            ConsequenceKind.CASTLING, ConsequenceKind.CHECK,
        }
        direct_total = sum((
            delta.captured is not None, delta.promoted,
            delta.castling_rook is not None, delta.gives_check,
        ))
        retained_direct = sum(item.kind in direct_kinds for item in account.consequences)
        structures[uci] = RootStructure(
            delta,
            account,
            selected,
            len(changes) - len(selected),
            direct_total - retained_direct,
        )
    return structures


def _defense_sources(
    delta: MoveDelta,
    subject: PieceId,
    baseline: tuple[PieceId, ...],
    after: tuple[PieceId, ...],
) -> tuple[RawFactRef, ...]:
    baseline_set = set(baseline)
    after_set = set(after)
    sources = [
        RawFactRef(delta.before, delta.after, delta.uci, RawFactKind.CONTACT_ADDED, index)
        for index, contact in enumerate(delta.contacts_added)
        if contact.kind is ContactKind.DEFEND and contact.subject == subject
        and contact.controller in after_set - baseline_set
    ]
    sources.extend(
        RawFactRef(delta.before, delta.after, delta.uci, RawFactKind.CONTACT_REMOVED, index)
        for index, contact in enumerate(delta.contacts_removed)
        if contact.kind is ContactKind.DEFEND and contact.subject == subject
        and contact.controller in baseline_set - after_set
    )
    return tuple(sources)


def _common_piece_ids(facts: tuple[PositionFacts, ...]) -> set[PieceId]:
    if not facts:
        return set()
    common = {item.piece_id for item in facts[0].pieces}
    for position in facts[1:]:
        common &= {item.piece_id for item in position.pieces}
    return common


def _defenders(facts: PositionFacts) -> dict[PieceId, tuple[PieceId, ...]]:
    defenders: dict[PieceId, set[PieceId]] = {}
    for contact in facts.contacts:
        if contact.kind is ContactKind.DEFEND:
            defenders.setdefault(contact.subject, set()).add(contact.controller)
    return {
        subject: tuple(sorted(controllers, key=_piece_key))
        for subject, controllers in defenders.items()
    }


def _attacked(facts: PositionFacts) -> set[PieceId]:
    return {
        contact.subject
        for contact in facts.contacts
        if contact.kind is ContactKind.ATTACK
    }


def _piece_square(facts: PositionFacts, piece: PieceId) -> SquareRef:
    placement = next(item for item in facts.pieces if item.piece_id == piece)
    return SquareRef(facts.position_id, placement.square)


def _piece_key(piece: PieceId) -> tuple[str, str, str]:
    return piece.color, piece.origin_square, piece.original_piece_type
