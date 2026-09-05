"""Validation for standard-chess positions, including composed material."""

from __future__ import annotations

import chess
import re


class PositionValidationError(ValueError):
    """A position cannot be used under NamiChess's standard-chess rules."""


_ALLOWED_STATUS = (
    chess.STATUS_TOO_MANY_WHITE_PAWNS
    | chess.STATUS_TOO_MANY_BLACK_PAWNS
    | chess.STATUS_TOO_MANY_WHITE_PIECES
    | chess.STATUS_TOO_MANY_BLACK_PIECES
)


def parse_fen(fen: str) -> chess.Board:
    """Parse a complete FEN without repairing invalid state."""

    fields = fen.split()
    if len(fields) != 6:
        raise PositionValidationError(
            "FEN must contain exactly six fields; correct the FEN and reload"
        )
    placement, turn, castling, ep, halfmove, fullmove = fields
    ranks = placement.split("/")
    placement_ok = len(ranks) == 8
    for rank in ranks:
        if not re.fullmatch(r"[prnbqkPRNBQK1-8]+", rank):
            placement_ok = False
            break
        if sum(int(char) if char.isdigit() else 1 for char in rank) != 8:
            placement_ok = False
            break
    halfmove_ok = bool(re.fullmatch(r"0|[1-9][0-9]{0,9}", halfmove, re.ASCII))
    fullmove_ok = bool(re.fullmatch(r"[1-9][0-9]{0,9}", fullmove, re.ASCII))
    if halfmove_ok:
        halfmove_ok = int(halfmove) <= 1_000_000_000
    if fullmove_ok:
        fullmove_ok = int(fullmove) <= 1_000_000_000
    checks = (
        (placement_ok, "piece placement must describe eight ranks of eight squares"),
        (turn in {"w", "b"}, "side to move must be w or b"),
        (bool(re.fullmatch(r"-|K?Q?k?q?", castling)), "castling must be - or unique KQkq rights in that order"),
        (bool(re.fullmatch(r"-|[a-h][36]", ep)), "en-passant target must be - or a square on rank 3 or 6"),
        (halfmove_ok, "halfmove counter must be a decimal integer from 0 to 1000000000 without leading zeros"),
        (fullmove_ok, "fullmove counter must be a decimal integer from 1 to 1000000000 without leading zeros"),
    )
    for accepted, problem in checks:
        if not accepted:
            raise PositionValidationError(f"invalid FEN: {problem}; correct the FEN and reload")
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise PositionValidationError(
            f"invalid FEN: {exc}; correct the FEN and reload"
        ) from exc

    status = board.status() & ~_ALLOWED_STATUS
    if status != chess.STATUS_VALID:
        problems = ", ".join(
            member.name.lower().replace("_", " ")
            for member in chess.Status
            if member and member & status
        )
        raise PositionValidationError(
            f"invalid FEN state: {problems}; correct the FEN and reload"
        )
    return board
