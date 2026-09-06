# Changelog

Completed changes are grouped by milestone, newest first.

## Unreleased

### Milestone 2

- Added identity-bearing attack/defence relationships, undefended-piece facts,
  latent rays, and before/after continuity through captures, castling, en passant,
  and every promotion type.
- Added bounded exchange and forcing analysis, focused move/piece probes, and
  qualified safety, trapping, material-exposure, and conflicting-duty assessments
  with explicit evidence, omissions, and coverage.
- Added connected move accounts, automatic position attention, immediate
  candidate comparisons, richer `changes`/inspection/details, and read-only
  previews. Shared schema-version-4 views retain fact sources, identities,
  selection limits, and navigation references for a later GUI.
- Connected complex discoveries, explicit checker roles, double checks, and
  structural forks with bounded checking-threat response evidence, keeping
  capture availability separate from material-gain claims.
- Condensed progress and score output, and consolidated repeated catalog loads,
  fact and assessment computation, PGN preparation, and exposure rendering.
- Added persistent shared orientation defaults, import overrides, and local
  flipping without changing chess state or score perspective.
- Formalized unique case-insensitive move shorthand in PGN imports and typed
  commands, inferring omitted capture/check/mate effects while retaining strict
  legality, structural validation, and canonical in-memory SAN.
- Hardened stale-request rejection, terminal-position boundaries, cancellation,
  and replacement handling; verified shared references, source preservation, and
  complete CLI/Stockfish workflows through independent reviews.

### Milestone 1

- Delivered an interactive CLI for bounded PGN/FEN import, game and variation
  navigation, composed positions, and in-memory trial moves without rewriting
  imported files.
- Added shared static board facts, piece identities, geometric attacks, legal
  access, absolute pins, and move deltas.
- Integrated persistent Stockfish analysis and candidate comparison with bounded
  work, explicit White-perspective scores, and legally replayed tactical evidence.
- Added candidate tables, editable explanation text, evidence details, and
  versioned shared JSON snapshots for future interfaces.
- Verified transactional imports, revision-safe updates, cancellation, engine
  startup/shutdown, UTF-8 Windows streams, and the 32-piece engine boundary.

### Project Setup

- Established the Python 3.13 package, pytest environment, python-chess dependency,
  and ignored machine-local Stockfish installation.
- Defined product goals, layer boundaries, working rules, documentation ownership,
  and the narrow local-file defense model.
- Standardized project naming and layout; separated PGN/FEN interchange, settings,
  and derived analysis, deferring SQLite until justified by actual needs.
- Bundled the MPChess SVG piece set with pinned provenance, licensing notices,
  and a shared twelve-piece theme contract.
