from __future__ import annotations

import asyncio

import chess
import pytest

from namichess.analysis.exchange import evaluate_exchange
from namichess.analysis.local import LocalExit, LocalLimit, LocalLimits, LocalTermination, _Explorer, explore_local
from namichess.application.analysis import AnalysisController, ProbeSubject
from namichess.application.session import Session
from namichess.domain.models import PieceId, PositionContext


def context(fen: str) -> PositionContext:
    return PositionContext(1, 1, (), fen, (), fen, False)


def test_local_roots_are_deterministic_and_promotion_complete() -> None:
    async def exercise() -> None:
        position = context("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        result = await explore_local(
            position, limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
        )
        assert tuple(root.root_uci for root in result.roots) == (
            "a7a8q", "a7a8r", "a7a8b", "a7a8n",
        )
        assert result.omitted_legal_moves == tuple(sorted(move.uci() for move in chess.Board(position.current_fen).legal_moves if move.from_square != chess.A7))

    asyncio.run(exercise())


def test_piece_probe_covers_all_piece_exits_and_replays_continuity() -> None:
    async def exercise() -> None:
        position = context(chess.STARTING_FEN)
        result = await explore_local(
            position,
            limits=LocalLimits(),
            deadline=10.0,
            monotonic=lambda: 0.0,
            piece_square="g1",
        )
        assert tuple(root.root_uci for root in result.roots) == ("g1f3", "g1h3")
        for root in result.roots:
            assert root.examined_reply_count == root.legal_reply_count
            for line in root.lines:
                assert line.moves[0] == root.root_uci
                assert tuple(delta.uci for delta in line.deltas) == line.moves
                assert line.exit in (LocalExit.EXAMINED, LocalExit.WITNESSED_MATE)

    asyncio.run(exercise())


def test_node_limit_reports_unresolved_omissions_without_escape() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context(chess.STARTING_FEN),
            limits=LocalLimits(node_limit=2),
            deadline=10.0,
            monotonic=lambda: 0.0,
            root_moves=("e2e4",),
        )
        assert result.nodes == 2
        assert result.limit_reached is LocalLimit.NODES
        assert result.omitted_legal_moves
        assert result.roots[0].lines[0].exit is LocalExit.UNRESOLVED

    asyncio.run(exercise())


def test_nested_exchange_uses_the_same_node_allowance() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context("7k/8/2p5/3p4/4Q3/8/8/4K3 w - - 0 1"),
            limits=LocalLimits(node_limit=2), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("e4d5",),
        )
        assert result.nodes == 2
        assert result.limit_reached is LocalLimit.NODES
        assert result.roots[0].exchange is not None
        assert result.roots[0].exchange.status.value == "incomplete"

    asyncio.run(exercise())


def test_immediate_capture_reply_carries_model_scoped_exchange() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context("4k3/8/8/3p4/8/8/4P3/4K3 w - - 0 1"),
            limits=LocalLimits(), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("e2e4",),
        )
        capture = next(line for line in result.roots[0].lines if line.moves[:2] == ("e2e4", "d5e4"))
        assert capture.reply_exchange is not None
        assert capture.reply_exchange.line[:2] == ("d5e4",)
        assert capture.reply_exchange.material_result == -1

    asyncio.run(exercise())


def test_explorer_yields_at_the_shared_32_node_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    yields = 0

    async def counted_sleep(delay: float) -> None:
        nonlocal yields
        assert delay == 0
        yields += 1

    monkeypatch.setattr("namichess.analysis.local.asyncio.sleep", counted_sleep)

    async def exercise() -> None:
        result = await explore_local(
            context(chess.STARTING_FEN),
            limits=LocalLimits(node_limit=96),
            deadline=10.0,
            monotonic=lambda: 0.0,
            piece_square="g1",
        )
        assert result.nodes >= 32
        assert yields == result.nodes // 32

    asyncio.run(exercise())


def test_nested_see_entered_at_node_31_yields_on_aggregate_node_32(monkeypatch: pytest.MonkeyPatch) -> None:
    yields = 0

    async def counted_sleep(delay: float) -> None:
        nonlocal yields
        yields += 1

    monkeypatch.setattr("namichess.analysis.local.asyncio.sleep", counted_sleep)

    async def exercise() -> None:
        position = context("7k/8/2p5/3p4/4Q3/8/8/4K3 w - - 0 1")
        explorer = _Explorer(position, LocalLimits(), 10.0, lambda: 0.0, lambda: False, 1)
        explorer.nodes = 31
        board = chess.Board(position.current_fen)
        await evaluate_exchange(
            board, chess.Move.from_uci("e4d5"), perspective=chess.WHITE,
            deadline=10.0, monotonic=lambda: 0.0, cooperate=explorer.checkpoint,
        )
        assert explorer.nodes >= 32
        assert yields >= 1

    asyncio.run(exercise())


def test_deadline_stops_before_expansion() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context(chess.STARTING_FEN),
            limits=LocalLimits(), deadline=1.0, monotonic=lambda: 1.0,
        )
        assert result.nodes == 0
        assert result.limit_reached is LocalLimit.DEADLINE
        assert not result.roots

    asyncio.run(exercise())


def test_depth_one_records_only_the_root_and_omits_every_reply() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context(chess.STARTING_FEN), limits=LocalLimits(max_depth=1),
            deadline=10.0, monotonic=lambda: 0.0, root_moves=("e2e4",),
        )
        root = result.roots[0]
        assert root.examined_reply_count == 0
        assert len(root.omitted_replies) == root.legal_reply_count
        assert root.lines[0].moves == ("e2e4",)
        assert root.lines[0].termination is LocalTermination.DEPTH

    asyncio.run(exercise())


def test_terminal_root_has_zero_of_zero_reply_coverage() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"), limits=LocalLimits(),
            deadline=10.0, monotonic=lambda: 0.0, root_moves=("f7g7",),
        )
        root = result.roots[0]
        assert root.legal_reply_count == root.examined_reply_count == 0
        assert root.omitted_replies == ()
        assert root.lines[0].termination is LocalTermination.TERMINAL
        assert root.lines[0].exit is LocalExit.EXAMINED

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "fen,root",
    (
        ("r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1", "b7a8b"),
        ("4k3/8/8/8/8/8/1p6/R3K3 b - - 0 1", "b2a1b"),
    ),
)
def test_root_that_reaches_insufficient_material_has_no_fictional_replies(fen: str, root: str) -> None:
    async def exercise() -> None:
        result = await explore_local(
            context(fen), limits=LocalLimits(max_depth=1), deadline=10.0,
            monotonic=lambda: 0.0, root_moves=(root,),
        )
        evidence = result.roots[0]
        assert evidence.legal_reply_count == evidence.examined_reply_count == 0
        assert evidence.omitted_replies == ()
        assert len(evidence.lines) == 1
        assert evidence.lines[0].moves == (root,)
        assert evidence.lines[0].termination is LocalTermination.TERMINAL
    asyncio.run(exercise())


def test_automatic_seventyfive_move_draw_stops_after_root_but_claimable_fifty_does_not() -> None:
    async def exercise() -> None:
        automatic = await explore_local(
            context("7k/8/8/8/8/8/8/R6K w - - 149 1"),
            limits=LocalLimits(max_depth=1), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("a1a2",),
        )
        assert automatic.roots[0].legal_reply_count == 0
        assert automatic.roots[0].lines[0].termination is LocalTermination.TERMINAL

        claimable = await explore_local(
            context("7k/8/8/8/8/8/8/R6K w - - 99 1"),
            limits=LocalLimits(max_depth=1), deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("a1a2",),
        )
        assert claimable.roots[0].legal_reply_count > 0
        assert claimable.roots[0].lines[0].termination is LocalTermination.DEPTH
    asyncio.run(exercise())


def test_fivefold_repetition_stops_after_the_repeating_root() -> None:
    moves = ("g1f3", "g8f6", "f3g1", "f6g8") * 3 + ("g1f3", "g8f6", "f3g1")
    board = chess.Board()
    for move in moves:
        board.push_uci(move)
    position = PositionContext(1, 1, (), chess.STARTING_FEN, moves, board.fen(en_passant="fen"), True)

    async def exercise() -> None:
        result = await explore_local(
            position, limits=LocalLimits(max_depth=1), deadline=10.0,
            monotonic=lambda: 0.0, root_moves=("f6g8",),
        )
        root = result.roots[0]
        assert root.legal_reply_count == root.examined_reply_count == 0
        assert root.lines[0].termination is LocalTermination.TERMINAL
    asyncio.run(exercise())


def test_terminal_source_returns_no_roots_or_omitted_moves_even_when_focused() -> None:
    async def exercise() -> None:
        result = await explore_local(
            context("7k/8/8/8/8/8/8/K7 w - - 0 1"), limits=LocalLimits(),
            deadline=10.0, monotonic=lambda: 0.0,
            root_moves=("a1a2",), piece_square="a1",
        )
        assert result.roots == ()
        assert result.omitted_legal_moves == ()
        assert result.nodes == 0
    asyncio.run(exercise())


@pytest.mark.parametrize("field,value", (("max_depth", 1.5), ("node_limit", 2.0), ("max_depth", True)))
def test_limits_require_real_integers(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        LocalLimits(**{field: value})  # type: ignore[arg-type]


class _UnusedEngine:
    async def prepare(self):
        raise AssertionError("invalid probe must not submit")


def test_session_rejects_opponent_and_illegal_probe_before_controller_mutation() -> None:
    session = Session()
    view = session.load_fen(chess.STARTING_FEN)
    controller = AnalysisController(_UnusedEngine())
    black_pawn = next(piece.piece_id for piece in view.pieces if piece.square == "a7")

    with pytest.raises(ValueError, match="side to move"):
        session.request_probe(controller, ProbeSubject.for_piece(black_pawn), view=view)
    assert controller.latest is None

    with pytest.raises(ValueError, match="legal UCI"):
        session.request_probe(controller, ProbeSubject.for_move("e2e5"), view=view)
    assert controller.latest is None


def test_controller_rejects_absent_piece_before_incrementing_request() -> None:
    controller = AnalysisController(_UnusedEngine())
    absent = PieceId(99, 1, "a2", "white", "pawn")
    with pytest.raises(ValueError, match="not present"):
        controller.submit_probe(context(chess.STARTING_FEN), 3, ProbeSubject.for_piece(absent))
    assert controller.latest is None


def test_session_rejects_stale_probe_view_before_controller_mutation() -> None:
    session = Session()
    stale = session.load_fen("7k/8/8/8/8/8/8/R6K w - - 0 1")
    session.play("Ra2")
    controller = AnalysisController(_UnusedEngine())
    with pytest.raises(ValueError, match="stale"):
        session.request_probe(controller, ProbeSubject.for_move("a1a2"), view=stale)
    assert controller.latest is None
