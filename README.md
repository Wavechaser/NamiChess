# NamiChess

NamiChess is a local, rating-agnostic chess-analysis and training project. Its
purpose is to explain what a position permits, what a move changes, which threats
matter, and which sufficiently strong continuation a human can understand and
keep playing.

The project is implementing its first milestone. Strict PGN/FEN import,
interactive CLI navigation, and shared static board facts are available;
engine-backed analysis remains in progress. The product definition is in
[docs/chess-copilot-spec.md](docs/chess-copilot-spec.md), and the decision-complete
milestone gates are in [docs/M1-PLAN.md](docs/M1-PLAN.md).

## Current state

- Python package, test environment, and `namichess` CLI established.
- `python-chess` available for board representation and rules.
- Stockfish 18 installed as an ignored machine-local tool.
- Product, architecture, feature, defense, and defect documents established.
- MPChess SVG pieces bundled for the future board interface.
- M1 can strictly load and navigate PGN/FEN positions, including composed
  standard-chess positions with unusual material. Shared views expose geometric
  attacks, actual-side legal moves, absolute pins, and the previous move delta;
  `inspect <square>` renders those facts. Stockfish analysis remains in progress.

## Requirements

- Windows 11 x64 for the initial headed application.
- Python 3.13; the established development runtime is 3.13.14.
- Stockfish 18. The current setup uses the official Windows x86-64 AVX2 build.

The backend remains platform- and interface-agnostic. Windows-specific GUI,
packaging, and file-picker behavior belongs in interface adapters.

## Setup

Create the virtual environment from Python 3.13 and install the editable
development package:

```powershell
py -3.13 -m venv .venv --prompt NamiChess
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The Stockfish executable is machine-local and not committed. Place the official
Stockfish 18 executable at:

```text
.tools\stockfish\stockfish-windows-x86-64-avx2.exe
```

The established archive is the official `sf_18` Windows AVX2 release. Its
SHA-256 is `6f6c272ebd6ea594377715235c8a7326f75940ef4f4f856f45106028fe6ae900`.

Verify the environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
& '.\.tools\stockfish\stockfish-windows-x86-64-avx2.exe' compiler
```

Start an interactive session:

```powershell
namichess
```

Use `load <path>` for a UTF-8 `.pgn` or `.fen` file, or enter a complete
six-field position with `fen <FEN>`. `games`, `game <n>`, `start`, `end`,
`next`, `back`, `goto <ply>`, `variations`, `variation <n>`, and
`move <SAN-or-UCI>` navigate without changing the imported file. Run `help`
inside the session for the compact command list.

The application will later accept an explicit engine path, with this location
as the development default. It will not download engines or contact remote
services at runtime.

## Persistence

SQLite is deliberately deferred. NamiChess imports, parses, saves, and exports
PGN games and FEN positions; small app-owned settings, metadata, and derived
analysis use separate versioned UTF-8 JSON. Imported files are read-only inputs,
and exports use distinct user-confirmed paths.

## Documentation

- [Product specification](docs/chess-copilot-spec.md)
- [Features](docs/FEATURES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [M1 implementation plan](docs/M1-PLAN.md)
- [Defense](docs/DEFENSE.md)
- [Bugs](docs/BUGS.md)
- [Changelog](CHANGELOG.md)
- [Working rules](AGENTS.md)

## License

NamiChess is licensed under GPL-3.0-or-later. Stockfish and python-chess have
their own GPL distribution obligations; packaging must preserve those licenses
and corresponding-source requirements. Bundled third-party artwork is identified
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
