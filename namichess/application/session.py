"""Navigable in-memory chess document session."""

from __future__ import annotations

import dataclasses
import itertools

import chess
import chess.pgn

from namichess.analysis.static import move_delta, position_facts
from namichess.application.analysis import AnalysisController
from namichess.application.imports import (
    ImportedDocument,
    import_fen_text,
    import_pgn_text,
)
from namichess.application.views import GameSummary, PositionStatus, SessionView
from namichess.domain.models import PositionContext


class SessionError(ValueError):
    """A session command cannot be completed."""


_document_ids = itertools.count(1)


class Session:
    def __init__(self) -> None:
        self._document: ImportedDocument | None = None
        self._document_id = 0
        self._game_index = 0
        self._node: chess.pgn.GameNode | None = None
        self._revision = 0

    @property
    def loaded(self) -> bool:
        return self._document is not None

    def load_fen(self, fen: str) -> SessionView:
        return self._replace(import_fen_text(fen))

    def load_pgn(self, pgn: str) -> SessionView:
        return self._replace(import_pgn_text(pgn))

    def _replace(self, document: ImportedDocument) -> SessionView:
        node: chess.pgn.GameNode = document.games[0]
        while node.variations:
            node = node.variations[0]
        previous = (self._document, self._document_id, self._game_index, self._node, self._revision)
        self._document = document
        self._document_id = next(_document_ids)
        self._game_index = 0
        self._node = node
        self._revision += 1
        try:
            return self.view()
        except Exception:
            self._document, self._document_id, self._game_index, self._node, self._revision = previous
            raise

    def select_game(self, number: int) -> SessionView:
        document = self._require_document()
        if not 1 <= number <= len(document.games):
            raise SessionError(f"game must be between 1 and {len(document.games)}")
        node: chess.pgn.GameNode = document.games[number - 1]
        while node.variations:
            node = node.variations[0]
        return self._select(number - 1, node)

    def start(self) -> SessionView:
        document = self._require_document()
        return self._select(self._game_index, document.games[self._game_index])

    def end(self) -> SessionView:
        node = self._require_node()
        while node.variations:
            node = node.variations[0]
        return self._select(self._game_index, node)

    def next(self) -> SessionView:
        node = self._require_node()
        if not node.variations:
            raise SessionError("already at the end of this line")
        return self._select(self._game_index, node.variations[0])

    def back(self) -> SessionView:
        node = self._require_node()
        if node.parent is None:
            raise SessionError("already at the starting position")
        return self._select(self._game_index, node.parent)

    def goto(self, ply: int) -> SessionView:
        if ply < 0:
            raise SessionError("ply must be nonnegative")
        node = self._require_node()
        current = node.ply() - node.game().ply()
        while current > ply and node.parent is not None:
            node = node.parent
            current -= 1
        while current < ply and node.variations:
            node = node.variations[0]
            current += 1
        if current != ply:
            raise SessionError(f"ply {ply} is not available from the selected line")
        return self._select(self._game_index, node)

    def variation(self, number: int) -> SessionView:
        node = self._require_node()
        if not 1 <= number <= len(node.variations):
            raise SessionError(f"variation must be between 1 and {len(node.variations)}")
        return self._select(self._game_index, node.variations[number - 1])

    def play(self, notation: str) -> SessionView:
        node = self._require_node()
        board = node.board()
        try:
            move = chess.Move.from_uci(notation)
            if move not in board.legal_moves:
                raise ValueError
        except ValueError:
            try:
                move = board.parse_san(notation)
            except ValueError as exc:
                raise SessionError(f"{notation!r} is not a legal unambiguous SAN or UCI move") from exc
            if move == chess.Move.null() or move not in board.legal_moves:
                raise SessionError(f"{notation!r} is not a legal unambiguous SAN or UCI move")
        for child in node.variations:
            if child.move == move:
                return self._select(self._game_index, child)
        return self._select(self._game_index, node.add_variation(move))

    def resolve_moves(self, notations: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve legal SAN/UCI moves at the selected node without moving it."""
        board = self._require_node().board()
        resolved: list[str] = []
        for notation in notations:
            try:
                move = chess.Move.from_uci(notation)
                if move not in board.legal_moves:
                    raise ValueError
            except ValueError:
                try:
                    move = board.parse_san(notation)
                except ValueError as exc:
                    raise SessionError(f"{notation!r} is not a legal unambiguous SAN or UCI move") from exc
            uci = move.uci()
            if uci in resolved:
                raise SessionError("compare requires two distinct legal moves")
            resolved.append(uci)
        return tuple(resolved)

    def request_analysis(
        self,
        controller: AnalysisController,
        *,
        view: SessionView | None = None,
        compare: tuple[str, ...] = (),
    ) -> SessionView:
        """Submit analysis and return the revision-safe shared application view."""
        current = self._current_view(view)
        moves = self.resolve_moves(compare) if compare else ()
        controller.submit(current.position, current.revision, moves)
        return self.analysis_view(controller, view=current)

    def analysis_view(
        self,
        controller: AnalysisController,
        *,
        view: SessionView | None = None,
    ) -> SessionView:
        """Attach only analysis belonging to the selected session revision."""
        current = view or self.view()
        result = controller.latest
        if result is not None and result.revision != current.revision:
            result = None
        return dataclasses.replace(current, analysis=result)

    def _current_view(self, supplied: SessionView | None) -> SessionView:
        if supplied is None:
            return self.view()
        if supplied.revision != self._revision or supplied.position != self._context(self._require_node()):
            raise SessionError("analysis view is stale; request analysis from the current position")
        return supplied

    def view(self) -> SessionView:
        document = self._require_document()
        node = self._require_node()
        game = document.games[self._game_index]
        board = node.board()
        context = self._context(node)
        facts = position_facts(context)
        previous_move = None
        if node.parent is not None:
            previous_move = move_delta(self._context(node.parent), context)
        summaries = tuple(
            GameSummary(
                number=index + 1,
                headers=tuple(candidate.headers.items()),
                recorded_result=candidate.headers.get("Result"),
            )
            for index, candidate in enumerate(document.games)
        )
        variations = tuple(board.san(child.move) for child in node.variations)
        outcome = board.outcome(claim_draw=False)
        return SessionView(
            revision=self._revision,
            games=summaries,
            selected_game=self._game_index + 1,
            selected_ply=node.ply() - game.ply(),
            position=context,
            facts=facts,
            previous_move=previous_move,
            pieces=facts.pieces,
            board_rows=_board_rows(board),
            turn="white" if board.turn else "black",
            status=_position_status(board),
            outcome=outcome.result() if outcome else None,
            can_claim_fifty_moves=board.can_claim_fifty_moves(),
            can_claim_threefold_repetition=board.can_claim_threefold_repetition(),
            variations=variations,
        )

    def _context(self, node: chess.pgn.GameNode) -> PositionContext:
        document = self._require_document()
        game = document.games[self._game_index]
        board = node.board()
        return PositionContext(
            document_id=self._document_id,
            game_number=self._game_index + 1,
            node_path=_node_path(node),
            starting_fen=game.board().fen(en_passant="fen"),
            moves=tuple(ancestor.move.uci() for ancestor in _node_chain(node)[1:]),
            current_fen=board.fen(en_passant="fen"),
            has_history=document.has_history,
        )

    def _select(self, game_index: int, node: chess.pgn.GameNode) -> SessionView:
        if game_index != self._game_index or node is not self._node:
            self._revision += 1
        self._game_index = game_index
        self._node = node
        return self.view()

    def _require_document(self) -> ImportedDocument:
        if self._document is None:
            raise SessionError("no position is loaded; use load or fen first")
        return self._document

    def _require_node(self) -> chess.pgn.GameNode:
        self._require_document()
        assert self._node is not None
        return self._node


def _node_chain(node: chess.pgn.GameNode) -> list[chess.pgn.GameNode]:
    chain: list[chess.pgn.GameNode] = []
    while node is not None:
        chain.append(node)
        node = node.parent  # type: ignore[assignment]
    chain.reverse()
    return chain


def _node_path(node: chess.pgn.GameNode) -> tuple[int, ...]:
    path: list[int] = []
    while node.parent is not None:
        path.append(node.parent.variations.index(node))
        node = node.parent
    path.reverse()
    return tuple(path)


def _board_rows(board: chess.Board) -> tuple[str, ...]:
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            cells.append(piece.symbol() if piece else ".")
        rows.append(f"{rank + 1} " + " ".join(cells))
    rows.append("  a b c d e f g h")
    return tuple(rows)


def _position_status(board: chess.Board) -> PositionStatus:
    if board.is_checkmate():
        return PositionStatus.CHECKMATE
    if board.is_stalemate():
        return PositionStatus.STALEMATE
    if board.is_insufficient_material():
        return PositionStatus.INSUFFICIENT_MATERIAL
    if board.is_seventyfive_moves():
        return PositionStatus.SEVENTYFIVE_MOVES
    if board.is_fivefold_repetition():
        return PositionStatus.FIVEFOLD_REPETITION
    if board.is_check():
        return PositionStatus.CHECK
    return PositionStatus.ACTIVE
