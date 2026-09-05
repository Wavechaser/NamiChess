"""Piece-theme asset contract tests."""

from importlib.resources import files
from xml.etree import ElementTree


PIECE_NAMES = {
    f"{color}{piece}.svg"
    for color in ("b", "w")
    for piece in ("B", "K", "N", "P", "Q", "R")
}
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def test_bundled_mpchess_theme_satisfies_piece_contract() -> None:
    theme = files("namichess").joinpath(
        "interfaces", "web", "assets", "pieces", "mpchess"
    )

    assert {asset.name for asset in theme.iterdir() if asset.name.endswith(".svg")} == (
        PIECE_NAMES
    )
    assert theme.joinpath("LICENSE").is_file()

    for name in PIECE_NAMES:
        root = ElementTree.fromstring(theme.joinpath(name).read_bytes())
        assert root.tag == f"{{{SVG_NAMESPACE}}}svg"
        assert root.attrib.get("viewBox")
        assert all(
            element.tag != f"{{{SVG_NAMESPACE}}}script" for element in root.iter()
        )
        assert all(
            not attribute.endswith("href") or value.startswith("#")
            for element in root.iter()
            for attribute, value in element.attrib.items()
        )
