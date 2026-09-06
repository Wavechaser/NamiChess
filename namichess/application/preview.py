"""Read-only candidate-line views shared by CLI and future GUI adapters."""

from __future__ import annotations

from dataclasses import dataclass

import chess

from namichess.analysis.static import MoveDelta, PositionFacts, move_delta, position_facts
from namichess.application.analysis import CandidateResult
from namichess.analysis.continuations import continuation_context
from namichess.application.views import SessionView
from namichess.domain.models import PositionContext, PositionId
from namichess.domain.position import replay_position


class PreviewError(ValueError):
    """A candidate continuation cannot be previewed from this shared view."""


@dataclass(frozen=True, slots=True)
class CandidateLinePreview:
    """One reconstructed candidate position, without changing the session."""

    revision: int
    candidate: CandidateResult
    ply: int
    context: PositionContext
    facts: PositionFacts
    previous_move: MoveDelta | None
    source_position_id: PositionId
    parent_position_id: PositionId | None
    child_position_id: PositionId | None
    board_rows: tuple[str, ...]


def preview_candidate_line(view: SessionView, candidate_number: int, ply: int) -> CandidateLinePreview:
    """Reconstruct one current candidate ply from its legal shared context."""
    analysis = view.analysis
    if analysis is None or analysis.revision != view.revision:
        raise PreviewError("no current analysis line is available")
    if not 1 <= candidate_number <= len(analysis.candidates):
        raise PreviewError(f"candidate number must be between 1 and {len(analysis.candidates)}")
    candidate = analysis.candidates[candidate_number - 1]
    if candidate.position_id != view.position.position_id:
        raise PreviewError("candidate belongs to a different position")
    if not 0 <= ply <= len(candidate.pv):
        raise PreviewError(f"ply must be between 0 and {len(candidate.pv)} for this candidate")
    if not candidate.pv or candidate.pv[0] != candidate.uci:
        raise PreviewError("candidate line does not begin with the candidate move")

    board, _ = replay_position(view.position)
    contexts = [view.position]
    moves = list(view.position.moves)
    for index, uci in enumerate(candidate.pv, 1):
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise PreviewError(f"candidate line contains invalid move {uci!r}") from exc
        if move not in board.legal_moves:
            raise PreviewError(f"candidate line contains illegal move {uci!r}")
        board.push(move)
        moves.append(uci)
        contexts.append(continuation_context(view.position, analysis.request_id, tuple(moves), board))

    current = contexts[ply]
    parent = contexts[ply - 1] if ply else None
    child = contexts[ply + 1] if ply < len(candidate.pv) else None
    return CandidateLinePreview(
        revision=view.revision,
        candidate=candidate,
        ply=ply,
        context=current,
        facts=position_facts(current),
        previous_move=move_delta(parent, current) if parent is not None else None,
        source_position_id=view.position.position_id,
        parent_position_id=parent.position_id if parent is not None else None,
        child_position_id=child.position_id if child is not None else None,
        board_rows=_board_rows(board, len(candidate.pv) - ply),
    )


def _board_rows(board: chess.Board, undo: int) -> tuple[str, ...]:
    preview = board.copy(stack=True)
    for _ in range(undo):
        preview.pop()
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            piece = preview.piece_at(chess.square(file, rank))
            cells.append(piece.symbol() if piece else ".")
        rows.append(f"{rank + 1} " + " ".join(cells))
    return tuple((*rows, "  a b c d e f g h"))
