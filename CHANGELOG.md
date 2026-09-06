# Changelog

Completed project changes are recorded here newest-first.

## Unreleased

### M2 final acceptance — 2026-09-06

- Verified Unicode multi-game imports, exact source-file preservation, special
  moves, comparison and read-only previews, shared references, orientation,
  focused probes, cancellation/retry, and failure recovery across the CLI.
- Exercised fifty rapid replacements plus navigation submissions with one
  active and one pending request maximum and complete worker settlement.
- Completed independent architecture and interface reviews, interactive Windows
  checks, 283 ordinary tests with 10 optional skips, and 293 Stockfish-enabled
  tests; archived the accepted M2 plan. Actual GUI work remains deferred.

### M2 shared explanations and focused CLI — 2026-09-06

- Added `changes`, focused move and piece probes, detailed evidence, and
  orientation-aware read-only candidate-line boards including ply zero.
- Added immediate navigation references and typed local assessments to shared
  schema-version-2 snapshots for CLI and non-CLI consumers.
- Replaced count-only move summaries with capped priority facts and complete
  identity-bearing relationship detail on demand; shared catalog prose names
  each assessment subject and preserves the limits of its evidence.

### Terminal local-analysis boundary — 2026-09-06

- Stop local exploration at automatic terminal positions before enumerating
  roots or replies, including insufficient material and automatic draws that
  still have geometric legal moves.
- Preserve checkmate precedence and distinguish claimable draws from automatic
  game endings; report no fictional post-game continuations or reply coverage.

### M2 qualified local assessments — 2026-09-06

- Added immutable move-safety and piece-trapping assessments with explicit
  reply or legal-exit coverage, replay-verified immediate mate failures, and
  truthful incomplete and no-refutation-found results.
- Added model-qualified per-exit material exposure that accounts for root gains
  while keeping negative exchange evidence separate from move soundness and
  sacrifice compensation.
- Added witnessed conflicting-duty evidence for narrow overload candidates,
  requiring legal identity-bearing continuations while leaving universal
  overload claims unsupported.

### M2 bounded local exploration and focused probes — 2026-09-06

- Added cancelable depth-four local exploration for checks, captures,
  promotions, direct attacks, and focused move or piece probes, with replayable
  per-reply continuity and exchange evidence.
- Exposed immutable probe subjects, local limits, omissions, termination
  reasons, and coverage through application analysis results while preserving
  engine candidates when local material evidence is negative.
- Kept ordinary local work within 250 ms and focused local work within one
  second of a fifteen-second focused request, sharing the 10,000-node allowance
  and cooperative yield accounting with nested exchange search.

### Stale analysis submission boundary — 2026-09-06

- Reject obsolete supplied session views before resolving comparison moves or
  submitting analysis, preserving the selected position and controller state.

### M2 bounded local exchange evaluation — 2026-09-06

- Added asynchronous target-square capture/recapture minimax with legal stop
  decisions, recomputed x-rays, special-move accounting, and replayable typed
  material evidence.
- Bounded exchange work by an injected deadline and 4,096 expanded positions,
  with distinct unsupported and incomplete results that cannot filter engine
  candidates.

### M2 structural continuity — 2026-09-06

- Added identity-bearing attack and geometric-defence contacts, undefended-piece
  facts, and latent slider rays with exact move deltas across special moves.
- Advanced shared snapshots to schema version 2 while preserving version-1 field
  meanings and encodings.

### M2 shared orientation — 2026-09-06

- Added one versioned shared orientation default, local CLI board flipping, and
  import/process overrides without changing canonical position or analysis state.

### M2 shared interface contract — 2026-09-06

- Extracted schema-version-1 snapshot serialization from CLI rendering into an
  interface-neutral adapter without changing its wire shape.
- Recorded the active M2 checkpoint plan and clarified that M2 prepares shared
  views for a later GUI while orientation defaults remain shared settings.

### M2 scope discussion — 2026-09-06

- Recorded proposed continuity-first analysis, bounded local tactical assessments,
  promotion coverage, and board orientation behavior in the feature roadmap.
  These are planned features, not delivered runtime changes.

### M1 documentation archive — 2026-09-06

- Retired the accepted M1 implementation plan and combined invariant review to
  `docs/obsolete/`; active CLI/API and durable architecture contracts remain in
  their owning references.

### Interactive analysis workflow — 2026-09-06

- Connected navigation to revision-safe bounded analysis, legal two-move
  comparison, awaited cancellation, explicit engine paths, and clean shutdown.
- Added concise candidate tables, catalog-backed facts, detailed SAN evidence,
  move-change summaries, and complete `schema_version: 1` JSON snapshots from
  the same shared application view.
- Closed the combined lifecycle audit with request-scoped cancellation,
  absorbing shared close, one aggregate startup deadline, bounded child-process
  reaping, UTF-8 native streams, and joined real CLI/Stockfish verification.

### Candidate comparison and tactical evidence — 2026-09-06

- Added deterministic bounded candidate surveys and focused probes with typed
  White-perspective scores, explicit bounds, legal coverage, and stable IDs
  independent of rank.
- Added legally replayed evidence for checks, mate in one, captures, recaptures,
  promotions, material changes, and survey/probe disagreement without inferring
  unsearched alternatives.

### Strict PGN move notation — 2026-09-06

- Reject false or missing check/mate suffixes and nonstandard coordinate or
  overspecified SAN in imported games and variations, with actionable errors.
- Preserve the current session after rejection; retain SAN/UCI support for trial moves.

### Persistent Stockfish adapter — 2026-09-06

- Added an asynchronous, reusable engine adapter with legal history/PV checks,
  perspective-explicit scores and bounds, and the 32-piece engine boundary.
- Covered startup, cancellation, failure, and shutdown ownership with fake-engine
  regressions and guarded ordinary/composed-position Stockfish integration tests.

### Shared static position facts — 2026-09-06

- Added identity-bearing geometric attacks, actual-side legal moves, absolute
  pins, check facts, and reconstructable move deltas to shared session views.
- Added `inspect <square>` rendering from the shared facts, preserving the
  distinction between geometric attack and legal access.

### PGN/FEN CLI navigation — 2026-09-06

- Added strict, bounded PGN and FEN import with composed-material support,
  transactional failures, retained histories, and immutable shared position views.
- Added the interactive `namichess` CLI for ASCII board display, game/variation
  navigation, and in-memory SAN/UCI trial moves without changing imported files.

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
