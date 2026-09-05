"""Strict, bounded import of PGN and FEN chess documents."""

from __future__ import annotations

from dataclasses import dataclass
import io
import re

import chess.pgn

from namichess.domain.validation import PositionValidationError, parse_fen

MAX_GAMES = 1_000
MAX_MOVE_NODES = 100_000
MAX_VARIATION_DEPTH = 64


class ImportError(ValueError):
    """Imported chess text is incomplete or invalid."""


@dataclass(slots=True)
class ImportedDocument:
    games: tuple[chess.pgn.Game, ...]
    has_history: bool


@dataclass(slots=True)
class _ParseBudget:
    moves: int = 0
    depth: int = 0


class _StrictBuilder(chess.pgn.GameBuilder):
    def __init__(self, budget: _ParseBudget) -> None:
        super().__init__()
        self._budget = budget

    def handle_error(self, error: Exception) -> None:
        raise error

    def begin_variation(self) -> None:
        self._budget.depth += 1
        if self._budget.depth > MAX_VARIATION_DEPTH:
            raise ImportError(
                f"PGN exceeds variation depth limit {MAX_VARIATION_DEPTH}; reduce the variations and reload"
            )
        return super().begin_variation()

    def end_variation(self) -> None:
        self._budget.depth -= 1
        return super().end_variation()

    def visit_move(self, board: chess.Board, move: chess.Move) -> None:
        if move == chess.Move.null():
            raise ImportError("PGN contains a null move; remove null moves and reload")
        if move not in board.legal_moves:
            raise ImportError("PGN contains a move that is not legal standard chess")
        self._budget.moves += 1
        if self._budget.moves > MAX_MOVE_NODES:
            raise ImportError(
                f"PGN exceeds move-node limit {MAX_MOVE_NODES}; reduce the games or variations and reload"
            )
        return super().visit_move(board, move)


_MOVE_NUMBER = re.compile(r"\d+\.(?:\.\.)?")


def _location(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous = text.rfind("\n", 0, offset)
    return line, offset - previous


def _problem(game_number: int, text: str, offset: int, message: str) -> ImportError:
    line, column = _location(text, offset)
    return ImportError(
        f"game {game_number}, line {line}, column {column}: {message}; correct the PGN and reload"
    )


def _mask_comments_and_headers(segment: str, game_number: int) -> str:
    chars = list(segment)
    in_brace = False
    movetext_started = False
    offset = 0
    for raw_line in segment.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        stripped = line.lstrip()
        leading = len(line) - len(stripped)
        if not in_brace and stripped.startswith("["):
            if movetext_started or not chess.pgn.TAG_REGEX.fullmatch(stripped):
                raise _problem(game_number, segment, offset + leading, "malformed or misplaced PGN tag")
            for index in range(offset, offset + len(line)):
                chars[index] = " "
            offset += len(raw_line)
            continue
        if not in_brace and (line.startswith("%") or stripped.startswith(";")):
            for index in range(offset, offset + len(line)):
                chars[index] = " "
            offset += len(raw_line)
            continue
        if stripped:
            movetext_started = True
        index = 0
        while index < len(line):
            absolute = offset + index
            if in_brace:
                chars[absolute] = " "
                if line[index] == "}":
                    in_brace = False
                index += 1
            elif line[index] == "{":
                in_brace = True
                chars[absolute] = " "
                index += 1
            elif line[index] == "}":
                raise _problem(game_number, segment, absolute, "unmatched closing comment brace")
            elif line[index] == ";":
                for rest in range(absolute, offset + len(line)):
                    chars[rest] = " "
                break
            else:
                index += 1
        offset += len(raw_line)
    if in_brace:
        raise _problem(game_number, segment, len(segment) - 1, "unclosed comment brace")
    return "".join(chars)


def _validate_tokens(segment: str, game_number: int) -> str:
    text = _mask_comments_and_headers(segment, game_number)
    offset = 0
    depth = 0
    result: str | None = None
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        number = _MOVE_NUMBER.match(text, offset)
        if number:
            if result is not None:
                raise _problem(game_number, segment, offset, "movetext follows the result marker")
            offset = number.end()
            continue
        token_match = chess.pgn.MOVETEXT_REGEX.match(text, offset)
        if not token_match:
            end = offset
            while end < len(text) and not text[end].isspace():
                end += 1
            raise _problem(game_number, segment, offset, f"unrecognized movetext {text[offset:end]!r}")
        token = token_match.group(0)
        if token.startswith(("?", "!")):
            run_end = offset
            while run_end < len(text) and text[run_end] in "?!":
                run_end += 1
            if run_end - offset > 2:
                raise _problem(game_number, segment, offset, "annotation glyph contains more than two symbols")
        if token in {"--", "Z0", "0000", "@@@@"}:
            raise _problem(game_number, segment, offset, "null moves are not valid standard PGN moves")
        if result is not None:
            raise _problem(game_number, segment, offset, "movetext follows the result marker")
        if token == "(":
            depth += 1
            if depth > MAX_VARIATION_DEPTH:
                raise _problem(game_number, segment, offset, f"variation depth exceeds {MAX_VARIATION_DEPTH}")
        elif token == ")":
            if depth == 0:
                raise _problem(game_number, segment, offset, "unmatched closing variation parenthesis")
            depth -= 1
        elif token in {"1-0", "0-1", "1/2-1/2", "*"}:
            if depth:
                raise _problem(game_number, segment, offset, "result marker appears inside a variation")
            result = token
        offset = token_match.end()
        if offset < len(text) and text[offset] in "+#":
            offset += 1
    if depth:
        raise _problem(game_number, segment, len(segment) - 1, "unclosed variation parenthesis")
    if result is None:
        raise _problem(game_number, segment, max(0, len(segment) - 1), "missing terminating result marker")
    return result


def import_pgn_text(text: str) -> ImportedDocument:
    handle = io.StringIO(text.lstrip("\ufeff"))
    games: list[chess.pgn.Game] = []
    budget = _ParseBudget()
    while True:
        start = handle.tell()
        try:
            game = chess.pgn.read_game(handle, Visitor=lambda: _StrictBuilder(budget))
        except (ValueError, ImportError) as exc:
            if isinstance(exc, ImportError):
                raise
            line, column = _location(text, start)
            raise ImportError(
                f"game {len(games) + 1}, near line {line}, column {column}: {exc}; correct the PGN and reload"
            ) from exc
        end = handle.tell()
        if game is None:
            if text[start:].strip():
                raise _problem(len(games) + 1, text, start, "unparseable trailing content")
            break
        game_number = len(games) + 1
        if game_number > MAX_GAMES:
            raise ImportError(
                f"PGN exceeds game limit {MAX_GAMES}; reduce the file and reload"
            )
        segment = handle.getvalue()[start:end]
        result = _validate_tokens(segment, game_number)
        if game.errors:
            raise ImportError(
                f"game {game_number}: {game.errors[0]}; correct the PGN and reload"
            )
        variant = game.headers.get("Variant")
        if variant and variant.lower() not in {"standard", "chess"}:
            raise ImportError(
                f"game {game_number}: unsupported Variant {variant!r}; use standard chess and reload"
            )
        setup = game.headers.get("SetUp")
        if setup not in {None, "0", "1"}:
            raise ImportError(
                f"game {game_number}: SetUp must be 0 or 1; correct the PGN and reload"
            )
        if setup == "1" and "FEN" not in game.headers:
            raise ImportError(
                f"game {game_number}: SetUp 1 requires a FEN tag; correct the PGN and reload"
            )
        try:
            parse_fen(game.headers.get("FEN", chess.STARTING_FEN))
        except PositionValidationError as exc:
            raise ImportError(f"game {game_number}: {exc}") from exc
        marker = game.headers.get("Result")
        if marker is not None and marker != result:
            raise ImportError(
                f"game {game_number}: Result header does not match movetext; correct the PGN and reload"
            )
        games.append(game)
    if not games:
        raise ImportError("PGN contains no games; add a complete game and reload")
    return ImportedDocument(tuple(games), has_history=True)


def import_fen_text(text: str) -> ImportedDocument:
    fen = text.strip().lstrip("\ufeff")
    try:
        board = parse_fen(fen)
    except PositionValidationError as exc:
        raise ImportError(str(exc)) from exc
    game = chess.pgn.Game()
    if board.fen(en_passant="fen") != chess.STARTING_FEN:
        game.headers["SetUp"] = "1"
        game.headers["FEN"] = board.fen(en_passant="fen")
    game.headers["Result"] = "*"
    return ImportedDocument((game,), has_history=False)

