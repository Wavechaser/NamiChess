# NamiChess

NamiChess is a local, rating-agnostic chess-analysis and training project. Its
purpose is to explain what a position permits, what a move changes, which threats
matter, and which sufficiently strong continuation a human can understand and
keep playing.

The project is in pre-implementation setup. The product definition is in
[chess-copilot-spec.md](chess-copilot-spec.md).

## Current state

- Python package and test environment established.
- `python-chess` available for board representation and rules.
- Stockfish 18 installed as an ignored machine-local tool.
- Product, architecture, feature, defense, and defect documents established.
- Position analysis and user interfaces are not implemented yet.

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

The application will later accept an explicit engine path, with this location
as the development default. It will not download engines or contact remote
services at runtime.

## Persistence

SQLite is deliberately deferred. NamiChess imports, parses, saves, and exports
PGN games and FEN positions; small app-owned settings, metadata, and derived
analysis use separate versioned UTF-8 JSON. Imported files are read-only inputs,
and exports use distinct user-confirmed paths.

## Documentation

- [Product specification](chess-copilot-spec.md)
- [Features](docs/FEATURES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Defense](docs/DEFENSE.md)
- [Bugs](docs/BUGS.md)
- [Changelog](CHANGELOG.md)
- [Working rules](AGENTS.md)

## License

NamiChess is licensed under GPL-3.0-or-later. Stockfish and python-chess have
their own GPL distribution obligations; packaging must preserve those licenses
and corresponding-source requirements.
