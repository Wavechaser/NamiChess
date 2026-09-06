from __future__ import annotations

import asyncio

import chess
import pytest

import namichess.analysis.local as local_module
from namichess.analysis.exchange import ExchangeStatus
from namichess.analysis.consequences import resolve_raw_fact
from namichess.analysis.local import LocalLimits, explore_local
from namichess.analysis.mechanisms import CheckKind, CheckerRole
from namichess.analysis.threats import DefensiveReplyRole, ThreatConclusion, ThreatReplyOutcome
from namichess.domain.models import PositionContext


def _context(fen: str) -> PositionContext:
    assert chess.Board(fen).is_valid()
    return PositionContext(1, 1, (), fen, (), fen, False)


async def _root(
    fen: str,
    root: str,
    *,
    limits: LocalLimits = LocalLimits(),
    deadline: float = 10.0,
    monotonic=lambda: 0.0,
    cancelled=lambda: False,
):
    result = await explore_local(
        _context(fen), limits=limits, deadline=deadline, monotonic=monotonic,
        root_moves=(root,), cancelled=cancelled, request_id=1,
    )
    return result.roots[0]


def test_double_check_fork_keeps_queen_target_through_every_king_reply() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1", "c3e5")
        threat = root.threats[0]

        assert threat.effect.check.kind is CheckKind.DOUBLE
        assert tuple(item.piece.origin_square for item in threat.effect.check.checkers) == ("c1", "c3")
        assert threat.effect.attacks[0].actor.origin_square == "c3"
        assert threat.effect.target.origin_square == "h2"
        assert threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY
        assert all(response.capture_uci == "e5h2" for response in threat.responses)
        assert all(response.roles == (DefensiveReplyRole.KING_MOVE,) for response in threat.responses)
        assert root.root_delta is not None
        assert all(
            resolve_raw_fact(root.root_delta, reference) is not None
            for attack in threat.effect.attacks
            for reference in attack.supporting_facts
        )

    asyncio.run(exercise())


def test_discovered_check_tracks_the_same_queen_after_interposition() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6")
        threat = root.threats[0]
        block = next(response for response in threat.responses if response.reply_uci == "h4c4")

        assert threat.effect.check.kind is CheckKind.SINGLE
        assert threat.effect.check.checkers[0].role is CheckerRole.DISCOVERED
        assert tuple(item.piece.origin_square for item in threat.effect.check.checkers) == ("c1",)
        assert threat.effect.target.origin_square == "h4"
        assert threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY
        assert block.target_square.square == "c4"
        assert block.reply_san == "Qc4"
        assert block.capture_uci == "c1c4"
        assert block.capture_san == "Qxc4+"
        assert block.capture_actor is not None and block.capture_actor.origin_square == "c1"
        assert block.capture_source is not None and block.capture_source.square == "c1"
        assert block.capture_destination is not None and block.capture_destination.square == "c4"
        assert DefensiveReplyRole.INTERPOSE in block.roles
        assert block.exchange is not None and block.exchange.status is ExchangeStatus.UNSUPPORTED

    asyncio.run(exercise())


def test_single_check_fork_is_not_misclassified_as_discovered_or_double() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/8/2B5/3P3r/K7 w - - 0 1", "c3e5")
        threat = root.threats[0]

        assert threat.effect.check.kind is CheckKind.SINGLE
        assert threat.effect.check.checkers[0].role is CheckerRole.DIRECT
        assert tuple(item.piece.origin_square for item in threat.effect.check.checkers) == ("c3",)
        assert threat.effect.target.origin_square == "h2"
        assert threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY

    asyncio.run(exercise())


def test_threat_response_coverage_stays_incomplete_at_the_shared_node_limit() -> None:
    async def exercise() -> None:
        root = await _root(
            "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6",
            limits=LocalLimits(node_limit=2),
        )
        threat = root.threats[0]

        assert threat.examined_reply_count == 1
        assert threat.legal_reply_count == 6
        assert len(threat.omitted_replies) == 5
        assert threat.conclusion is ThreatConclusion.INCOMPLETE
        assert threat.responses[0].outcome is ThreatReplyOutcome.CAPTURE_AVAILABLE

    asyncio.run(exercise())


def test_depth_below_root_reply_capture_does_not_establish_a_common_outcome() -> None:
    async def exercise() -> None:
        root = await _root(
            "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6",
            limits=LocalLimits(max_depth=2),
        )
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h4")

        assert threat.examined_reply_count == 0
        assert len(threat.omitted_replies) == threat.legal_reply_count
        assert threat.conclusion is ThreatConclusion.INCOMPLETE

    asyncio.run(exercise())


def test_automatic_draw_after_check_has_no_fictional_defensive_responses() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 149 1", "c3f6")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h4")

        assert root.legal_reply_count == root.examined_reply_count == 0
        assert threat.legal_reply_count == threat.examined_reply_count == 0
        assert threat.responses == ()
        assert threat.conclusion is ThreatConclusion.NO_LEGAL_REPLIES

    asyncio.run(exercise())


def test_root_delta_reuses_one_before_and_after_fact_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    real_position_facts = local_module.position_facts
    calls = 0

    def counted(context):
        nonlocal calls
        calls += 1
        return real_position_facts(context)

    monkeypatch.setattr(local_module, "position_facts", counted)

    async def exercise() -> None:
        await _root(
            "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 149 1", "c3f6",
        )
        assert calls == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("fen", "root", "mirrored_root", "target"),
    (
        ("8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1", "c3e5", "c6e4", "h2"),
        ("8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6", "c6f3", "h4"),
        ("8/2k5/8/8/8/2B5/3P3r/K7 w - - 0 1", "c3e5", "c6e4", "h2"),
    ),
)
def test_checking_target_coverage_mirrors_by_color(fen: str, root: str, mirrored_root: str, target: str) -> None:
    async def exercise() -> None:
        original = await _root(fen, root)
        mirrored = await _root(chess.Board(fen).mirror().fen(en_passant="fen"), mirrored_root)
        original_threat = next(item for item in original.threats if item.effect.target.origin_square == target)
        mirrored_threat = next(item for item in mirrored.threats if item.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY)

        assert original_threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY
        assert mirrored_threat.effect.target.color == "white"
        assert mirrored_threat.legal_reply_count == original_threat.legal_reply_count
        assert all(response.capture_actor is not None and response.capture_actor.color == "black"
                   for response in mirrored_threat.responses)

    asyncio.run(exercise())


def test_interposing_target_can_countercheck_without_erasing_its_identity() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/7q/2B5/K2P4/2Q5 w - - 0 1", "c3f6")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h4")
        response = next(item for item in threat.responses if item.reply_uci == "h4c4")

        assert response.reply_san == "Qc4+"
        assert response.target_square.square == "c4"
        assert response.capture_san == "Qxc4+"
        assert response.outcome is ThreatReplyOutcome.CAPTURE_AVAILABLE

    asyncio.run(exercise())


def test_terminal_defense_is_not_treated_as_a_capture_witness() -> None:
    async def exercise() -> None:
        root = await _root("8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 148 1", "c3f6")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h4")

        assert threat.legal_reply_count == 6
        assert all(item.outcome is ThreatReplyOutcome.TERMINAL for item in threat.responses)
        assert threat.conclusion is ThreatConclusion.NO_IMMEDIATE_CAPTURE

    asyncio.run(exercise())


def test_escapable_target_prevents_a_universal_capture_conclusion() -> None:
    async def exercise() -> None:
        fen = "8/8/Q2r3Q/3Q4/K7/8/2k1p3/8 w - - 0 1"
        root = await _root(fen, "d5d3")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "e2")
        board = chess.Board(fen)
        board.push_uci(root.root_uci)

        assert {move.uci() for move in board.legal_moves} == {"c2b2", "d6d3"}
        assert [(item.reply_uci, item.outcome) for item in threat.responses] == [
            ("c2b2", ThreatReplyOutcome.CAPTURE_AVAILABLE),
            ("d6d3", ThreatReplyOutcome.NO_IMMEDIATE_CAPTURE),
        ]
        assert threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_SOME_REPLY

    asyncio.run(exercise())


def test_pinned_geometric_attacker_is_not_a_legal_capture_witness() -> None:
    async def exercise() -> None:
        fen = "8/7Q/8/1r6/8/rk3K2/4N3/6Q1 w - - 0 1"
        root = await _root(fen, "h7d3")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "b5")
        response = next(item for item in threat.responses if item.reply_uci == "b3b4")
        board = chess.Board(fen)
        board.push_uci(root.root_uci)
        board.push_uci(response.reply_uci)

        assert board.is_pinned(chess.WHITE, chess.D3)
        assert chess.D3 in board.attackers(chess.WHITE, chess.B5)
        assert not any(board.is_capture(move) and move.to_square == chess.B5 for move in board.legal_moves)
        assert response.outcome is ThreatReplyOutcome.NO_IMMEDIATE_CAPTURE
        assert threat.conclusion is ThreatConclusion.NO_IMMEDIATE_CAPTURE

    asyncio.run(exercise())


def test_loss_making_exchange_remains_capture_availability_not_material_gain() -> None:
    async def exercise() -> None:
        root = await _root("7r/2k5/8/8/8/2B5/3P3p/K7 w - - 0 1", "c3e5")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h2")

        assert threat.conclusion is ThreatConclusion.CAPTURE_AVAILABLE_EVERY_REPLY
        assert all(item.exchange is not None for item in threat.responses)
        assert all(item.exchange.status is ExchangeStatus.COMPLETED for item in threat.responses if item.exchange)
        assert all(item.exchange.material_result == -2 for item in threat.responses if item.exchange)

    asyncio.run(exercise())


def test_en_passant_defense_tracks_the_captured_pawn_not_the_landing_square() -> None:
    async def exercise() -> None:
        fen = "8/3k1p2/8/4P3/6N1/7Q/8/K7 w - - 0 1"
        root = await _root(fen, "g4h6")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "f7")
        response = next(item for item in threat.responses if item.reply_uci == "f7f5")
        board = chess.Board(fen)
        board.push_uci(root.root_uci)
        board.push_uci(response.reply_uci)

        assert [move.uci() for move in board.legal_moves if board.is_en_passant(move)] == ["e5f6"]
        assert response.target_square.square == "f5"
        assert response.capture_uci == "e5f6"
        assert response.capture_destination is not None and response.capture_destination.square == "f6"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("fen", "root_uci", "reply_uci"),
    (
        ("8/8/8/4k1n1/6p1/8/5P2/K7 w - - 0 1", "f2f4", "g4f3"),
        ("k7/5p2/8/6P1/4K1N1/8/8/8 b - - 0 1", "f7f5", "g5f6"),
    ),
)
def test_en_passant_capture_of_checker_has_capture_checker_role(
    fen: str, root_uci: str, reply_uci: str,
) -> None:
    async def exercise() -> None:
        root = await _root(fen, root_uci)
        response = next(
            item
            for threat in root.threats
            for item in threat.responses
            if item.reply_uci == reply_uci
        )
        board = chess.Board(fen)
        board.push_uci(root_uci)
        reply = chess.Move.from_uci(reply_uci)

        assert board.is_en_passant(reply)
        assert reply in board.legal_moves
        assert response.roles == (DefensiveReplyRole.CAPTURE_CHECKER,)

    asyncio.run(exercise())


def test_promotion_defense_keeps_the_moving_pawn_identity() -> None:
    async def exercise() -> None:
        fen = "8/8/8/8/4k3/8/p1N5/1BK5 w - - 0 1"
        root = await _root(fen, "c2b4")
        threat = next(item for item in root.threats if item.effect.target.origin_square == "a2")
        response = next(item for item in threat.responses if item.reply_uci == "a2b1q")
        board = chess.Board(fen)
        board.push_uci(root.root_uci)

        assert {move.uci() for move in board.legal_moves if move.from_square == chess.A2} == {
            "a2b1q", "a2b1r", "a2b1b", "a2b1n",
        }
        assert response.target_square.square == "b1"
        assert response.capture_uci == "c1b1"
        assert response.outcome is ThreatReplyOutcome.CAPTURE_AVAILABLE

    asyncio.run(exercise())


def test_same_target_attacked_by_two_pieces_produces_one_effect() -> None:
    async def exercise() -> None:
        root = await _root("8/1B6/1b1k4/8/8/2R1N1p1/3K4/8 w - - 0 1", "e3f5")
        threats = [item for item in root.threats if item.effect.target.origin_square == "g3"]

        assert len(threats) == 1
        assert {attack.actor.origin_square for attack in threats[0].effect.attacks} == {"c3", "e3"}

    asyncio.run(exercise())


def test_deadline_during_threat_responses_marks_coverage_incomplete() -> None:
    async def exercise() -> None:
        calls = 0

        def clock() -> float:
            nonlocal calls
            calls += 1
            return 0.0 if calls < 3 else 1.0

        root = await _root(
            "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6",
            deadline=1.0, monotonic=clock,
        )
        threat = next(item for item in root.threats if item.effect.target.origin_square == "h4")

        assert threat.examined_reply_count == 0
        assert threat.omitted_replies
        assert threat.conclusion is ThreatConclusion.INCOMPLETE

    asyncio.run(exercise())


def test_cancellation_during_threat_response_propagates() -> None:
    async def exercise() -> None:
        checks = 0

        def cancelled() -> bool:
            nonlocal checks
            checks += 1
            return checks > 1

        with pytest.raises(asyncio.CancelledError):
            await _root(
                "8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1", "c3f6",
                cancelled=cancelled,
            )

    asyncio.run(exercise())
