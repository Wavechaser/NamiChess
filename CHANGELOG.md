# Changelog

Completed project changes are recorded here newest-first.

## Unreleased

### Project setup — 2026-09-05

- Established the Python 3.13 package, virtual environment, and pytest smoke test.
- Added `python-chess` and an ignored machine-local Stockfish 18 installation.
- Defined project working rules, architecture, features, defense scope, and
  defect tracking.
- Deferred SQLite in favor of PGN, FEN, and versioned JSON until query needs
  justify a database.
