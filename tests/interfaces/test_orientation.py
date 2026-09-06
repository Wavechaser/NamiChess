from namichess.interfaces.orientation import (
    BoardDisplayState,
    Orientation,
    ResolvedOrientation,
    resolve_orientation,
)


def test_import_resolution_and_local_flips_do_not_depend_on_navigation_turn() -> None:
    state = BoardDisplayState()
    state.apply_import(Orientation.TURN, "black")
    assert state.orientation is ResolvedOrientation.BLACK
    state.flip()
    assert state.orientation is ResolvedOrientation.WHITE
    # The display is intentionally stable while later positions change turn.
    assert state.orientation is ResolvedOrientation.WHITE


def test_explicit_orientation_resolves_without_consulting_turn() -> None:
    assert resolve_orientation(Orientation.WHITE, "black") is ResolvedOrientation.WHITE
    assert resolve_orientation(Orientation.BLACK, "white") is ResolvedOrientation.BLACK
