"""Strict, bounded import of PGN and FEN chess documents."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import io
import re

import chess.pgn

from namichess.domain.notation import relaxed_san_matches, resolve_legal_move
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
    def __init__(self, budget: _ParseBudget, original_moves: deque[str]) -> None:
        super().__init__()
        self._budget = budget
        self._original_moves = original_moves
        self.sans: list[str] = []

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
        self.sans.append(board.san(move))
        return super().visit_move(board, move)

    def parse_san(self, board: chess.Board, san: str) -> chess.Move:
        original = self._original_moves.popleft() if self._original_moves else san
        if san in {"--", "Z0", "0000", "@@@@", "*"}:
            return board.parse_san(san)
        try:
            return resolve_legal_move(board, original)
        except ValueError as exc:
            if original.endswith(("+", "#")):
                try:
                    return resolve_legal_move(board, original[:-1])
                except ValueError:
                    pass
            raise ValueError(f"illegal san: {original!r}") from exc


_MOVE_NUMBER = re.compile(r"\d+\.(?:\.\.)?")
_RELAXED_MOVETEXT_REGEX = re.compile(
    r"""
    (
        [NBKRQnbkrq]?[A-Ha-h]?[1-8]?[\-xX]?[A-Ha-h][1-8](?:=?[nbrqkNBRQK])?
        |[PNBRQKpnbrqk]?@[A-Ha-h][1-8]
        |--|Z0|0000|@@@@
        |[Oo0]-[Oo0](?:-[Oo0])?
    )
    |(\{.*)|(;.*)|(\$[0-9]+)|(\()|(\))
    |(\*|1-0|0-1|1/2-1/2)|([\?!]{1,2})
    """,
    re.VERBOSE | re.DOTALL,
)
_PAWN_SAN = re.compile(r"[a-h](?:x[a-h])?[1-8](?:=?[nbrqk])?")


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


def _validate_tokens(segment: str, game_number: int, expected_sans: tuple[str, ...]) -> str:
    text = _mask_comments_and_headers(segment, game_number)
    offset = 0
    depth = 0
    result: str | None = None
    san_index = 0
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
        token_match = _RELAXED_MOVETEXT_REGEX.match(text, offset)
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
        elif token.startswith(("$", "?", "!")):
            pass
        else:
            token_end = token_match.end()
            if token_end < len(text) and text[token_end] in "+#":
                token_end += 1
            actual_san = text[offset:token_end]
            if san_index >= len(expected_sans):
                raise _problem(game_number, segment, offset, f"unrecognized SAN {actual_san!r}")
            expected_san = expected_sans[san_index]
            if not relaxed_san_matches(actual_san, expected_san):
                raise _problem(
                    game_number,
                    segment,
                    offset,
                    f"noncanonical SAN {actual_san!r}; use {expected_san!r}",
                )
            san_index += 1
        offset = token_match.end()
        if offset < len(text) and text[offset] in "+#":
            offset += 1
    if depth:
        raise _problem(game_number, segment, len(segment) - 1, "unclosed variation parenthesis")
    if result is None:
        raise _problem(game_number, segment, max(0, len(segment) - 1), "missing terminating result marker")
    if san_index != len(expected_sans):
        raise _problem(game_number, segment, len(segment), "incomplete movetext")
    return result


def _normalize_move_tokens(text: str) -> str:
    masked = _mask_non_movetext(text)
    normalized = list(text)
    for match in _RELAXED_MOVETEXT_REGEX.finditer(masked):
        token = match.group(0)
        projected = _project_move_token(token)
        if projected is not None:
            normalized[match.start():match.end()] = projected
    return "".join(normalized)


def _mask_non_movetext(text: str) -> str:
    masked = list(text)
    in_comment = False
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if not in_comment and (line.lstrip().startswith("[") or line.startswith("%")):
            masked[offset:offset + len(line)] = " " * len(line)
            offset += len(raw_line)
            continue
        for index, character in enumerate(line):
            absolute = offset + index
            if in_comment:
                masked[absolute] = " "
                if character == "}":
                    in_comment = False
            elif character == "{":
                in_comment = True
                masked[absolute] = " "
            elif character == ";":
                masked[absolute:offset + len(line)] = " " * (len(line) - index)
                break
        offset += len(raw_line)
    return "".join(masked)


def _project_move_token(token: str) -> str | None:
    if not token or token in {"(", ")", "*", "1-0", "0-1", "1/2-1/2"}:
        return None
    if token.startswith(("$", "?", "!", "{", ";")):
        return None
    lowered = token.lower()
    if lowered in {"o-o", "0-0"}:
        return "O-O"
    if lowered in {"o-o-o", "0-0-0"}:
        return "O-O-O"
    if _PAWN_SAN.fullmatch(lowered):
        return lowered
    return token[0].upper() + lowered[1:]


def _original_move_tokens(text: str) -> deque[str]:
    masked = _mask_non_movetext(text)
    moves: deque[str] = deque()
    depth = 0
    for match in _RELAXED_MOVETEXT_REGEX.finditer(masked):
        token = match.group(0)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)
        elif token in {"1-0", "0-1", "1/2-1/2", "*"} and not depth:
            continue
        elif _project_move_token(token) is not None:
            end = match.end()
            if end < len(text) and text[end] in "+#":
                token += text[end]
            moves.append(token)
    return moves


def import_pgn_text(text: str) -> ImportedDocument:
    source = text.lstrip("\ufeff")
    handle = io.StringIO(_normalize_move_tokens(source))
    original_moves = _original_move_tokens(source)
    games: list[chess.pgn.Game] = []
    budget = _ParseBudget()
    while True:
        start = handle.tell()
        builder = _StrictBuilder(budget, original_moves)
        try:
            game = chess.pgn.read_game(handle, Visitor=lambda: builder)
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
        result = _validate_tokens(segment, game_number, tuple(builder.sans))
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
