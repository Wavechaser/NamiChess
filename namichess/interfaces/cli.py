"""Interactive command-line adapter for the navigable M1 session."""

from __future__ import annotations

import asyncio
import sys
from typing import TextIO

import chess
from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import create_app_session
from prompt_toolkit.input import Input
from prompt_toolkit.input.defaults import create_input
from prompt_toolkit.output import Output
from prompt_toolkit.output.defaults import create_output
from prompt_toolkit.patch_stdout import patch_stdout

from namichess.application.imports import ImportError as ChessImportError
from namichess.application.session import Session, SessionError
from namichess.application.views import SessionView
from namichess.domain.models import PiecePlacement
from namichess.interfaces.files import read_chess_file

MAX_COMMAND_CHARS = 16 * 1024


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
    return "\n".join(lines)


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


def execute(session: Session, command: str) -> tuple[str, bool]:
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
        return render_board(view), False
    if verb == "fen":
        if not argument:
            raise SessionError("fen requires all six FEN fields")
        return render_board(session.load_fen(argument)), False
    if verb == "games":
        return render_games(session.view()), False
    if verb == "game":
        return render_board(session.select_game(_positive_int(argument, "game"))), False
    if verb == "board":
        return render_board(session.view()), False
    if verb == "inspect":
        try:
            square = chess.square_name(chess.parse_square(argument.lower()))
        except ValueError as exc:
            raise SessionError("inspect requires a square from a1 to h8") from exc
        return render_inspection(session.view(), square), False
    if verb == "start":
        return render_board(session.start()), False
    if verb == "end":
        return render_board(session.end()), False
    if verb == "next":
        return render_board(session.next()), False
    if verb == "back":
        return render_board(session.back()), False
    if verb == "goto":
        return render_board(session.goto(_nonnegative_int(argument, "ply"))), False
    if verb == "variations":
        view = session.view()
        if not view.variations:
            return "No continuations from this position.", False
        return "\n".join(f"{index}: {san}" for index, san in enumerate(view.variations, 1)), False
    if verb == "variation":
        return render_board(session.variation(_positive_int(argument, "variation"))), False
    if verb == "move":
        if not argument:
            raise SessionError("move requires SAN or UCI notation")
        return render_board(session.play(argument)), False
    if verb in {"quit", "exit"}:
        return "", True
    if verb == "help":
        return (
            "load <path> | fen <FEN> | games | game <n> | board | start | end | "
            "next | back | goto <ply> | variations | variation <n> | move <SAN-or-UCI> | "
            "inspect <square> | quit"
        ), False
    if not verb:
        return "", False
    raise SessionError(f"unknown command {verb!r}; use help to list commands")


async def run_cli(
    session: Session,
    *,
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
                    output, should_quit = execute(session, command)
                    if output:
                        print(output, file=stdout)
                    if should_quit:
                        break
                except (ChessImportError, SessionError) as exc:
                    print(f"Error: {exc}", file=stderr)
                except KeyboardInterrupt:
                    if prompt is None:
                        break
                    continue
                except EOFError:
                    break
        return 0
    finally:
        if owned_input is not None:
            owned_input.close()


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
