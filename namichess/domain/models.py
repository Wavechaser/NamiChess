"""Immutable references shared by application and analysis layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionId:
    document_id: int
    game_number: int
    node_path: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SquareRef:
    position_id: PositionId
    square: str


@dataclass(frozen=True, slots=True)
class PositionContext:
    """A selected position and the legal history that produced it."""

    document_id: int
    game_number: int
    node_path: tuple[int, ...]
    starting_fen: str
    moves: tuple[str, ...]
    current_fen: str
    has_history: bool

    @property
    def position_id(self) -> PositionId:
        return PositionId(self.document_id, self.game_number, self.node_path)


@dataclass(frozen=True, slots=True)
class PieceId:
    """Stable identity for a piece within one imported document and game."""

    document_id: int
    game_number: int
    origin_square: str
    color: str
    original_piece_type: str


@dataclass(frozen=True, slots=True)
class PiecePlacement:
    """A piece identity at the selected position."""

    piece_id: PieceId
    square: str
    color: str
    piece_type: str
    promoted: bool
