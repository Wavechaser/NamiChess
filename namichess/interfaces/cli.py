"""Interactive command-line adapter for the navigable M1 session."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TextIO

import chess
from namichess.analysis.engine import EngineScore
from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.application.current import create_app_session
from prompt_toolkit.input import Input
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.output import Output
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.patch_stdout import patch_stdout

from namichess.application.imports import ImportError as ChessImportError
from namichess.analysis.consequences import ConsequenceKind, MoveAccount, resolve_raw_fact
from namichess.application.attention import AttentionKind, AttentionSelection
from namichess.application.analysis import AnalysisController, AnalysisResult, AnalysisState, CandidateResult
from namichess.analysis.evidence import Explanation
from namichess.analysis.static import ContactKind, MoveDelta, PieceContact
from namichess.application.session import Session, SessionError
from namichess.application.preview import CandidateLinePreview, PreviewError, preview_candidate_line
from namichess.application.views import SessionView
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.domain.models import PiecePlacement
from namichess.interfaces.files import read_chess_file
from namichess.interfaces.orientation import BoardDisplayState, Orientation, ResolvedOrientation
from namichess.interfaces.serialization import serialize_session_view
from namichess.interfaces.settings import DEFAULT_ORIENTATION, SettingsError, SettingsStore

MAX_COMMAND_CHARS = 16 * 1024


def configure_standard_streams() -> None:
    """Use the CLI's documented UTF-8 contract for native process streams."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def render_board(
    view: SessionView,
    orientation: ResolvedOrientation = ResolvedOrientation.WHITE,
    catalog: ExplanationCatalog | None = None,
) -> str:
    if catalog is None and (view.previous_move is not None or (view.attention and view.attention.items)):
        catalog = _load_catalog()
    lines = list(_oriented_board_rows(view.board_rows, orientation))
    lines.append(f"Orientation: {orientation.value}")
    lines.append(f"Turn: {view.turn}")
    lines.append(f"Status: {view.status.value}")
    if view.outcome:
        lines.append(f"Outcome: {view.outcome}")
    claims = []
    if view.can_claim_fifty_moves:
        claims.append("fifty-move draw")
    if view.can_claim_threefold_repetition:
        claims.append("threefold repetition")
    if claims:
        lines.append("Claimable: " + ", ".join(claims))
    attention, covered_sources = _attention_text(
        view.facts, view.attention, view.previous_move,
        catalog,
        check_explicit=view.status.value in {"check", "checkmate"}
        or bool(view.previous_move and view.previous_move.gives_check),
    )
    if attention:
        lines.append("Attention: " + "; ".join(attention))
    if view.previous_move is not None:
        lines.append(_delta_text(
            view.previous_move, account=view.move_account, catalog=catalog,
            covered_sources=covered_sources,
        ))
    if view.analysis is not None:
        lines.extend(_analysis_summary(view.analysis))
    return "\n".join(lines)


def _oriented_board_rows(
    rows: tuple[str, ...], orientation: ResolvedOrientation,
) -> tuple[str, ...]:
    if orientation is ResolvedOrientation.WHITE:
        return rows
    board_rows = []
    for row in reversed(rows[:8]):
        rank, cells = row.split(" ", 1)
        board_rows.append(f"{rank} " + " ".join(reversed(cells.split())))
    return tuple(board_rows + ["  h g f e d c b a"])


def render_analysis(result: AnalysisResult, catalog: ExplanationCatalog) -> str:
    lines = _analysis_summary(result)
    explanations = {item.explanation_id: item for item in result.explanations}
    evidence = {item.evidence_id: item for item in result.evidence}
    critical: list[str] = []
    ordinary: list[str] = []
    for explanation in sorted(result.explanations, key=_explanation_priority):
        candidate = next(
            (item for item in result.candidates if explanation.explanation_id in item.explanation_refs),
            None,
        )
        prefix = f"[{candidate.san}] " if candidate is not None else ""
        rendered = f"Fact: {prefix}{_render_fact(explanation, catalog, evidence)}"
        (critical if _explanation_priority(explanation)[0] < 3 else ordinary).append(rendered)
    assessments: list[str] = []
    for assessment in result.trapping:
        assessments.append("Fact: " + _render_assessment("assessment.trapping", assessment, catalog, result))
    for assessment in result.move_safety:
        assessments.append("Fact: " + _render_assessment("assessment.move_safety", assessment, catalog, result))
    for assessment in result.overload:
        assessments.append("Fact: " + _render_assessment("assessment.overload", assessment, catalog, result))
    lines.extend((*critical, *assessments, *ordinary)[:3])
    if result.candidates:
        lines.append("#  Rank  Move  Score  Summary")
    for number, candidate in enumerate(result.candidates, 1):
        candidate_explanations = [explanations[ref] for ref in candidate.explanation_refs if ref in explanations]
        summary = (
            catalog.render(min(candidate_explanations, key=_explanation_priority))
            if candidate_explanations
            else "No concrete explanation available."
        )
        lines.append(
            f"{number}  {candidate.rank if candidate.rank is not None else '-'}  {candidate.san}  "
            f"{_score_text(candidate)}  {summary}"
        )
    return "\n".join(lines)


def render_details(result: AnalysisResult, number: int, catalog: ExplanationCatalog) -> str:
    if not 1 <= number <= len(result.candidates):
        raise SessionError(f"candidate number must be between 1 and {len(result.candidates)}")
    candidate = result.candidates[number - 1]
    evidence = {item.evidence_id: item for item in result.evidence}
    explanations = {item.explanation_id: item for item in result.explanations}
    lines = [f"Candidate {number}: {candidate.san} ({candidate.uci})", f"Score: {_score_text(candidate)}"]
    for ref in candidate.explanation_refs:
        if ref in explanations:
            lines.append(catalog.render(explanations[ref]))
    for ref in candidate.evidence_refs:
        item = evidence.get(ref)
        if item is None:
            continue
        depth = "absent" if item.engine_depth is None else str(item.engine_depth)
        nodes = "absent" if item.engine_nodes is None else str(item.engine_nodes)
        elapsed = "absent" if item.engine_elapsed_seconds is None else f"{item.engine_elapsed_seconds:.2f}s"
        lines.append(f"Evidence: {item.kind}; depth={depth}; nodes={nodes}; elapsed={elapsed}")
        if item.score is not None:
            label = "Survey" if item.kind == "engine_survey" else "Probe"
            lines.append(f"{label} score: {_engine_score_text(item.score)}")
        if item.line:
            lines.append("Moves (UCI): " + " ".join(item.line))
        if item.san_line:
            lines.append("Continuation: " + " ".join(f"{ply}. {san}" for ply, san in enumerate(item.san_line, 1)))
        for branch, san_branch in enumerate(item.alternative_san_lines, 1):
            lines.append(f"Line {branch}: " + " ".join(f"{ply}. {san}" for ply, san in enumerate(san_branch, 1)))
        for consequence in item.consequences:
            detail = f"{consequence.san} [{consequence.source.square}→{consequence.target.square}]"
            if consequence.capture is not None:
                detail += (
                    f" captures {consequence.captured_color} {consequence.captured_piece_type}"
                    f" on {consequence.capture_square.square}"
                )
            if consequence.recapture:
                detail += "; recapture"
            if consequence.promotion is not None:
                detail += f"; promotes to {consequence.promotion}"
            if consequence.material_delta_white:
                detail += f"; material Δ {consequence.material_delta_white:+d}"
            if consequence.gives_check:
                detail += " and gives check"
            lines.append(f"{consequence.ply}. {detail}")
    for assessment in result.move_safety:
        if assessment.root_uci == candidate.uci:
            lines.append(_render_assessment("assessment.move_safety", assessment, catalog, result))
    for assessment in result.trapping:
        lines.append(_render_assessment("assessment.trapping", assessment, catalog, result))
        for exposure in assessment.material_exposures:
            lines.append(_render_material_exposure(exposure, catalog))
    for assessment in result.overload:
        lines.append(_render_assessment("assessment.overload", assessment, catalog, result))
    return "\n".join(lines)


def _render_assessment(
    catalog_id: str, assessment, catalog: ExplanationCatalog, result: AnalysisResult,
) -> str:
    coverage = assessment.coverage
    conclusion = catalog.render(Explanation(
        "", f"assessment.conclusion.{assessment.conclusion.value}",
    ))
    text = catalog.render(Explanation(
        "", catalog_id,
        (("conclusion", conclusion), ("examined", coverage.examined),
         ("total", coverage.total), ("unresolved", coverage.unresolved)),
    ))
    if hasattr(assessment, "root_uci"):
        candidate = next((item for item in result.candidates if item.uci == assessment.root_uci), None)
        subject = f"move {candidate.san} ({assessment.root_uci})" if candidate else f"move {assessment.root_uci}"
    else:
        piece_id = assessment.piece if hasattr(assessment, "piece") else assessment.defender
        placement = next(item for item in result.assessment_pieces if item.piece_id == piece_id)
        subject = f"{placement.square} {placement.color} {placement.piece_type}"
    return f"{subject}: {text}"


def _render_material_exposure(exposure, catalog: ExplanationCatalog) -> str:
    model = catalog.render(Explanation("", f"assessment.material_model.{exposure.model}"))
    return catalog.render(Explanation(
        "", "assessment.material_exposure",
        (("exit", exposure.exit_uci), ("reply", exposure.reply_uci),
         ("material", exposure.material_result), ("model", model)),
    ))


def _explanation_priority(explanation: Explanation) -> tuple[int, str]:
    catalog_id = explanation.catalog_id
    priority = {
        "engine.reported_mate": 0,
        "position.mate_in_one": 0,
        "position.in_check": 1,
        "candidate.allows_opponent_mate_in_one": 2,
    }.get(catalog_id, 3)
    return priority, explanation.explanation_id


def _delta_text(
    delta: MoveDelta,
    *,
    account: MoveAccount | None = None,
    catalog: ExplanationCatalog | None = None,
    detailed: bool = False,
    covered_sources: frozenset = frozenset(),
) -> str:
    catalog = catalog or _load_catalog()
    moved = delta.moved
    parts = [
        f"{delta.san}: {moved.before.piece_type} {moved.before.square}→{moved.after.square}"
    ]
    if delta.captured is not None:
        captured = delta.captured
        parts.append(f"captured {captured.piece_type} on {captured.square}")
    if delta.castling_rook is not None:
        rook = delta.castling_rook
        parts.append(f"rook {rook.before.square}→{rook.after.square}")
    if delta.promoted:
        parts.append(f"promoted to {moved.after.piece_type}")
    if delta.gives_check:
        parts.append("gives check")
    facts = _account_changes(delta, account, covered_sources)
    if account is not None and account.omitted_count:
        facts = (*facts, _catalog_text(
            catalog, "cli.move_account_omitted", (("count", account.omitted_count),),
        ))
    if detailed:
        raw = _relationship_changes(delta, catalog)
        return "\n".join(("; ".join(parts), *facts, *(('Raw changes:', *raw) if raw else ())))
    return "; ".join((*parts, *facts))


def _account_changes(
    delta: MoveDelta, account: MoveAccount | None, covered_sources: frozenset = frozenset(),
) -> tuple[str, ...]:
    if account is None:
        return ()
    direct = {
        ConsequenceKind.CAPTURE, ConsequenceKind.PROMOTION,
        ConsequenceKind.CASTLING, ConsequenceKind.CHECK,
    }
    changes = []
    for event in account.consequences:
        if event.kind in direct or covered_sources.intersection(event.supporting_facts):
            continue
        subject = _account_piece_label(delta, event.subject)
        related = _account_piece_label(delta, event.related_piece)
        actor = _account_piece_label(delta, event.actor)
        relationship = _account_relationship(delta, event)
        if event.kind is ConsequenceKind.LOST_DEFENSE:
            changes.append(f"{subject} is now unguarded")
        elif event.kind is ConsequenceKind.PINNED:
            changes.append(f"{subject} is pinned to {related}")
        elif event.kind is ConsequenceKind.UNPINNED:
            changes.append(f"{subject} is no longer pinned to {related}")
        elif event.kind is ConsequenceKind.OPENED_LINE:
            changes.append(f"opens {actor}'s line {relationship} {subject}")
        elif event.kind is ConsequenceKind.BLOCKED_LINE:
            changes.append(f"blocks {actor}'s line {relationship} {subject}")
        elif event.kind is ConsequenceKind.GAINED_CONTROL:
            changes.append(
                f"{actor} now {relationship} {subject}"
                if event.subject is not None else f"{actor} now controls {event.target.square}"
            )
        elif event.kind is ConsequenceKind.LOST_CONTROL:
            changes.append(f"{actor} no longer {relationship} {subject}")
    return tuple(changes)


def _account_piece_label(delta: MoveDelta, piece_id) -> str:
    if piece_id is None:
        return "piece"
    placement = next(
        (item for item in (*delta.after_pieces, *delta.before_pieces) if item.piece_id == piece_id),
        None,
    )
    return f"{placement.piece_type} {placement.square}" if placement is not None else "piece"


def _account_relationship(delta: MoveDelta, event) -> str:
    contact = next((
        fact for reference in event.supporting_facts
        if isinstance((fact := resolve_raw_fact(delta, reference)), PieceContact)
    ), None)
    if contact is None:
        return "controls"
    if event.kind in (ConsequenceKind.OPENED_LINE, ConsequenceKind.BLOCKED_LINE):
        return "attack on" if contact.kind is ContactKind.ATTACK else "defense of"
    return "attacks" if contact.kind is ContactKind.ATTACK else "defends"


def _attention_text(
    facts, attention: AttentionSelection | None, delta: MoveDelta | None,
    catalog: ExplanationCatalog | None, *, check_explicit: bool,
):
    if attention is None:
        return (), frozenset()
    lines = []
    covered = set()
    for item in attention.items:
        if item.kind is AttentionKind.CHECK and check_explicit:
            continue
        subject = _facts_piece_label(facts, item.subject)
        actor = _facts_piece_label(facts, item.actor)
        related = _facts_piece_label(facts, item.related_piece)
        if item.kind is AttentionKind.CHECK:
            lines.append(f"{subject} is in check")
        elif item.kind is AttentionKind.ATTACKED_UNDEFENDED:
            lines.append(f"{subject} is attacked and geometrically undefended")
        elif item.kind is AttentionKind.LOST_DEFENSE_UNDER_ATTACK:
            lines.append(f"{subject} is now attacked and unguarded")
        elif item.kind is AttentionKind.PINNED:
            lines.append(f"{subject} is pinned to {related}")
        elif item.kind in (AttentionKind.OPENED_LINE, AttentionKind.BLOCKED_LINE):
            relation = _attention_relationship(delta, item)
            verb = "opens" if item.kind is AttentionKind.OPENED_LINE else "blocks"
            lines.append(f"{verb} {actor}'s line {relation} {subject}")
        covered.update(item.move_sources)
    if attention.omitted_count:
        lines.append(_catalog_text(
            catalog, "cli.attention_omitted", (("count", attention.omitted_count),),
        ))
    return tuple(lines), frozenset(covered)


def _facts_piece_label(facts, piece_id) -> str:
    if piece_id is None:
        return "piece"
    placement = next((item for item in facts.pieces if item.piece_id == piece_id), None)
    return f"{placement.piece_type} {placement.square}" if placement is not None else "piece"


def _attention_relationship(delta: MoveDelta | None, item) -> str:
    if delta is None:
        return "to"
    contact = next((
        fact for reference in item.move_sources
        if isinstance((fact := resolve_raw_fact(delta, reference)), PieceContact)
    ), None)
    if contact is None:
        return "to"
    return "attack on" if contact.kind is ContactKind.ATTACK else "defense of"


def _relationship_changes(delta: MoveDelta, catalog: ExplanationCatalog | None) -> tuple[str, ...]:
    before = {piece.piece_id: piece for piece in delta.before_pieces}
    after = {piece.piece_id: piece for piece in delta.after_pieces}
    changes: list[str] = []
    for items, added in ((delta.contacts_added, True), (delta.contacts_removed, False)):
        placements = after if added else before
        heading = _catalog_text(catalog, "cli.contact_added" if added else "cli.contact_removed")
        for contact in items:
            changes.append(
                f"{heading} {_piece_label(placements[contact.controller])} {contact.kind.value}s "
                f"{_piece_label(placements[contact.subject])}"
            )
    for items, added in (
        (delta.geometrically_undefended_added, True),
        (delta.geometrically_undefended_removed, False),
    ):
        placements = after if added else before
        for item in items:
            heading = _catalog_text(catalog, "cli.undefended_added" if added else "cli.undefended_removed")
            changes.append(f"{heading} {_piece_label(placements[item.piece])}")
    for items, added in ((delta.latent_rays_added, True), (delta.latent_rays_removed, False)):
        placements = after if added else before
        heading = _catalog_text(catalog, "cli.latent_ray_added" if added else "cli.latent_ray_removed")
        for ray in items:
            target = f" toward {_piece_label(placements[ray.target])}" if ray.target is not None else ""
            changes.append(
                f"{heading} {_piece_label(placements[ray.slider])} {ray.direction}, blocked by "
                f"{_piece_label(placements[ray.blocker])}{target}"
            )
    for items, added in ((delta.pins_added, True), (delta.pins_removed, False)):
        placements = after if added else before
        heading = _catalog_text(catalog, "cli.pin_added" if added else "cli.pin_removed")
        for pin in items:
            changes.append(
                f"{heading} {_piece_label(placements[pin.piece])} to "
                f"{_piece_label(placements[pin.king])}"
            )
    return tuple(changes)


def render_json(view: SessionView) -> str:
    return serialize_session_view(view)


def _analysis_summary(result: AnalysisResult) -> list[str]:
    probe_summary = _completed_probe_summary(result)
    state_text = probe_summary if result.state is AnalysisState.COMPLETED and probe_summary else result.state.value
    lines = [f"Analysis: {state_text}"]
    if result.state is AnalysisState.RUNNING:
        return lines
    if result.message:
        lines.append(f"Analysis message: {result.message}")
    if result.state is AnalysisState.FAILED:
        lines.append("Check the --engine executable path; run analyze to retry. Board navigation remains available.")
    lines.append(
        f"Coverage: surveyed {result.coverage.surveyed}; selected {result.coverage.requested} "
        f"of {result.coverage.total_legal} legal moves; probed {result.coverage.probed}"
        + (" (interrupted)" if result.coverage.interrupted else "")
    )
    return lines


def _completed_probe_summary(result: AnalysisResult) -> str | None:
    probes = tuple(item for item in result.evidence if item.kind == "engine_line")
    if not probes:
        return None
    depths = sorted(item.engine_depth for item in probes if item.engine_depth is not None)
    noun = "root probe" if len(probes) == 1 else "root probes"
    summary = f"{len(probes)} {noun} completed"
    if not depths:
        return summary
    qualifier = "known " if len(depths) != len(probes) else ""
    if depths[0] == depths[-1]:
        return f"{summary}; {qualifier}depth {depths[0]}"
    return f"{summary}; {qualifier}depth range {depths[0]}–{depths[-1]}"


def _render_fact(explanation: Explanation, catalog: ExplanationCatalog, evidence: dict[str, object]) -> str:
    text = catalog.render(explanation)
    if explanation.catalog_id == "position.in_check" and explanation.squares:
        return text + " Checkers: " + ", ".join(square.square for square in explanation.squares) + "."
    if explanation.catalog_id == "position.mate_in_one":
        san_moves = [
            line[0]
            for ref in explanation.evidence_refs
            if ref in evidence
            for line in evidence[ref].alternative_san_lines  # type: ignore[attr-defined]
            if line
        ]
        if san_moves:
            return text + " Moves: " + ", ".join(san_moves) + "."
    return text


def _score_text(candidate: CandidateResult) -> str:
    score = candidate.score
    if score is None:
        return "not available"
    return _engine_score_text(score, provisional=candidate.provisional)


def _engine_score_text(score: EngineScore, *, provisional: bool = False) -> str:
    suffix = f" ({score.bound.value}{', provisional' if provisional else ''})"
    mate = score.mate
    mate_winner = score.mate_winner
    if mate is not None:
        return f"{mate_winner} mates in {abs(mate)}{suffix}"
    centipawns = score.centipawns
    assert centipawns is not None
    return f"{centipawns / 100:+.2f}{suffix}"


def render_games(view: SessionView) -> str:
    lines = []
    for game in view.games:
        headers = dict(game.headers)
        label = " - ".join(value for value in (headers.get("White"), headers.get("Black")) if value)
        selected = "*" if game.number == view.selected_game else " "
        lines.append(f"{selected} {game.number}: {label or '(untitled)'} [{game.recorded_result or '*'}]")
    return "\n".join(lines)


def render_inspection(
    view: SessionView, square: str, catalog: ExplanationCatalog | None = None,
) -> str:
    placements = {piece.piece_id: piece for piece in view.facts.pieces}
    occupant = next((piece for piece in view.facts.pieces if piece.square == square), None)
    attacks = tuple(attack for attack in view.facts.attacks if attack.target.square == square)
    access = tuple(move for move in view.facts.legal_moves if move.target.square == square)
    pins = tuple(
        pin
        for pin in view.facts.pins
        if pin.piece == (occupant.piece_id if occupant else None)
        or any(attack.attacker == pin.piece for attack in attacks)
        or any(reference.square == square for reference in pin.ray)
    )
    lines = [f"Square: {square}"]
    lines.append(f"Occupant: {_piece_label(occupant) if occupant else 'none'}")
    lines.append(
        "Geometric attackers: "
        + (", ".join(_piece_label(placements[attack.attacker]) for attack in attacks) or "none")
    )
    lines.append(
        f"Legal access ({view.facts.turn} to move): "
        + (", ".join(f"{move.uci} {_piece_label(placements[move.mover])}" for move in access) or "none")
    )
    lines.append(
        "Absolute pins: "
        + (
            ", ".join(
                f"{_piece_label(placements[pin.piece])} along "
                + "-".join(reference.square for reference in pin.ray)
                for pin in pins
            )
            or "none"
        )
    )
    contacts = tuple(
        contact
        for contact in view.facts.contacts
        if contact.controller_square.square == square or contact.subject_square.square == square
    )
    lines.append(
        "Piece contacts: "
        + (
            ", ".join(
                f"{_piece_label(placements[contact.controller])} {contact.kind.value}s "
                f"{_piece_label(placements[contact.subject])}"
                for contact in contacts
            )
            or "none"
        )
    )
    rays = tuple(
        ray
        for ray in view.facts.latent_rays
        if ray.source.square == square or ray.blocker_square.square == square
        or any(reference.square == square for reference in ray.beyond)
    )
    lines.append(
        "Latent slider rays: "
        + (
            ", ".join(
                f"{_piece_label(placements[ray.slider])} {ray.direction} blocked by "
                f"{_piece_label(placements[ray.blocker])}"
                + (f" toward {_piece_label(placements[ray.target])}" if ray.target is not None else "")
                for ray in rays
            )
            or "none"
        )
    )
    undefended = tuple(item for item in view.facts.geometrically_undefended if item.square.square == square)
    lines.append(
        "Geometrically undefended: "
        + (", ".join(_piece_label(placements[item.piece]) for item in undefended) or "none")
    )
    if view.analysis is not None and catalog is not None:
        piece = next((item for item in view.pieces if item.square == square), None)
        if piece is not None:
            for assessment in view.analysis.trapping:
                if assessment.piece == piece.piece_id:
                    lines.append(_render_assessment("assessment.trapping", assessment, catalog, view.analysis))
                    for exposure in assessment.material_exposures:
                        lines.append(_render_material_exposure(exposure, catalog))
            for assessment in view.analysis.overload:
                if assessment.defender == piece.piece_id:
                    lines.append(_render_assessment("assessment.overload", assessment, catalog, view.analysis))
    return "\n".join(lines)


def _piece_label(piece: PiecePlacement) -> str:
    return f"{piece.square} {piece.color} {piece.piece_type}"


def render_changes(view: SessionView, catalog: ExplanationCatalog | None = None) -> str:
    return (
        _delta_text(view.previous_move, account=view.move_account, catalog=catalog, detailed=True)
        if view.previous_move is not None
        else _catalog_text(catalog, "cli.no_previous_move")
    )


def render_line_preview(
    preview: CandidateLinePreview,
    catalog: ExplanationCatalog | None = None,
    orientation: ResolvedOrientation = ResolvedOrientation.WHITE,
) -> str:
    if catalog is None and (preview.previous_move is not None or preview.attention.items):
        catalog = _load_catalog()
    lines = list(_oriented_board_rows(preview.board_rows, orientation))
    lines.append(f"Candidate line: {preview.candidate.san} ({preview.candidate.uci}), ply {preview.ply}")
    attention, covered_sources = _attention_text(
        preview.facts, preview.attention, preview.previous_move,
        catalog,
        check_explicit=bool(preview.previous_move and preview.previous_move.gives_check),
    )
    if attention:
        lines.append("Attention: " + "; ".join(attention))
    lines.append(
        _delta_text(
            preview.previous_move, account=preview.move_account, catalog=catalog,
            covered_sources=covered_sources,
        ) if preview.previous_move is not None else _catalog_text(catalog, "cli.candidate_line_root")
    )
    return "\n".join(lines)


def _catalog_text(
    catalog: ExplanationCatalog | None,
    catalog_id: str,
    values: tuple[tuple[str, str | int | bool], ...] = (),
) -> str:
    if catalog is not None:
        return catalog.render(Explanation("", catalog_id, values))
    return _load_catalog().render(Explanation("", catalog_id, values))


def _load_catalog() -> ExplanationCatalog:
    return ExplanationCatalog.load(Path(__file__).parents[1] / "content" / "explanations.json")


def execute(
    session: Session,
    command: str,
    *,
    controller: AnalysisController | None = None,
    catalog: ExplanationCatalog | None = None,
    display_state: BoardDisplayState | None = None,
    settings_store: SettingsStore | None = None,
    orientation_override: Orientation | None = None,
) -> tuple[str, bool]:
    display = display_state or BoardDisplayState()
    if len(command) > MAX_COMMAND_CHARS:
        raise SessionError(f"command exceeds {MAX_COMMAND_CHARS} characters")
    verb, separator, remainder = command.strip().partition(" ")
    verb = verb.lower()
    argument = remainder.strip() if separator else ""
    if verb == "load":
        explicit_orientation, argument = _import_orientation(argument)
        if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in {'"', "'"}:
            argument = argument[1:-1]
        if not argument:
            raise SessionError("load requires a .pgn or .fen path")
        suffix, text = read_chess_file(argument)
        view = session.load_pgn(text) if suffix == ".pgn" else session.load_fen(text)
        return _render_import(
            session, view, controller, catalog, display, settings_store, orientation_override, explicit_orientation,
        ), False
    if verb == "fen":
        explicit_orientation, argument = _import_orientation(argument)
        if not argument:
            raise SessionError("fen requires all six FEN fields")
        view = session.load_fen(argument)
        return _render_import(
            session, view, controller, catalog, display, settings_store, orientation_override, explicit_orientation,
        ), False
    if verb == "games":
        return render_games(_shared_view(session, controller)), False
    if verb == "game":
        return render_board(
            _submit(session, session.select_game(_positive_int(argument, "game")), controller),
            display.orientation, catalog,
        ), False
    if verb == "board":
        return render_board(_shared_view(session, controller), display.orientation, catalog), False
    if verb == "flip":
        display.flip()
        return render_board(_shared_view(session, controller), display.orientation, catalog), False
    if verb == "orientation":
        return _orientation_command(argument, display, settings_store), False
    if verb == "inspect":
        try:
            square = chess.square_name(chess.parse_square(argument.lower()))
        except ValueError as exc:
            raise SessionError("inspect requires a square from a1 to h8") from exc
        return render_inspection(_shared_view(session, controller), square, catalog), False
    if verb == "changes":
        return render_changes(_shared_view(session, controller), catalog), False
    if verb == "start":
        return render_board(_submit(session, session.start(), controller), display.orientation, catalog), False
    if verb == "end":
        return render_board(_submit(session, session.end(), controller), display.orientation, catalog), False
    if verb == "next":
        return render_board(_submit(session, session.next(), controller), display.orientation, catalog), False
    if verb == "back":
        return render_board(_submit(session, session.back(), controller), display.orientation, catalog), False
    if verb == "goto":
        return render_board(
            _submit(session, session.goto(_nonnegative_int(argument, "ply")), controller), display.orientation, catalog,
        ), False
    if verb == "variations":
        view = _shared_view(session, controller)
        if not view.variations:
            return "No continuations from this position.", False
        return "\n".join(f"{index}: {san}" for index, san in enumerate(view.variations, 1)), False
    if verb == "variation":
        return render_board(
            _submit(session, session.variation(_positive_int(argument, "variation")), controller),
            display.orientation, catalog,
        ), False
    if verb == "move":
        if not argument:
            raise SessionError("move requires SAN or UCI notation")
        return render_board(_submit(session, session.play(argument), controller), display.orientation, catalog), False
    if verb == "analyze":
        view = session.view()
        if controller is None:
            raise SessionError("analysis is not configured")
        return render_board(session.request_analysis(controller, view=view), display.orientation, catalog), False
    if verb == "compare":
        notations = tuple(argument.split())
        if len(notations) != 2:
            raise SessionError("compare requires two legal SAN or UCI moves")
        if controller is None:
            raise SessionError("analysis is not configured")
        view = session.view()
        return render_board(
            session.request_analysis(controller, view=view, compare=notations), display.orientation, catalog,
        ), False
    if verb == "probe":
        kind, separator, value = argument.partition(" ")
        if controller is None:
            raise SessionError("analysis is not configured")
        if not separator or not value.strip():
            raise SessionError("probe requires 'move <SAN-or-UCI>' or 'piece <square>'")
        subject = session.resolve_probe(kind, value.strip())
        return render_board(
            session.request_probe(controller, subject, view=session.view()), display.orientation, catalog,
        ), False
    if verb == "details":
        view = _shared_view(session, controller)
        if catalog is None or view.analysis is None or view.analysis.revision != view.revision:
            raise SessionError("no current analysis details are available")
        return render_details(view.analysis, _positive_int(argument, "candidate number"), catalog), False
    if verb == "line":
        parts = argument.split()
        if len(parts) != 2:
            raise SessionError("line requires a candidate number and ply")
        try:
            preview = preview_candidate_line(
                _shared_view(session, controller),
                _positive_int(parts[0], "candidate number"),
                _nonnegative_int(parts[1], "ply"),
            )
        except PreviewError as exc:
            raise SessionError(str(exc)) from exc
        return render_line_preview(preview, catalog, display.orientation), False
    if verb == "json":
        return render_json(_shared_view(session, controller)), False
    if verb == "cancel":
        raise SessionError("cancel must run through the asynchronous CLI")
    if verb in {"quit", "exit"}:
        return "", True
    if verb == "help":
        return (
            "load <path> | fen <FEN> | games | game <n> | board | start | end | "
            "next | back | goto <ply> | variations | variation <n> | move <SAN-or-UCI> | "
            "inspect <square> | changes | flip | orientation [white|black|default <white|black|turn>] | "
            "analyze | compare <move> <move> | probe move <SAN-or-UCI> | probe piece <square> | "
            "details <n> | line <candidate-number> <ply> | json | cancel | quit"
        ), False
    if not verb:
        return "", False
    raise SessionError(f"unknown command {verb!r}; use help to list commands")


def _import_orientation(argument: str) -> tuple[Orientation | None, str]:
    if argument != "--orientation" and not argument.startswith("--orientation "):
        return None, argument
    option, separator, remainder = argument.partition(" ")
    if option != "--orientation" or not separator:
        raise SessionError("--orientation requires white, black, or turn followed by an import")
    value, separator, remainder = remainder.strip().partition(" ")
    if not separator or not remainder.strip():
        raise SessionError("--orientation requires white, black, or turn followed by an import")
    try:
        return Orientation(value), remainder.strip()
    except ValueError as exc:
        raise SessionError("--orientation must be white, black, or turn") from exc


def _render_import(
    session: Session,
    view: SessionView,
    controller: AnalysisController | None,
    catalog: ExplanationCatalog | None,
    display: BoardDisplayState,
    settings_store: SettingsStore | None,
    orientation_override: Orientation | None,
    explicit_orientation: Orientation | None,
) -> str:
    message = None
    preference = explicit_orientation or orientation_override
    if preference is None and settings_store is not None:
        loaded = settings_store.load()
        preference = loaded.settings.orientation
        message = loaded.message
    display.apply_import(preference or DEFAULT_ORIENTATION, view.turn)
    output = render_board(_submit(session, view, controller), display.orientation, catalog)
    return output if message is None else output + f"\nSettings: {message}"


def _orientation_command(
    argument: str,
    display: BoardDisplayState,
    settings_store: SettingsStore | None,
) -> str:
    if not argument:
        if settings_store is None:
            return f"Orientation: {display.orientation.value}; saved default: {DEFAULT_ORIENTATION.value}"
        loaded = settings_store.load()
        default = loaded.settings.orientation
        if loaded.message is not None:
            return (
                f"Orientation: {display.orientation.value}; default fallback: {default.value}"
                f"\nSettings: {loaded.message}"
            )
        return f"Orientation: {display.orientation.value}; saved default: {default.value}"
    if argument.startswith("default "):
        if settings_store is None:
            raise SessionError("settings are not configured")
        try:
            preference = Orientation(argument.removeprefix("default ").strip())
        except ValueError as exc:
            raise SessionError("orientation default must be white, black, or turn") from exc
        try:
            settings_store.save_orientation(preference)
        except SettingsError as exc:
            raise SessionError(str(exc)) from exc
        return f"Saved orientation default: {preference.value}"
    try:
        display.set_orientation(ResolvedOrientation(argument))
    except ValueError as exc:
        raise SessionError("orientation must be white, black, or default <white|black|turn>") from exc
    return f"Orientation: {display.orientation.value}"


def _submit(session: Session, view: SessionView, controller: AnalysisController | None) -> SessionView:
    if controller is not None and (controller.latest is None or controller.latest.revision != view.revision):
        return session.request_analysis(controller, view=view)
    return session.analysis_view(controller, view=view) if controller is not None else view


def _shared_view(session: Session, controller: AnalysisController | None) -> SessionView:
    return session.analysis_view(controller) if controller is not None else session.view()


async def execute_async(
    session: Session,
    command: str,
    *,
    controller: AnalysisController | None = None,
    catalog: ExplanationCatalog | None = None,
    display_state: BoardDisplayState | None = None,
    settings_store: SettingsStore | None = None,
    orientation_override: Orientation | None = None,
) -> tuple[str, bool]:
    if command.strip().lower() == "cancel":
        if controller is None:
            raise SessionError("analysis is not configured")
        if controller.latest is None or controller.latest.state is not AnalysisState.RUNNING:
            return "No analysis is running.", False
        await controller.cancel()
        return "Analysis canceled.", False
    return execute(
        session, command, controller=controller, catalog=catalog, display_state=display_state,
        settings_store=settings_store, orientation_override=orientation_override,
    )


async def run_cli(
    session: Session,
    *,
    controller: AnalysisController | None = None,
    catalog: ExplanationCatalog | None = None,
    display_state: BoardDisplayState | None = None,
    settings_store: SettingsStore | None = None,
    orientation_override: Orientation | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    prompt_input: Input | None = None,
    prompt_output: Output | None = None,
) -> int:
    interactive = prompt_input is not None or stdin.isatty()
    owned_input = create_input(stdin=stdin) if interactive and prompt_input is None else None
    actual_input = prompt_input or owned_input
    actual_output = prompt_output or (create_output(stdout=stdout) if interactive else None)
    display = display_state or BoardDisplayState()
    quit_requested = False
    reporter = (
        asyncio.create_task(_report_analysis(controller, catalog, session, stdout))
        if interactive and controller is not None and catalog is not None
        else None
    )
    try:
        with create_app_session(input=actual_input, output=actual_output):
            prompt = PromptSession(input=actual_input, output=actual_output) if interactive else None
            while True:
                try:
                    if prompt is not None:
                        with patch_stdout(raw=True):
                            command = await prompt.prompt_async("namichess> ")
                    else:
                        line = await asyncio.to_thread(stdin.readline)
                        if not line:
                            break
                        command = line.rstrip("\r\n")
                    output, should_quit = await execute_async(
                        session, command, controller=controller, catalog=catalog, display_state=display,
                        settings_store=settings_store, orientation_override=orientation_override,
                    )
                    if output:
                        print(output, file=stdout)
                    if should_quit:
                        quit_requested = True
                        if controller is not None:
                            await controller.cancel()
                        break
                except (ChessImportError, SessionError) as exc:
                    print(f"Error: {exc}", file=stderr)
                except KeyboardInterrupt:
                    if controller is not None and controller.latest is not None and controller.latest.state is AnalysisState.RUNNING:
                        await controller.cancel()
                    if prompt is None:
                        break
                    continue
                except EOFError:
                    break
            if not interactive and not quit_requested and controller is not None and controller.latest is not None:
                result = await controller.wait()
                if result is not None and session.loaded and result.revision == session.view().revision and catalog is not None:
                    print(render_analysis(result, catalog), file=stdout)
        return 0
    finally:
        if reporter is not None:
            reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)
        if controller is not None:
            await controller.close()
        if owned_input is not None:
            owned_input.close()


async def _report_analysis(
    controller: AnalysisController,
    catalog: ExplanationCatalog,
    session: Session,
    stdout: TextIO,
) -> None:
    last_final: tuple[int, AnalysisState] | None = None
    while True:
        await asyncio.sleep(0.25)
        result = controller.latest
        if result is None or not session.loaded or result.revision != session.view().revision:
            continue
        if result.state is AnalysisState.RUNNING:
            continue
        marker = (result.request_id, result.state)
        if marker != last_final:
            await run_in_terminal(lambda: print(render_analysis(result, catalog), file=stdout))
            last_final = marker


def _positive_int(value: str, name: str) -> int:
    number = _nonnegative_int(value, name)
    if number == 0:
        raise SessionError(f"{name} must be at least 1")
    return number


def _nonnegative_int(value: str, name: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise SessionError(f"{name} must be an integer") from exc
    if number < 0:
        raise SessionError(f"{name} must be nonnegative")
    return number
