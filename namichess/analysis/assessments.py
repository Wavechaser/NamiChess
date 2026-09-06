"""Qualified assessments derived from replayable local evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import chess

from namichess.analysis.exchange import ExchangeStatus
from namichess.analysis.local import LocalExit, LocalExploration, LocalLine, LocalTermination
from namichess.analysis.static import ContactKind, position_facts
from namichess.domain.models import PieceId, PositionContext, PositionId
from namichess.domain.position import replay_position


class AssessmentConclusion(str, Enum):
    OBSERVED_FAILURE = "observed_failure"
    LOCALLY_ESTABLISHED_FAILURE = "locally_established_failure"
    NO_REFUTATION_FOUND = "no_refutation_found"
    INCOMPLETE = "incomplete"
    NO_LEGAL_EXITS = "no_legal_exits"
    NO_LOCALLY_SURVIVING_EXIT = "no_locally_surviving_exit"
    UNREFUTED_EXIT_FOUND = "unrefuted_exit_found"
    WITNESSED_CONFLICTING_DUTIES = "witnessed_conflicting_duties"
    NO_CONFLICT_FOUND = "no_conflict_found"
    UNSUPPORTED = "unsupported"


class EvidenceKind(str, Enum):
    LOCAL_LINE = "local_line"
    EXCHANGE = "exchange"
    REPLY_EXCHANGE = "reply_exchange"


class CoverageUnit(str, Enum):
    OPPONENT_REPLIES = "opponent_replies"
    LEGAL_EXITS = "legal_exits"
    ROOT_MOVES = "root_moves"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    kind: EvidenceKind
    root_uci: str
    line_index: int | None = None


@dataclass(frozen=True, slots=True)
class AssessmentCoverage:
    unit: CoverageUnit
    total: int
    examined: int
    refuted: int
    unresolved: int

    def __post_init__(self) -> None:
        values = (self.total, self.examined, self.refuted, self.unresolved)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("coverage counts must be nonnegative integers")
        if self.examined + self.unresolved != self.total or self.refuted > self.examined:
            raise ValueError("coverage counts are inconsistent")

    @property
    def complete(self) -> bool:
        return self.examined == self.total and self.unresolved == 0


@dataclass(frozen=True, slots=True)
class MoveSafetyAssessment:
    position_id: PositionId
    root_uci: str
    conclusion: AssessmentConclusion
    coverage: AssessmentCoverage
    evidence: tuple[EvidenceRef, ...]
    exchange_result: int | None = None


@dataclass(frozen=True, slots=True)
class MaterialExposure:
    exit_uci: str
    reply_uci: str
    material_result: int
    evidence: EvidenceRef
    model: str = "root_gain_plus_target_square_material"


@dataclass(frozen=True, slots=True)
class TrappingAssessment:
    position_id: PositionId
    piece: PieceId
    conclusion: AssessmentConclusion
    legal_exits: tuple[str, ...]
    refuted_exits: tuple[str, ...]
    unresolved_exits: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    coverage: AssessmentCoverage
    material_exposed_exits: tuple[str, ...] = ()
    material_exposures: tuple[MaterialExposure, ...] = ()


@dataclass(frozen=True, slots=True)
class Duty:
    defended: PieceId
    attacker: PieceId


@dataclass(frozen=True, slots=True)
class OverloadAssessment:
    position_id: PositionId
    defender: PieceId
    duties: tuple[Duty, ...]
    conclusion: AssessmentConclusion
    evidence: tuple[EvidenceRef, ...]
    coverage: AssessmentCoverage


def assess_move_safety(context: PositionContext, exploration: LocalExploration) -> tuple[MoveSafetyAssessment, ...]:
    """Assess explored roots without turning a selected PV into a forced claim."""
    _same_position(context, exploration)
    _validate_evidence_associations(exploration)
    board, _ = replay_position(context)
    mover = board.turn
    results = []
    for root in exploration.roots:
        observed: list[EvidenceRef] = []
        established: list[EvidenceRef] = []
        unresolved = root.legal_reply_count - root.examined_reply_count
        for index, line in enumerate(root.lines):
            if not _eligible_mate_line(context, line, mover):
                continue
            reference = EvidenceRef(EvidenceKind.LOCAL_LINE, root.root_uci, index)
            observed.append(reference)
            if len(line.moves) == 2:
                established.append(reference)
        if established:
            conclusion = AssessmentConclusion.LOCALLY_ESTABLISHED_FAILURE
            evidence = tuple(established)
        elif observed:
            conclusion = AssessmentConclusion.OBSERVED_FAILURE
            evidence = tuple(observed)
        elif unresolved:
            conclusion = AssessmentConclusion.INCOMPLETE
            evidence = ()
        else:
            conclusion = AssessmentConclusion.NO_REFUTATION_FOUND
            evidence = ()
        exchange_result = None
        if root.exchange is not None and root.exchange.status is ExchangeStatus.COMPLETED:
            exchange_result = root.exchange.material_result
            evidence = (*evidence, EvidenceRef(EvidenceKind.EXCHANGE, root.root_uci))
        results.append(MoveSafetyAssessment(
            exploration.position_id, root.root_uci, conclusion,
            AssessmentCoverage(CoverageUnit.OPPONENT_REPLIES, root.legal_reply_count, root.examined_reply_count, len(established), unresolved),
            evidence, exchange_result,
        ))
    return tuple(results)


def assess_trapping(
    context: PositionContext, exploration: LocalExploration, piece: PieceId,
) -> TrappingAssessment:
    """Classify actual-turn legal exits of one piece under local coverage."""
    _same_position(context, exploration)
    _validate_evidence_associations(exploration)
    board, placements = replay_position(context)
    placement = next((item for item in placements if item.piece_id == piece), None)
    if placement is None or placement.color != ("white" if board.turn else "black"):
        return TrappingAssessment(exploration.position_id, piece, AssessmentConclusion.UNSUPPORTED, (), (), (), (), AssessmentCoverage(CoverageUnit.LEGAL_EXITS, 0, 0, 0, 0))
    if board.is_game_over(claim_draw=False):
        return TrappingAssessment(exploration.position_id, piece, AssessmentConclusion.UNSUPPORTED, (), (), (), (), AssessmentCoverage(CoverageUnit.LEGAL_EXITS, 0, 0, 0, 0))
    source = chess.parse_square(placement.square)
    legal_exits = tuple(sorted(move.uci() for move in board.legal_moves if move.from_square == source))
    if not legal_exits:
        return TrappingAssessment(exploration.position_id, piece, AssessmentConclusion.NO_LEGAL_EXITS, (), (), (), (), AssessmentCoverage(CoverageUnit.LEGAL_EXITS, 0, 0, 0, 0))

    roots = {root.root_uci: root for root in exploration.roots}
    refuted: list[str] = []
    unresolved: list[str] = []
    evidence: list[EvidenceRef] = []
    material_exposures: list[MaterialExposure] = []
    for uci in legal_exits:
        root = roots.get(uci)
        if root is not None:
            material_exposures.extend(_material_exposures(root))
        decisive = _immediate_mate_refs(context, root, board.turn) if root is not None else ()
        if decisive:
            refuted.append(uci)
            evidence.extend(decisive)
        elif root is None or root.examined_reply_count != root.legal_reply_count or any(
            line.exit is LocalExit.UNRESOLVED for line in root.lines
        ):
            unresolved.append(uci)

    examined = len(legal_exits) - len(unresolved)
    coverage = AssessmentCoverage(CoverageUnit.LEGAL_EXITS, len(legal_exits), examined, len(refuted), len(unresolved))
    if unresolved:
        conclusion = AssessmentConclusion.INCOMPLETE
    elif len(refuted) == len(legal_exits):
        conclusion = AssessmentConclusion.NO_LOCALLY_SURVIVING_EXIT
    else:
        conclusion = AssessmentConclusion.UNREFUTED_EXIT_FOUND
    return TrappingAssessment(
        exploration.position_id, piece, conclusion, legal_exits, tuple(refuted), tuple(unresolved), tuple(evidence), coverage,
        tuple(dict.fromkeys(item.exit_uci for item in material_exposures)), tuple(material_exposures),
    )


def assess_overload(context: PositionContext, exploration: LocalExploration) -> tuple[OverloadAssessment, ...]:
    """Report concrete witnessed duty conflicts; do not infer universal overload."""
    _same_position(context, exploration)
    _validate_evidence_associations(exploration)
    facts = position_facts(context)
    board, _ = replay_position(context)
    if board.is_game_over(claim_draw=False):
        return ()
    actual = "white" if board.turn else "black"
    attacked = {
        contact.subject: tuple(
            other.controller for other in facts.contacts
            if other.subject == contact.subject and other.kind is ContactKind.ATTACK
        )
        for contact in facts.contacts
        if contact.kind is ContactKind.ATTACK and contact.subject.color == actual
    }
    defenders = sorted(
        {contact.controller for contact in facts.contacts if contact.kind is ContactKind.DEFEND and contact.subject in attacked},
        key=lambda item: (item.color, item.origin_square),
    )
    results = []
    for defender in defenders:
        duties = tuple(
            Duty(contact.subject, attacker)
            for contact in facts.contacts if contact.kind is ContactKind.DEFEND and contact.controller == defender
            for attacker in attacked.get(contact.subject, ())
        )
        if len({duty.defended for duty in duties}) < 2:
            continue
        refs = _witnessed_duty_conflicts(context, exploration, defender, duties)
        legal_roots = {move.uci() for move in board.legal_moves}
        completed_roots = {
            root.root_uci for root in exploration.roots
            if root.examined_reply_count == root.legal_reply_count
        }
        unresolved = len(legal_roots - completed_roots)
        conclusion = AssessmentConclusion.WITNESSED_CONFLICTING_DUTIES if refs else (
            AssessmentConclusion.INCOMPLETE if exploration.limit_reached is not None or unresolved else AssessmentConclusion.NO_CONFLICT_FOUND
        )
        results.append(OverloadAssessment(
            exploration.position_id, defender, duties, conclusion, refs,
            AssessmentCoverage(CoverageUnit.ROOT_MOVES, len(legal_roots), len(completed_roots), 0, unresolved),
        ))
    return tuple(results)


def _witnessed_duty_conflicts(context, exploration, defender, duties) -> tuple[EvidenceRef, ...]:
    refs = []
    for root in exploration.roots:
        for index, line in enumerate(root.lines):
            if not line.deltas or line.deltas[0].moved.piece != defender:
                continue
            first = line.deltas[0]
            fulfilled = {
                duty.defended
                for duty in duties
                if first.captured is not None and first.captured.piece_id == duty.attacker
            }
            abandoned = {
                contact.subject
                for contact in first.contacts_removed
                if contact.kind is ContactKind.DEFEND and contact.controller == defender
            } - fulfilled
            if not fulfilled or not abandoned:
                continue
            for reply in line.deltas[1:2]:
                exploited = next((
                    duty for duty in duties
                    if duty.defended in abandoned
                    and reply.moved.piece == duty.attacker
                    and reply.captured is not None
                    and reply.captured.piece_id == duty.defended
                ), None)
                if exploited is not None and not _capture_has_legal_recapture(context, line.moves[:2]):
                    refs.append(EvidenceRef(EvidenceKind.LOCAL_LINE, root.root_uci, index))
    return tuple(dict.fromkeys(refs))


def _capture_has_legal_recapture(context: PositionContext, moves: tuple[str, ...]) -> bool:
    board, _ = replay_position(context)
    for uci in moves:
        board.push_uci(uci)
    target = chess.Move.from_uci(moves[-1]).to_square
    return any(move.to_square == target and board.is_capture(move) for move in board.legal_moves)


_MATERIAL_VALUES = {"pawn": 1, "knight": 3, "bishop": 3, "rook": 5, "queen": 9}


def _material_exposures(root) -> tuple[MaterialExposure, ...]:
    result = []
    for index, line in enumerate(root.lines):
        if len(line.deltas) < 2 or line.reply_exchange is None:
            continue
        exchange = line.reply_exchange
        if exchange.status is not ExchangeStatus.COMPLETED or exchange.material_result is None:
            continue
        first, reply = line.deltas[:2]
        if reply.captured is None or reply.captured.piece_id != first.moved.piece:
            continue
        root_gain = _MATERIAL_VALUES.get(first.captured.piece_type, 0) if first.captured is not None else 0
        if first.promoted:
            root_gain += _MATERIAL_VALUES.get(first.moved.after.piece_type, 0) - 1
        net = root_gain + exchange.material_result
        if net < 0:
            result.append(MaterialExposure(
                root.root_uci, line.moves[1], net,
                EvidenceRef(EvidenceKind.REPLY_EXCHANGE, root.root_uci, index),
            ))
    return tuple(result)


def _immediate_mate_refs(context, root, mover):
    if root is None:
        return ()
    return tuple(
        EvidenceRef(EvidenceKind.LOCAL_LINE, root.root_uci, index)
        for index, line in enumerate(root.lines)
        if len(line.moves) == 2 and _eligible_mate_line(context, line, mover)
    )


def _eligible_mate_line(context: PositionContext, line: LocalLine, mover: chess.Color) -> bool:
    return (
        line.exit is LocalExit.WITNESSED_MATE
        and line.termination is LocalTermination.TERMINAL
        and _mated_side(context, line) == mover
    )


def _mated_side(context: PositionContext, line: LocalLine) -> chess.Color | None:
    board, _ = replay_position(context)
    try:
        for uci in line.moves:
            board.push_uci(uci)
    except (ValueError, chess.IllegalMoveError):
        return None
    return board.turn if board.is_checkmate() else None


def _same_position(context: PositionContext, exploration: LocalExploration) -> None:
    if context.position_id != exploration.position_id:
        raise ValueError("local exploration belongs to a different position")


def _validate_evidence_associations(exploration: LocalExploration) -> None:
    seen_roots: set[str] = set()
    for root in exploration.roots:
        if root.root_uci in seen_roots:
            raise ValueError("local exploration contains a duplicate root")
        seen_roots.add(root.root_uci)
        if not 0 <= root.examined_reply_count <= root.legal_reply_count:
            raise ValueError("local root reply coverage is inconsistent")
        if root.exchange is not None and root.exchange.status is ExchangeStatus.COMPLETED and (
            not root.exchange.line or root.exchange.line[0] != root.root_uci
        ):
            raise ValueError("root exchange belongs to a different move")
        seen_replies: set[str] = set()
        resolved_replies = 0
        for line in root.lines:
            if not line.moves or line.moves[0] != root.root_uci:
                raise ValueError("local line belongs to a different root")
            if line.deltas and tuple(delta.uci for delta in line.deltas) != line.moves:
                raise ValueError("local line deltas do not match its moves")
            if line.reply_exchange is not None and line.reply_exchange.status is ExchangeStatus.COMPLETED and (
                len(line.moves) < 2
                or not line.reply_exchange.line
                or line.reply_exchange.line[0] != line.moves[1]
            ):
                raise ValueError("reply exchange belongs to a different reply")
            if len(line.moves) >= 2:
                if line.moves[1] in seen_replies:
                    raise ValueError("local root contains a duplicate reply branch")
                seen_replies.add(line.moves[1])
                if line.exit is not LocalExit.UNRESOLVED:
                    resolved_replies += 1
        if root.legal_reply_count and resolved_replies != root.examined_reply_count:
            raise ValueError("local root reply count does not match its resolved branches")
