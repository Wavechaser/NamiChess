"""NamiChess composition root."""

from __future__ import annotations

import asyncio
import argparse
from importlib.resources import files
from pathlib import Path

from namichess.analysis.engine import StockfishAdapter
from namichess.application.analysis import AnalysisController
from namichess.application.session import Session
from namichess.interfaces.explanations import ExplanationCatalog
from namichess.interfaces.cli import configure_standard_streams, run_cli


def main() -> int:
    configure_standard_streams()
    parser = argparse.ArgumentParser(prog="namichess")
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(".tools/stockfish/stockfish-windows-x86-64-avx2.exe"),
        help="path to the Stockfish executable",
    )
    args = parser.parse_args()
    catalog = ExplanationCatalog.load(Path(str(files("namichess").joinpath("content", "explanations.json"))))
    controller = AnalysisController(StockfishAdapter(args.engine))
    return asyncio.run(run_cli(Session(), controller=controller, catalog=catalog))
