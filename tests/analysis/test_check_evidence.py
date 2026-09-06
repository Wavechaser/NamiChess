from __future__ import annotations

import chess
import pytest

import namichess.application.analysis as analysis_module
from namichess.analysis.engine import EngineCandidate, EngineScore, ScoreBound
from namichess.analysis.evidence import line_consequences
from namichess.analysis.static import move_delta, position_facts
from namichess.domain import PositionContext


def context(fen: str, moves: tuple[str, ...] = ()) -> PositionContext:
    board = chess.Board(fen)
    for uci in moves:
        board.push_uci(uci)
    return PositionContext(17, 1, tuple(range(len(moves))), fen, moves, board.fen(en_passant="fen"), bool(moves))


def placement_id(position: PositionContext, square: str):
    return next(piece.piece_id for piece in position_facts(position).pieces if piece.square == square)


@pytest.mark.parametrize(
    ("fen", "uci", "checker_squares", "king_square", "mover_is_checker"),
    (
        ("3k4/8/8/8/8/8/4R3/4K3 w - - 0 1", "e2d2", ("d2",), "d8", True),
        ("4k3/8/8/8/8/8/4B3/K3R3 w - - 0 1", "e2d3", ("e1",), "e8", False),
        ("4k3/8/8/8/8/8/4B3/K3R3 w - - 0 1", "e2b5", ("e1", "b5"), "e8", True),
        ("3K4/4r3/8/8/8/8/8/3k4 b - - 0 1", "e7d7", ("d7",), "d8", True),
        ("k3r3/4b3/8/8/8/8/8/4K3 b - - 0 1", "e7d6", ("e8",), "e1", False),
        ("k3r3/4b3/8/8/8/8/8/4K3 b - - 0 1", "e7b4", ("b4", "e8"), "e1", True),
    ),
)
def test_check_evidence_names_actual_post_move_roles(
    fen: str, uci: str, checker_squares: tuple[str, ...], king_square: str, mover_is_checker: bool,
) -> None:
    before = context(fen)
    after = context(fen, (uci,))
    delta = move_delta(before, after)
    consequence = line_consequences(chess.Board(fen), (uci,), (delta,))[0]

    assert consequence.gives_check
    assert consequence.checked_king == placement_id(after, king_square)
    assert consequence.checked_king_square is not None
    assert (consequence.checked_king_square.position_id, consequence.checked_king_square.square) == (
        after.position_id, king_square,
    )
    assert consequence.checkers == tuple(placement_id(after, square) for square in checker_squares)
    assert tuple((square.position_id, square.square) for square in consequence.checker_squares) == tuple(
        (after.position_id, square) for square in checker_squares
    )
    assert (consequence.mover in consequence.checkers) is mover_is_checker


def test_non_check_has_no_check_role_evidence() -> None:
    fen = "4k3/8/8/8/8/8/R7/4K3 w - - 0 1"
    before = context(fen)
    after = context(fen, ("a2a3",))
    consequence = line_consequences(chess.Board(fen), ("a2a3",), (move_delta(before, after),))[0]

    assert not consequence.gives_check
    assert consequence.checked_king is None
    assert consequence.checked_king_square is None
    assert consequence.checkers == ()
    assert consequence.checker_squares == ()


def test_line_check_explanation_uses_checkers_and_after_position_squares() -> None:
    fen = "4k3/8/8/8/8/8/4B3/K3R3 w - - 0 1"
    uci = "e2b5"
    position = context(fen)
    candidate = EngineCandidate(EngineScore(0, None, None, ScoreBound.EXACT), (uci,), 10, 100, 0.1)

    _, explanations, evidence = analysis_module._assemble(
        1, 1, chess.Board(fen), position, (uci,), {uci: candidate}, (),
    )
    line = next(item for item in evidence if item.kind == "engine_line").consequences[0]
    explanation = next(item for item in explanations if item.catalog_id == "line.check")

    assert explanation.pieces == line.checkers
    assert explanation.pieces != (line.mover,)
    assert explanation.squares == (*line.checker_squares, line.checked_king_square)
    assert all(square.position_id == line.target.position_id for square in explanation.squares)
