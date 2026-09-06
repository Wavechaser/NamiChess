"""Bounded checking-threat response evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import Enum

import chess

from namichess.analysis.continuations import continuation_context
from namichess.analysis.exchange import ExchangeEvidence, evaluate_exchange
from namichess.analysis.mechanisms import CheckMechanism, MechanismAttack, move_mechanisms
from namichess.analysis.static import MoveDelta, PositionFacts
from namichess.domain.models import PieceId, PositionContext, PositionId, SquareRef


class DefensiveReplyRole(str, Enum):
    KING_MOVE = "king_move"
    CAPTURE_CHECKER = "capture_checker"
    INTERPOSE = "interpose"


class ThreatReplyOutcome(str, Enum):
    CAPTURE_AVAILABLE = "capture_available"
    NO_IMMEDIATE_CAPTURE = "no_immediate_capture"
    TERMINAL = "terminal"


class ThreatConclusion(str, Enum):
    CAPTURE_AVAILABLE_EVERY_REPLY = "capture_available_every_reply"
    CAPTURE_AVAILABLE_SOME_REPLY = "capture_available_some_reply"
    NO_IMMEDIATE_CAPTURE = "no_immediate_capture"
    INCOMPLETE = "incomplete"
    NO_LEGAL_REPLIES = "no_legal_replies"


@dataclass(frozen=True, slots=True)
class ThreatEffect:
    root_uci: str
    check: CheckMechanism
    target: PieceId
    attacks: tuple[MechanismAttack, ...]


@dataclass(frozen=True, slots=True)
class ThreatResponse:
    reply_uci: str
    reply_san: str
    roles: tuple[DefensiveReplyRole, ...]
    target_square: SquareRef
    outcome: ThreatReplyOutcome
    capture_uci: str | None = None
    capture_san: str | None = None
    capture_actor: PieceId | None = None
    capture_source: SquareRef | None = None
    capture_destination: SquareRef | None = None
    capture_candidate_count: int = 0
    exchange: ExchangeEvidence | None = None


@dataclass(frozen=True, slots=True)
class ThreatEvidence:
    """A common target after a check and all covered legal defenses.

    A capture-available conclusion establishes a legal immediate capture only;
    exchange evidence cannot turn it into a material-win assertion.
    """

    position_id: PositionId
    effect: ThreatEffect
    conclusion: ThreatConclusion
    legal_reply_count: int
    examined_reply_count: int
    responses: tuple[ThreatResponse, ...]
    omitted_replies: tuple[str, ...] = ()


async def verify_checking_threats(
    *,
    context: PositionContext,
    request_id: int,
    root_context: PositionContext,
    root_delta: MoveDelta,
    after_facts: PositionFacts,
    after_root: chess.Board,
    max_depth: int,
    checkpoint: Callable[[], Awaitable[bool]],
    deadline: float,
    monotonic: Callable[[], float],
) -> tuple[ThreatEvidence, ...]:
    effects = _effects(root_delta, after_facts)
    if not effects:
        return ()
    if after_root.is_game_over(claim_draw=False):
        return tuple(_evidence(context.position_id, effect, 0, 0, (), ()) for effect in effects)
    replies = tuple(sorted(after_root.legal_moves, key=lambda item: item.uci()))
    if max_depth < 3:
        return tuple(_evidence(context.position_id, effect, len(replies), 0, (), tuple(item.uci() for item in replies)) for effect in effects)

    responses: list[list[ThreatResponse]] = [[] for _ in effects]
    actors_by_square = {
        chess.parse_square(placement.square): placement.piece_id
        for placement in after_facts.pieces
    }
    examined = 0
    for reply in replies:
        if not await checkpoint():
            break
        reply_san = after_root.san(reply)
        roles = _reply_roles(after_root, reply)
        after_root.push(reply)
        try:
            reply_context = continuation_context(context, request_id, (*root_context.moves, reply.uci()), after_root)
            terminal = after_root.is_game_over(claim_draw=False)
            for index, effect in enumerate(effects):
                target_square = _target_square_after_reply(effect, reply)
                captures = () if terminal else tuple(sorted(
                    (move for move in after_root.legal_moves if _captures_target(after_root, move, target_square)),
                    key=lambda move: (not after_root.gives_check(move), move.uci()),
                ))
                witness = captures[0] if captures else None
                actor = actors_by_square.get(witness.from_square) if witness is not None else None
                capture_san = after_root.san(witness) if witness is not None else None
                responses[index].append(ThreatResponse(
                    reply_uci=reply.uci(), reply_san=reply_san, roles=roles,
                    target_square=SquareRef(reply_context.position_id, chess.square_name(target_square)),
                    outcome=ThreatReplyOutcome.CAPTURE_AVAILABLE if witness is not None else (
                        ThreatReplyOutcome.TERMINAL if terminal else ThreatReplyOutcome.NO_IMMEDIATE_CAPTURE
                    ),
                    capture_uci=witness.uci() if witness is not None else None,
                    capture_san=capture_san,
                    capture_actor=actor,
                    capture_source=(SquareRef(reply_context.position_id, chess.square_name(witness.from_square))
                                    if witness is not None else None),
                    capture_destination=(SquareRef(reply_context.position_id, chess.square_name(witness.to_square))
                                         if witness is not None else None),
                    capture_candidate_count=len(captures),
                ))
        finally:
            after_root.pop()
        examined += 1

    omitted = tuple(item.uci() for item in replies[examined:])
    evidence = [_evidence(context.position_id, effect, len(replies), examined, tuple(items), omitted)
                for effect, items in zip(effects, responses, strict=True)]
    if omitted:
        return tuple(evidence)
    for evidence_index, item in enumerate(evidence):
        updated = list(item.responses)
        for response_index, response in enumerate(updated):
            if response.capture_uci is None:
                continue
            if not await checkpoint():
                evidence[evidence_index] = _evidence(item.position_id, item.effect, item.legal_reply_count,
                                                      item.examined_reply_count, tuple(updated), item.omitted_replies)
                return tuple(evidence)
            replay = after_root.copy(stack=True)
            replay.push_uci(response.reply_uci)
            exchange = await evaluate_exchange(
                replay, chess.Move.from_uci(response.capture_uci), perspective=replay.turn,
                deadline=deadline, monotonic=monotonic, node_limit=4096, cooperate=checkpoint,
            )
            updated[response_index] = replace(response, exchange=exchange)
        evidence[evidence_index] = _evidence(item.position_id, item.effect, item.legal_reply_count,
                                              item.examined_reply_count, tuple(updated), item.omitted_replies)
    return tuple(evidence)


def _effects(delta: MoveDelta, after: PositionFacts) -> tuple[ThreatEffect, ...]:
    mechanisms = move_mechanisms(delta, after)
    if mechanisms.check is None:
        return ()
    grouped: dict[PieceId, list[MechanismAttack]] = {}
    mover_color = delta.moved.after.color
    for attack in mechanisms.attacks:
        if attack.actor.color != mover_color:
            continue
        grouped.setdefault(attack.target, []).append(attack)
    return tuple(ThreatEffect(delta.uci, mechanisms.check, target, tuple(attacks))
                 for target, attacks in sorted(grouped.items(), key=lambda item: _piece_key(item[0])))


def _evidence(position_id: PositionId, effect: ThreatEffect, total: int, examined: int,
              responses: tuple[ThreatResponse, ...], omitted: tuple[str, ...]) -> ThreatEvidence:
    if not total:
        conclusion = ThreatConclusion.NO_LEGAL_REPLIES
    elif omitted or examined != total:
        conclusion = ThreatConclusion.INCOMPLETE
    elif all(item.outcome is ThreatReplyOutcome.CAPTURE_AVAILABLE for item in responses):
        conclusion = ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY
    elif any(item.outcome is ThreatReplyOutcome.CAPTURE_AVAILABLE for item in responses):
        conclusion = ThreatConclusion.CAPTURE_AVAILABLE_SOME_REPLY
    else:
        conclusion = ThreatConclusion.NO_IMMEDIATE_CAPTURE
    return ThreatEvidence(position_id, effect, conclusion, total, examined, responses, omitted)


def _reply_roles(board: chess.Board, reply: chess.Move) -> tuple[DefensiveReplyRole, ...]:
    king, checkers = board.king(board.turn), set(board.checkers())
    roles: list[DefensiveReplyRole] = []
    if reply.from_square == king:
        roles.append(DefensiveReplyRole.KING_MOVE)
    if board.is_capture(reply) and _captured_square(board, reply) in checkers:
        roles.append(DefensiveReplyRole.CAPTURE_CHECKER)
    if king is not None and any(chess.between(king, checker) & chess.BB_SQUARES[reply.to_square] for checker in checkers):
        roles.append(DefensiveReplyRole.INTERPOSE)
    return tuple(roles)


def _target_square_after_reply(effect: ThreatEffect, reply: chess.Move) -> chess.Square:
    square = chess.parse_square(effect.attacks[0].target_square.square)
    return reply.to_square if reply.from_square == square else square


def _captures_target(board: chess.Board, move: chess.Move, target: chess.Square) -> bool:
    if not board.is_capture(move):
        return False
    return _captured_square(board, move) == target


def _captured_square(board: chess.Board, move: chess.Move) -> chess.Square:
    if board.is_en_passant(move):
        return chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    return move.to_square


def _piece_key(piece: PieceId) -> tuple[str, str, str]:
    return piece.color, piece.origin_square, piece.original_piece_type
