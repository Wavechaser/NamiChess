"""Bounded, reference-based threat selection for interface consumers."""

from __future__ import annotations

from dataclasses import dataclass

from namichess.analysis.local import LocalExploration, LocalRootEvidence
from namichess.analysis.threats import (
    DefensiveReplyRole, ThreatConclusion, ThreatEvidence, ThreatReplyOutcome,
)
from namichess.domain.models import PieceId, PositionId


@dataclass(frozen=True, slots=True)
class ThreatReference:
    position_id: PositionId
    root_position_id: PositionId
    root_uci: str
    threat_index: int


@dataclass(frozen=True, slots=True)
class ThreatResponseGroup:
    outcome: ThreatReplyOutcome
    roles: tuple[DefensiveReplyRole, ...]
    capture_actor: PieceId | None
    capture_san: str | None
    target_square: str
    response_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SelectedThreat:
    reference: ThreatReference
    response_groups: tuple[ThreatResponseGroup, ...]


@dataclass(frozen=True, slots=True)
class ThreatSelection:
    position_id: PositionId
    root_uci: str
    threats: tuple[SelectedThreat, ...]
    omitted_count: int


def select_threats(
    local: LocalExploration,
    position_id: PositionId,
    root_uci: str,
    *,
    max_threats: int = 2,
) -> ThreatSelection | None:
    """Select interface-facing threat references without copying raw evidence."""
    if max_threats < 0:
        raise ValueError("maximum selected threats must be nonnegative")
    if local.position_id != position_id:
        raise ValueError("threat selection position does not match local evidence")
    root = next((item for item in local.roots if item.root_uci == root_uci), None)
    if root is None or not root.threats:
        return None
    if root.root_delta is None:
        raise ValueError("threat-bearing root must retain its root delta")

    ordered = sorted(
        enumerate(root.threats),
        key=lambda pair: (_conclusion_priority(pair[1]), _target_priority(root, pair[1]), pair[0]),
    )
    selected = tuple(
        SelectedThreat(
            ThreatReference(position_id, root.root_delta.after, root_uci, index),
            _response_groups(threat),
        )
        for index, threat in ordered[:max_threats]
    )
    return ThreatSelection(position_id, root_uci, selected, len(ordered) - len(selected))


def resolve_threat(local: LocalExploration, reference: ThreatReference) -> ThreatEvidence:
    """Resolve a selected reference against its exact retained local evidence."""
    if reference.position_id != local.position_id:
        raise ValueError("threat reference belongs to a different position")
    root = next((item for item in local.roots if item.root_uci == reference.root_uci), None)
    if root is None:
        raise ValueError("threat reference belongs to an unavailable root")
    if root.root_delta is None or reference.root_position_id != root.root_delta.after:
        raise ValueError("threat reference belongs to a different root position")
    if reference.threat_index < 0:
        raise ValueError("threat reference index is out of range")
    try:
        return root.threats[reference.threat_index]
    except IndexError as exc:
        raise ValueError("threat reference index is out of range") from exc


def _response_groups(threat: ThreatEvidence) -> tuple[ThreatResponseGroup, ...]:
    grouped: dict[tuple, list[int]] = {}
    for index, response in enumerate(threat.responses):
        key = (
            response.outcome,
            response.roles,
            response.capture_actor,
            response.capture_san,
            response.target_square.square,
        )
        grouped.setdefault(key, []).append(index)
    return tuple(
        ThreatResponseGroup(*key, tuple(indices))
        for key, indices in grouped.items()
    )


def _conclusion_priority(threat: ThreatEvidence) -> int:
    return {
        ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY: 0,
        ThreatConclusion.CAPTURE_AVAILABLE_SOME_REPLY: 1,
        ThreatConclusion.INCOMPLETE: 2,
        ThreatConclusion.NO_IMMEDIATE_CAPTURE: 3,
        ThreatConclusion.NO_LEGAL_REPLIES: 4,
    }[threat.conclusion]


def _target_priority(root: LocalRootEvidence, threat: ThreatEvidence) -> tuple[int, str, str]:
    current_type = threat.effect.target.original_piece_type
    if root.root_delta is not None:
        placement = next(
            (item for item in root.root_delta.after_pieces if item.piece_id == threat.effect.target),
            None,
        )
        if placement is not None:
            current_type = placement.piece_type
    category = 0 if current_type in {"queen", "rook"} else 1 if current_type in {"bishop", "knight"} else 2
    return category, current_type, threat.effect.target.origin_square
