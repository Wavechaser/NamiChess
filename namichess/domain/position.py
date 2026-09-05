"""Shared reconstruction of a position and stable piece placements."""

from __future__ import annotations

import chess

from .models import PieceId, PiecePlacement, PositionContext
from .validation import parse_fen


def replay_position(context: PositionContext) -> tuple[chess.Board, tuple[PiecePlacement, ...]]:
    """Rebuild a selected position from its root and legal move history."""
    board = parse_fen(context.starting_fen)
    identities = {
        square: PieceId(
            context.document_id,
            context.game_number,
            chess.square_name(square),
            _color_name(piece.color),
            chess.piece_name(piece.piece_type),
        )
        for square, piece in board.piece_map().items()
    }
    promoted: set[PieceId] = set()
    for uci in context.moves:
        try:
            move = board.parse_uci(uci)
        except ValueError as error:
            raise ValueError(f"position history contains illegal move {uci!r}") from error
        identity = identities.pop(move.from_square)
        if board.is_en_passant(move):
            captured = move.to_square - 8 if board.turn == chess.WHITE else move.to_square + 8
            identities.pop(captured)
        else:
            identities.pop(move.to_square, None)
        if board.is_castling(move):
            rank = chess.square_rank(move.from_square)
            rook_from = chess.square(7 if move.to_square > move.from_square else 0, rank)
            rook_to = chess.square(5 if move.to_square > move.from_square else 3, rank)
            identities[rook_to] = identities.pop(rook_from)
        identities[move.to_square] = identity
        if move.promotion is not None:
            promoted.add(identity)
        board.push(move)
    if board.fen(en_passant="fen") != context.current_fen:
        raise ValueError("current FEN does not match the replayed root and move history")
    placements = tuple(
        PiecePlacement(
            identities[square], chess.square_name(square), _color_name(piece.color),
            chess.piece_name(piece.piece_type), identities[square] in promoted,
        )
        for square, piece in sorted(board.piece_map().items())
    )
    return board, placements


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"
