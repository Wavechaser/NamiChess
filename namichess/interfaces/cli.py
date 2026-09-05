"""Interactive command-line adapter for the navigable M1 session."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from enum import Enum
from typing import Any, TextIO

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
from namichess.application.analysis import AnalysisController, AnalysisResult, AnalysisState, CandidateResult
from namichess.analysis.evidence import Explanation
from namichess.analysis.static import MoveDelta
from namichess.application.session import Session, SessionError
from namichess.application.views import SessionView
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.domain.models import PiecePlacement
from namichess.interfaces.files import read_chess_file

MAX_COMMAND_CHARS = 16 * 1024


def configure_standard_streams() -> None:
    """Use the CLI's documented UTF-8 contract for native process streams."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def render_board(view: SessionView) -> str:
    lines = list(view.board_rows)
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
    if view.previous_move is not None:
        lines.append(_delta_text(view.previous_move))
    if view.analysis is not None:
        lines.extend(_analysis_summary(view.analysis))
    return "\n".join(lines)


def render_analysis(result: AnalysisResult, catalog: ExplanationCatalog) -> str:
    lines = _analysis_summary(result)
    explanations = {item.explanation_id: item for item in result.explanations}
    evidence = {item.evidence_id: item for item in result.evidence}
    prioritized = sorted(result.explanations, key=_explanation_priority)[:3]
    for explanation in prioritized:
        candidate = next(
            (item for item in result.candidates if explanation.explanation_id in item.explanation_refs),
            None,
        )
        prefix = f"[{candidate.san}] " if candidate is not None else ""
        lines.append(f"Fact: {prefix}{_render_fact(explanation, catalog, evidence)}")
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
                detail += f"; White material change {consequence.material_delta_white:+d}"
            if consequence.gives_check:
                detail += " and gives check"
            lines.append(f"{consequence.ply}. {detail}")
    return "\n".join(lines)


def _explanation_priority(explanation: Explanation) -> tuple[int, str]:
    catalog_id = explanation.catalog_id
    priority = {
        "position.in_check": 0,
        "position.mate_in_one": 1,
        "candidate.allows_opponent_mate_in_one": 2,
    }.get(catalog_id, 3)
    return priority, explanation.explanation_id


def _delta_text(delta: MoveDelta) -> str:
    moved = delta.moved
    parts = [
        f"Changed: {delta.san} — {moved.after.color} {moved.after.piece_type} "
        f"{moved.before.square}→{moved.after.square}"
    ]
    if delta.captured is not None:
        captured = delta.captured
        parts.append(f"captured {captured.color} {captured.piece_type} on {captured.square}")
    if delta.castling_rook is not None:
        rook = delta.castling_rook
        parts.append(f"rook {rook.before.square}→{rook.after.square}")
    if delta.promoted:
        parts.append(f"promoted to {moved.after.piece_type}")
    added = len(delta.attacks_added)
    removed = len(delta.attacks_removed)
    if added or removed:
        parts.append(f"geometric attacks +{added}/−{removed}")
    pins_added = len(delta.pins_added)
    pins_removed = len(delta.pins_removed)
    if pins_added or pins_removed:
        parts.append(f"absolute pins +{pins_added}/−{pins_removed}")
    if delta.gives_check:
        parts.append("gives check")
    return "; ".join(parts)


def render_json(view: SessionView) -> str:
    return json.dumps({"schema_version": 1, "session": _json_value(dataclasses.replace(view, analysis=None)), "analysis": _json_value(view.analysis)}, sort_keys=True)


def _analysis_summary(result: AnalysisResult) -> list[str]:
    lines = [f"Analysis: {result.state.value}"]
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
    return f"{centipawns / 100:+.2f} (+ favors White / − favors Black){suffix}"


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def render_games(view: SessionView) -> str:
    lines = []
    for game in view.games:
        headers = dict(game.headers)
        label = " - ".join(value for value in (headers.get("White"), headers.get("Black")) if value)
        selected = "*" if game.number == view.selected_game else " "
        lines.append(f"{selected} {game.number}: {label or '(untitled)'} [{game.recorded_result or '*'}]")
    return "\n".join(lines)


def render_inspection(view: SessionView, square: str) -> str:
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
    return "\n".join(lines)


def _piece_label(piece: PiecePlacement) -> str:
    return f"{piece.square} {piece.color} {piece.piece_type}"


def execute(
    session: Session,
    command: str,
    *,
    controller: AnalysisController | None = None,
    catalog: ExplanationCatalog | None = None,
) -> tuple[str, bool]:
    if len(command) > MAX_COMMAND_CHARS:
        raise SessionError(f"command exceeds {MAX_COMMAND_CHARS} characters")
    verb, separator, remainder = command.strip().partition(" ")
    verb = verb.lower()
    argument = remainder.strip() if separator else ""
    if verb == "load":
        if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in {'"', "'"}:
            argument = argument[1:-1]
        if not argument:
            raise SessionError("load requires a .pgn or .fen path")
        suffix, text = read_chess_file(argument)
        view = session.load_pgn(text) if suffix == ".pgn" else session.load_fen(text)
        return render_board(_submit(session, view, controller)), False
    if verb == "fen":
        if not argument:
            raise SessionError("fen requires all six FEN fields")
        return render_board(_submit(session, session.load_fen(argument), controller)), False
    if verb == "games":
        return render_games(_shared_view(session, controller)), False
    if verb == "game":
        return render_board(_submit(session, session.select_game(_positive_int(argument, "game")), controller)), False
    if verb == "board":
        return render_board(_shared_view(session, controller)), False
    if verb == "inspect":
        try:
            square = chess.square_name(chess.parse_square(argument.lower()))
        except ValueError as exc:
            raise SessionError("inspect requires a square from a1 to h8") from exc
        return render_inspection(_shared_view(session, controller), square), False
    if verb == "start":
        return render_board(_submit(session, session.start(), controller)), False
    if verb == "end":
        return render_board(_submit(session, session.end(), controller)), False
    if verb == "next":
        return render_board(_submit(session, session.next(), controller)), False
    if verb == "back":
        return render_board(_submit(session, session.back(), controller)), False
    if verb == "goto":
        return render_board(_submit(session, session.goto(_nonnegative_int(argument, "ply")), controller)), False
    if verb == "variations":
        view = _shared_view(session, controller)
        if not view.variations:
            return "No continuations from this position.", False
        return "\n".join(f"{index}: {san}" for index, san in enumerate(view.variations, 1)), False
    if verb == "variation":
        return render_board(_submit(session, session.variation(_positive_int(argument, "variation")), controller)), False
    if verb == "move":
        if not argument:
            raise SessionError("move requires SAN or UCI notation")
        return render_board(_submit(session, session.play(argument), controller)), False
    if verb == "analyze":
        view = session.view()
        if controller is None:
            raise SessionError("analysis is not configured")
        return render_board(session.request_analysis(controller, view=view)), False
    if verb == "compare":
        notations = tuple(argument.split())
        if len(notations) != 2:
            raise SessionError("compare requires two legal SAN or UCI moves")
        if controller is None:
            raise SessionError("analysis is not configured")
        view = session.view()
        return render_board(session.request_analysis(controller, view=view, compare=notations)), False
    if verb == "details":
        view = _shared_view(session, controller)
        if catalog is None or view.analysis is None or view.analysis.revision != view.revision:
            raise SessionError("no current analysis details are available")
        return render_details(view.analysis, _positive_int(argument, "candidate number"), catalog), False
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
            "inspect <square> | analyze | compare <move> <move> | details <n> | json | cancel | quit"
        ), False
    if not verb:
        return "", False
    raise SessionError(f"unknown command {verb!r}; use help to list commands")


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
) -> tuple[str, bool]:
    if command.strip().lower() == "cancel":
        if controller is None:
            raise SessionError("analysis is not configured")
        if controller.latest is None or controller.latest.state is not AnalysisState.RUNNING:
            return "No analysis is running.", False
        await controller.cancel()
        return "Analysis canceled.", False
    return execute(session, command, controller=controller, catalog=catalog)


async def run_cli(
    session: Session,
    *,
    controller: AnalysisController | None = None,
    catalog: ExplanationCatalog | None = None,
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
    quit_requested = False
    reporter = (
        asyncio.create_task(_report_analysis(controller, catalog, session, stdout, stderr))
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
                    output, should_quit = await execute_async(session, command, controller=controller, catalog=catalog)
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
    stderr: TextIO,
) -> None:
    last_progress: tuple[int, float] | None = None
    last_final: tuple[int, AnalysisState] | None = None
    while True:
        await asyncio.sleep(0.25)
        result = controller.latest
        if result is None or not session.loaded or result.revision != session.view().revision:
            continue
        if result.state is AnalysisState.RUNNING:
            progress = controller.progress
            if progress is not None:
                marker = (result.request_id, progress.elapsed_seconds)
                if marker != last_progress:
                    await run_in_terminal(lambda: print(f"Analysis progress: {progress.elapsed_seconds:.1f}s", file=stderr))
                    last_progress = marker
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
