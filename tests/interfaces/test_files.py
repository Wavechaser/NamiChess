import hashlib

import pytest

from namichess.application.imports import ImportError
from namichess.interfaces.files import MAX_FILE_BYTES, read_chess_file


def test_read_chess_file_preserves_source(tmp_path) -> None:
    source = tmp_path / "game with spaces.pgn"
    source.write_bytes(b"\xef\xbb\xbf1. e4 *\r\n")
    before = hashlib.sha256(source.read_bytes()).digest()
    suffix, text = read_chess_file(str(source))
    assert suffix == ".pgn"
    assert text == "1. e4 *\r\n"
    assert hashlib.sha256(source.read_bytes()).digest() == before


def test_read_chess_file_rejects_invalid_utf8(tmp_path) -> None:
    source = tmp_path / "bad.pgn"
    source.write_bytes(b"1. e4 \xff *")
    with pytest.raises(ImportError, match="valid UTF-8"):
        read_chess_file(str(source))


def test_read_chess_file_rejects_oversized_input_before_decode(tmp_path) -> None:
    source = tmp_path / "large.pgn"
    source.write_bytes(b" " * (MAX_FILE_BYTES + 1))
    with pytest.raises(ImportError, match="size limit"):
        read_chess_file(str(source))
