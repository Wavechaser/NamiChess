import asyncio
import io

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from namichess.application.session import Session
from namichess.interfaces.cli import execute, run_cli


def test_cli_fen_board_move_and_navigation_transcript() -> None:
    session = Session()
    output, done = execute(session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1")
    assert "a b c d e f g h" in output
    assert "Turn: white" in output
    assert not done
    output, _ = execute(session, "move Ka2")
    assert "Turn: black" in output
    output, _ = execute(session, "back")
    assert "Turn: white" in output


def test_cli_games_lists_fen_as_one_game() -> None:
    session = Session()
    execute(session, "fen 7k/8/8/8/8/8/8/K7 w - - 0 1")
    output, _ = execute(session, "games")
    assert "* 1:" in output


def test_cli_load_accepts_a_quoted_windows_path_with_spaces(tmp_path) -> None:
    source = tmp_path / "sample game.pgn"
    source.write_text("1. e4 *\n", encoding="utf-8")
    output, _ = execute(Session(), f'load "{source}"')
    assert "Turn: black" in output


def test_interactive_prompt_path_accepts_commands() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text("fen 7k/8/8/8/8/8/8/K7 w - - 0 1\nquit\n")
        result = asyncio.run(
            run_cli(Session(), stdout=stdout, stderr=stderr, prompt_input=pipe, prompt_output=DummyOutput())
        )
    assert result == 0
    assert "Turn: white" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_invalid_large_counter_keeps_session_and_cli_running() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    session = Session()
    commands = io.StringIO(
        "fen 7k/8/8/8/8/8/4P3/K7 w - - 0 1\n"
        + "fen 7k/8/8/8/8/8/4P3/K7 w - - 0 " + "9" * 5000
        + "\nboard\nquit\n"
    )
    result = asyncio.run(run_cli(session, stdin=commands, stdout=stdout, stderr=stderr))
    assert result == 0
    assert "fullmove counter" in stderr.getvalue()
    assert "1000000000" in stderr.getvalue()
    assert "correct the FEN and reload" in stderr.getvalue()
    assert stdout.getvalue().count("Turn: white") == 2
    assert session.view().revision == 1
