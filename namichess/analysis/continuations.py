"""Identity-preserving contexts for witnessed analysis continuations."""

from __future__ import annotations

import chess

from namichess.domain.models import PositionContext


def continuation_context(
    source: PositionContext,
    request_id: int,
    moves: tuple[str, ...],
    board: chess.Board,
) -> PositionContext:
    """Build the established synthetic identity for one witnessed position."""
    return PositionContext(
        source.document_id,
        source.game_number,
        source.node_path + (-1, request_id, *_encoded_path(moves)),
        source.starting_fen,
        moves,
        board.fen(en_passant="fen"),
        source.has_history,
    )


def _encoded_path(moves: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(value for uci in moves for value in (len(uci), *(ord(character) for character in uci)))
