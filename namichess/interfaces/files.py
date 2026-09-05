"""Native CLI file boundary for explicitly supplied chess files."""

from __future__ import annotations

from pathlib import Path

from namichess.application.imports import ImportError

MAX_FILE_BYTES = 10 * 1024 * 1024


def read_chess_file(path: str) -> tuple[str, str]:
    suffix = Path(path).suffix.lower()
    if suffix not in {".pgn", ".fen"}:
        raise ImportError("file must have a .pgn or .fen extension; choose a supported file and reload")
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise ImportError(f"could not read {path!r}: {exc}; correct the path and retry") from exc
    if len(data) > MAX_FILE_BYTES:
        raise ImportError(
            f"file exceeds size limit {MAX_FILE_BYTES} bytes; reduce the file and reload"
        )
    try:
        return suffix, data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportError(
            f"file is not valid UTF-8 at byte {exc.start}; save it as UTF-8 and reload"
        ) from exc
