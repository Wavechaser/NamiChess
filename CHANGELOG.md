# Changelog

Completed project changes are recorded here newest-first.

## Unreleased

### M1 documentation — 2026-09-06

- Defined the CLI-first M1 checkpoint sequence for PGN/FEN navigation, shared
  position views, static facts, and bounded Stockfish candidate evidence.
- Recorded composed-position support and the 32-occupied-square engine boundary.
- Deferred GUI, recall/training, practical-best ranking, broad threat assessment,
  SEE, and persistence; excluded Syzygy integration and redistribution.

### Board assets — 2026-09-06

- Bundled Maxime Chupin's GPL-3.0-only MPChess SVG piece set with pinned provenance and
  redistribution notices.
- Defined one twelve-file SVG contract and rendering path for the bundled default
  and app-owned custom themes.

### Project layout — 2026-09-05

- Moved the `namichess` package from the `src` layout to the repository root and
  updated package discovery.
- Moved the core product specification under `docs/` and standardized project
  identifiers and command naming on `namichess`.

### Documentation — 2026-09-05

- Made the product rating-agnostic through Foundation, Club, and Advanced presets
  with sparse user overrides and reproducible per-analysis policy snapshots.
- Defined separate settings, PGN/FEN, derived-analysis, and editable explanation
  content boundaries.
- Documented the GIL-aware Python/Stockfish execution model and narrowed defense
  claims to concrete local authority and file risks.
- Removed unenforceable restrictions based on inferred user intent.

### Project setup — 2026-09-05

- Established the Python 3.13 package, virtual environment, and pytest smoke test.
- Added `python-chess` and an ignored machine-local Stockfish 18 installation.
- Defined project working rules, architecture, features, defense scope, and
  defect tracking.
- Deferred SQLite in favor of PGN, FEN, and versioned JSON until query needs
  justify a database.
