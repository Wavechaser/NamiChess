# Changelog

Completed project changes are recorded here newest-first.

## Unreleased

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
