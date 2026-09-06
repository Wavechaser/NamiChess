"""Resolve user move notation without weakening chess legality."""

from __future__ import annotations

import chess


def resolve_legal_move(board: chess.Board, notation: str) -> chess.Move:
    """Resolve UCI, canonical SAN, or uniquely matching relaxed SAN."""
    try:
        move = chess.Move.from_uci(notation.lower())
    except ValueError:
        pass
    else:
        if move != chess.Move.null() and move in board.legal_moves:
            return move

    try:
        move = board.parse_san(notation)
    except ValueError:
        pass
    else:
        if move != chess.Move.null() and move in board.legal_moves and board.san(move) == notation:
            return move

    legal = tuple((move, board.san(move)) for move in board.legal_moves)
    matches = [move for move, san in legal if relaxed_san_matches(notation, san)]
    if len(matches) != 1:
        raise ValueError(f"{notation!r} is not a legal unambiguous SAN or UCI move")
    return matches[0]


def relaxed_san_matches(notation: str, canonical_san: str) -> bool:
    """Whether notation differs only by case or omitted move-effect markers."""
    variants = {canonical_san.casefold()}
    if canonical_san.endswith(("+", "#")):
        variants.add(canonical_san[:-1].casefold())
    variants.update(candidate.replace("x", "") for candidate in tuple(variants))
    return notation.casefold() in variants
