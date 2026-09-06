"""Interface-local board orientation state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Orientation(str, Enum):
    WHITE = "white"
    BLACK = "black"
    TURN = "turn"


class ResolvedOrientation(str, Enum):
    WHITE = "white"
    BLACK = "black"


def resolve_orientation(preference: Orientation, turn: str) -> ResolvedOrientation:
    """Resolve an import preference against the imported position's turn."""
    if preference is Orientation.WHITE:
        return ResolvedOrientation.WHITE
    if preference is Orientation.BLACK:
        return ResolvedOrientation.BLACK
    if turn not in {"white", "black"}:
        raise ValueError("turn must be white or black")
    return ResolvedOrientation(turn)


@dataclass(slots=True)
class BoardDisplayState:
    """Mutable adapter state; it never changes a chess position or analysis."""

    orientation: ResolvedOrientation = ResolvedOrientation.WHITE

    def apply_import(self, preference: Orientation, turn: str) -> None:
        self.orientation = resolve_orientation(preference, turn)

    def flip(self) -> None:
        self.orientation = (
            ResolvedOrientation.BLACK
            if self.orientation is ResolvedOrientation.WHITE
            else ResolvedOrientation.WHITE
        )

    def set_orientation(self, orientation: ResolvedOrientation) -> None:
        self.orientation = orientation
