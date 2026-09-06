"""NamiChess composition root."""

from __future__ import annotations

import asyncio
import argparse
import os
from importlib.resources import files
from pathlib import Path

from namichess.analysis.engine import StockfishAdapter
from namichess.application.analysis import AnalysisController
from namichess.application.session import Session
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.interfaces.cli import configure_standard_streams, run_cli
from namichess.interfaces.orientation import Orientation
from namichess.interfaces.settings import SettingsStore


def main() -> int:
    configure_standard_streams()
    parser = argparse.ArgumentParser(prog="namichess")
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(".tools/stockfish/stockfish-windows-x86-64-avx2.exe"),
        help="path to the Stockfish executable",
    )
    parser.add_argument(
        "--orientation",
        choices=tuple(item.value for item in Orientation),
        help="orientation used for imports unless the import command overrides it",
    )
    args = parser.parse_args()
    catalog = ExplanationCatalog.load(Path(str(files("namichess").joinpath("content", "explanations.json"))))
    controller = AnalysisController(StockfishAdapter(args.engine))
    settings_store = SettingsStore(_settings_path())
    orientation_override = Orientation(args.orientation) if args.orientation is not None else None
    return asyncio.run(
        run_cli(
            Session(), controller=controller, catalog=catalog, settings_store=settings_store,
            orientation_override=orientation_override,
        )
    )


def _settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "NamiChess" / "settings.json"
