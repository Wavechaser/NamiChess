"""Immutable session views shared by command-line and future GUI adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from namichess.analysis.static import MoveDelta, PositionFacts
from namichess.analysis.consequences import MoveAccount
from namichess.application.analysis import AnalysisResult
from namichess.application.attention import AttentionSelection
from namichess.domain.models import PiecePlacement, PositionContext, PositionId


class PositionStatus(str, Enum):
    ACTIVE = "active"
    CHECK = "check"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    SEVENTYFIVE_MOVES = "seventyfive_moves"
    FIVEFOLD_REPETITION = "fivefold_repetition"


@dataclass(frozen=True, slots=True)
class GameSummary:
    number: int
    headers: tuple[tuple[str, str], ...]
    recorded_result: str | None


@dataclass(frozen=True, slots=True)
class SessionView:
    revision: int
    games: tuple[GameSummary, ...]
    selected_game: int
    selected_ply: int
    position: PositionContext
    facts: PositionFacts
    previous_move: MoveDelta | None
    move_account: MoveAccount | None
    pieces: tuple[PiecePlacement, ...]
    board_rows: tuple[str, ...]
    turn: str
    status: PositionStatus
    outcome: str | None
    can_claim_fifty_moves: bool
    can_claim_threefold_repetition: bool
    variations: tuple[str, ...]
    parent_position_id: PositionId | None = None
    child_position_ids: tuple[PositionId, ...] = ()
    analysis: AnalysisResult | None = None
    attention: AttentionSelection | None = None
