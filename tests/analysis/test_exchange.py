from __future__ import annotations

import asyncio
import json
from pathlib import Path

import chess
import pytest

from namichess.analysis.exchange import ExchangeLimit, ExchangeStatus, evaluate_exchange


FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures" / "exchanges.json").read_text(encoding="utf-8"))


async def evaluate(fen: str, uci: str, *, perspective: chess.Color, node_limit: int = 4096):
    board = chess.Board(fen)
    return await evaluate_exchange(
        board,
        chess.Move.from_uci(uci),
        perspective=perspective,
        deadline=1.0,
        monotonic=lambda: 0.0,
        node_limit=node_limit,
    )


def replay(fen: str, line: tuple[str, ...]) -> None:
    board = chess.Board(fen)
    for uci in line:
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move)


def test_hand_computed_exchange_uses_optimal_stop_and_replayable_line() -> None:
    async def run() -> None:
        fen = FIXTURES["basic_recapture"]
        white = await evaluate(fen, "e4d5", perspective=chess.WHITE)
        black = await evaluate(fen, "e4d5", perspective=chess.BLACK)

        assert white.status is ExchangeStatus.COMPLETED
        assert white.line == ("e4d5", "c6d5")
        assert white.material_result == 0
        assert black.material_result == 0
        assert black.perspective == "black"
        replay(fen, white.line)

    asyncio.run(run())


def test_negative_material_result_remains_completed_evidence() -> None:
    async def run() -> None:
        fen = FIXTURES["negative_exchange"]
        result = await evaluate(fen, "e4d5", perspective=chess.WHITE)
        assert result.status is ExchangeStatus.COMPLETED
        assert result.line == ("e4d5", "c6d5")
        assert result.material_result == -8
        replay(fen, result.line)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fixture,move,perspective",
    [("white_pin", "e4d5", chess.WHITE), ("black_pin", "e5d4", chess.BLACK)],
)
def test_mirrored_absolute_pins_exclude_illegal_recaptures(fixture: str, move: str, perspective: chess.Color) -> None:
    async def run() -> None:
        result = await evaluate(FIXTURES[fixture], move, perspective=perspective)
        assert result.status is ExchangeStatus.COMPLETED
        assert result.line == (move,)
        assert result.material_result == 1

    asyncio.run(run())


@pytest.mark.parametrize("suffix,gain", [("q", 13), ("r", 9), ("b", 7), ("n", 7)])
def test_en_passant_and_capture_promotions_account_for_actual_material(suffix: str, gain: int) -> None:
    async def run() -> None:
        en_passant = await evaluate(FIXTURES["en_passant"], "e5d6", perspective=chess.WHITE)
        promotion = await evaluate(FIXTURES["capture_promotion"], f"a7b8{suffix}", perspective=chess.WHITE)
        mirrored = await evaluate(FIXTURES["capture_promotion_black"], f"a2b1{suffix}", perspective=chess.BLACK)

        assert (en_passant.line, en_passant.material_result) == (("e5d6",), 1)
        assert (promotion.line, promotion.material_result) == ((f"a7b8{suffix}",), gain)
        assert (mirrored.line, mirrored.material_result) == ((f"a2b1{suffix}",), gain)

    asyncio.run(run())


def test_xray_recalculation_and_alternative_recapture_orders_affect_minimax() -> None:
    async def run() -> None:
        fen = FIXTURES["xray_orders"]
        result = await evaluate(fen, "e4d5", perspective=chess.WHITE)

        # Black chooses the pawn recapture. White then declines Rxd5 because
        # clearing the d-file would expose that rook to ...Rxd5.
        assert result.status is ExchangeStatus.COMPLETED
        assert result.line == ("e4d5", "c6d5")
        assert result.material_result == 8
        assert result.nodes >= 5
        replay(fen, result.line)

    asyncio.run(run())


def test_attacked_target_excludes_illegal_king_recapture() -> None:
    async def run() -> None:
        result = await evaluate(FIXTURES["illegal_king_recapture"], "f4d5", perspective=chess.WHITE)
        assert result.status is ExchangeStatus.COMPLETED
        assert result.line == ("f4d5",)
        assert result.material_result == 1

    asyncio.run(run())


def test_only_legal_noncheck_move_forces_target_recapture() -> None:
    async def run() -> None:
        fen = FIXTURES["forced_noncheck_recapture"]
        result = await evaluate(fen, "b1b7", perspective=chess.WHITE)
        assert result.status is ExchangeStatus.COMPLETED
        assert result.line == ("b1b7", "a8b7")
        assert result.material_result == 0
        replay(fen, result.line)

    asyncio.run(run())


def test_non_target_check_evasion_is_unsupported_instead_of_stand_pat() -> None:
    async def run() -> None:
        result = await evaluate(FIXTURES["checking_capture"], "b5d7", perspective=chess.WHITE)
        assert result.status is ExchangeStatus.UNSUPPORTED
        assert result.material_result is None
        assert result.line == ()

    asyncio.run(run())


def test_terminal_capture_is_unsupported_by_local_material_model() -> None:
    async def run() -> None:
        result = await evaluate(FIXTURES["terminal_capture"], "e4d5", perspective=chess.WHITE)
        assert result.status is ExchangeStatus.UNSUPPORTED
        assert result.material_result is None

    asyncio.run(run())


def test_node_and_deadline_limits_are_incomplete_not_zero() -> None:
    async def run() -> None:
        limited = await evaluate(FIXTURES["basic_recapture"], "e4d5", perspective=chess.WHITE, node_limit=1)
        board = chess.Board(FIXTURES["basic_recapture"])
        expired = await evaluate_exchange(
            board,
            chess.Move.from_uci("e4d5"),
            perspective=chess.WHITE,
            deadline=0.0,
            monotonic=lambda: 0.0,
        )
        assert limited.status is ExchangeStatus.INCOMPLETE
        assert limited.limit_reached is ExchangeLimit.NODES
        assert limited.material_result is None
        assert expired.status is ExchangeStatus.INCOMPLETE
        assert expired.limit_reached is ExchangeLimit.DEADLINE
        assert expired.material_result is None

    asyncio.run(run())


def test_invalid_or_non_capture_root_move_is_a_caller_error() -> None:
    async def run() -> None:
        board = chess.Board()
        with pytest.raises(ValueError, match="capture"):
            await evaluate_exchange(
                board,
                chess.Move.from_uci("e2e4"),
                perspective=chess.WHITE,
                deadline=1.0,
                monotonic=lambda: 0.0,
            )
        with pytest.raises(ValueError, match="legal"):
            await evaluate_exchange(
                board,
                chess.Move.from_uci("e2e5"),
                perspective=chess.WHITE,
                deadline=1.0,
                monotonic=lambda: 0.0,
            )
        for invalid_limit in (True, 1.5, 0, 4097):
            with pytest.raises(ValueError, match="node_limit"):
                await evaluate_exchange(
                    chess.Board(FIXTURES["basic_recapture"]),
                    chess.Move.from_uci("e4d5"),
                    perspective=chess.WHITE,
                    deadline=1.0,
                    monotonic=lambda: 0.0,
                    node_limit=invalid_limit,  # type: ignore[arg-type]
                )
        with pytest.raises(ValueError, match="finite"):
            await evaluate_exchange(
                chess.Board(FIXTURES["basic_recapture"]),
                chess.Move.from_uci("e4d5"),
                perspective=chess.WHITE,
                deadline=float("inf"),
                monotonic=lambda: 0.0,
            )

    asyncio.run(run())


def test_task_cancellation_propagates_at_32_position_checkpoint() -> None:
    async def run() -> None:
        board = chess.Board(FIXTURES["cooperative_cancellation"])
        clock_calls = 0

        def clock() -> float:
            nonlocal clock_calls
            clock_calls += 1
            return 0.0

        task = asyncio.create_task(evaluate_exchange(
            board,
            chess.Move.from_uci("e3d4"),
            perspective=chess.WHITE,
            deadline=1.0,
            monotonic=clock,
        ))
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert clock_calls == 32
        assert board.fen() == FIXTURES["cooperative_cancellation"]

    asyncio.run(run())
