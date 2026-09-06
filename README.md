# NamiChess

NamiChess is a local, rating-agnostic chess-analysis and training project. Its
purpose is to explain what a position permits, what a move changes, which threats
matter, and which sufficiently strong continuation a human can understand and
keep playing.

M1 and M2 are complete. The interactive CLI joins strict PGN/FEN navigation,
relationship continuity, bounded Stockfish and local evidence, focused probes,
and shared views for a future GUI. The product definition is in
[docs/chess-copilot-spec.md](docs/chess-copilot-spec.md), and current CLI/API
behavior is in [docs/COMMANDLINE.md](docs/COMMANDLINE.md).

## Current state

- Python package, test environment, and `namichess` CLI established.
- `python-chess` available for board representation and rules.
- Stockfish 18 installed as an ignored machine-local tool.
- Product, architecture, feature, defense, and defect documents established.
- MPChess SVG pieces bundled for the future board interface.
- The CLI can strictly load and navigate PGN/FEN positions, including composed
  standard-chess positions with unusual material. Shared views expose geometric
  attacks, actual-side legal moves, absolute pins, and the previous move delta;
  `inspect <square>` renders those facts. Bounded Stockfish analysis, comparison,
  evidence details, and versioned JSON snapshots are available for review.
- M2 adds identity-bearing relationship changes, bounded local exchange and
  forcing evidence, qualified safety/trapping/overload assessments, focused
  probes, connected move accounts, automatic attention, structural candidate
  comparisons, read-only previews, and shared orientation defaults. The
  interactive GUI remains future work.

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
`move <SAN-or-UCI>` navigate without changing the imported file. `inspect`,
`changes`, `analyze`, `compare`, `probe move`, `probe piece`, `details`, `line`,
and `json` expose the shared analysis workflow and read-only evidence previews.
Run `help`
inside the session for the compact command list.

Pass a different local executable with `namichess --engine <path>`. The location
above is the development default. NamiChess does not download engines or contact
remote services at runtime.

## Persistence

SQLite is deliberately deferred. The CLI imports and parses PGN games and FEN
positions; game save and export remain future work. The shared orientation
default uses versioned UTF-8 JSON at `%LOCALAPPDATA%\NamiChess\settings.json`.
Future metadata and derived analysis will be stored separately. Imported
files are read-only inputs, and future exports will use distinct user-confirmed
paths.

## Documentation

- [Product specification](docs/chess-copilot-spec.md)
- [Features](docs/FEATURES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Command-line guide](docs/COMMANDLINE.md)
- [M2 ablation study](docs/M2-ABLATION.md)
- [Historical M1 implementation plan](docs/obsolete/M1-PLAN.md)
- [Historical M1 invariant review](docs/obsolete/M1-INTEGRATION-REVIEW.md)
- [Historical M2 implementation and acceptance plan](docs/obsolete/M2-PLAN.md)
- [Historical M2 consolidation and explanation follow-up](docs/obsolete/M2-EXPLANATION-PLAN.md)
- [Defense](docs/DEFENSE.md)
- [Bugs](docs/BUGS.md)
- [Changelog](CHANGELOG.md)
- [Working rules](AGENTS.md)

## License

NamiChess is licensed under GPL-3.0-or-later. Stockfish and python-chess have
their own GPL distribution obligations; packaging must preserve those licenses
and corresponding-source requirements. Bundled third-party artwork is identified
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
