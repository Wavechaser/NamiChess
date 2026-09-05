"""NamiChess composition root."""

from __future__ import annotations

import asyncio

from namichess.interfaces.cli import run_cli
from namichess.application.session import Session


def main() -> int:
    return asyncio.run(run_cli(Session()))
