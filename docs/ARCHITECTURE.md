# NamiChess Architecture

**Status:** pre-implementation · **Scope:** durable boundaries and data flow

## 1. System shape

NamiChess is a local, rating-agnostic chess-analysis and training application.
Its backend explains positions and ranks executable decisions rather than merely
returning engine order. A Windows 11 GUI or CLI is an adapter around the same
platform-agnostic application use cases.

```text
interfaces  →  application  →  analysis  →  domain
                         ↘ adapters at composition root
```

- `domain` owns typed chess positions, moves, piece-square facts, and rules. It
  may use python-chess but knows nothing about Stockfish, files, presets, or text.
- `analysis` derives static facts, compares candidates, verifies tactical claims,
  and consumes an immutable per-job analysis policy.
- `application` owns use cases, settings semantics, job sequencing, progressive
  results, training records, and persistence coordination.
- `interfaces` collect requests, establish explicit file paths, edit settings,
  and render results. They own no chess or engine policy.
- `composition.py` wires concrete storage, PGN/FEN codecs, explanation content,
  the engine manager, and interfaces.

No initial database, remote service, plugin system, distributed worker, or
generalized message bus is required.

## 2. Analysis flow

```text
PGN/FEN/board input + resolved settings
                 ↓
validated position and move context
                 ↓
piece-square facts and move deltas
                 ↓
candidate, threat, and principle assessment
                 ↓
bounded Stockfish survey and verification
                 ↓
adequate moves + structured explanation evidence
                 ↓
progressive view + optional saved analysis
```

The shared model keeps geometric control, legal access, and tactical ownership
separate. It exposes important squares, piece profiles, move deltas, threats,
opened rays, mobility, duties, routes, and enabled resources. Counts retain piece
identities and never prove safety by themselves.

Static analysis proposes facts and causal hypotheses; search verifies or rejects
tactical claims. Engine values belong to resulting positions and may be
attributed to a square or piece only with a verified causal delta. Safety and
adequacy gate candidates before continuation burden ranks them.

Analysis starts with the user-selected candidate breadth and verification effort.
Critical, unstable, sacrificial, or shallow/deep-disputed claims receive deeper
probes. Long forcing lines may remain legible; opaque branches switch to plans,
triggers, and durable routes. Unsearched moves remain unknown.

## 3. Settings and analysis policy

The interface provides `Foundation`, `Club`, and `Advanced` presets plus a small
set of semantic overrides:

- search effort: `quick`, `normal`, or `thorough`;
- candidate breadth: `narrow`, `balanced`, or `wide`;
- continuation burden: `steadfast`, `balanced`, or `exacting`;
- visible explanation layers, including principles, pieces, pawn structure, and
  advanced strategy;
- resource use: `light`, `balanced`, or `maximum`.

`AnalysisPreferences` stores a base preset and sparse overrides. Changing a
preset value yields `Custom` based on that preset; restoring it removes the
overrides. The application resolves preferences and position context into one
immutable `AnalysisPolicy` when a job starts. Interfaces never translate a
setting directly into UCI options.

Settings affect future jobs. Each saved analysis snapshots its resolved policy,
analyzer version, Stockfish version, and relevant engine options so later preset
changes do not reinterpret prior results.

User settings live in versioned UTF-8 `settings.json`, separate from games and
analysis. Writes use temporary-file replacement. Invalid settings produce a
visible fallback while preserving the invalid file for recovery.
Appearance preferences such as the selected piece theme share the settings file
but remain separate from `AnalysisPreferences` and never affect `AnalysisPolicy`.

## 4. Explanation content

Analysis returns structured facts, evidence, a stable explanation identifier,
and typed values. User-facing prose is resolved from a bundled UTF-8 catalog at
`namichess/content/explanations.json`. Editing that catalog changes wording
without changing Python analysis code.

The catalog contains text templates only. It cannot contain chess policy,
executable expressions, paths, or unverified claims. Startup validation and tests
ensure every identifier exists and every placeholder matches its typed values.
Bundled explanation content is installation data, not mutable user data.

## 5. Piece themes

MPChess is the bundled default under GPL-3.0-only. Bundled assets live at
`namichess/interfaces/web/assets/pieces/mpchess/`; their attribution, pinned
source revision, and license travel with every distribution.

Every theme implements one data contract: twelve standalone SVG files named
`wK.svg`, `wQ.svg`, `wR.svg`, `wB.svg`, `wN.svg`, `wP.svg`, and their `b*`
counterparts. A theme resolver maps the selected theme and logical piece code to
an opaque local asset URL. The board always uses the same image renderer; it has
no MPChess-, custom-, or per-piece rendering branches.

Custom-theme import starts from a user-selected directory, validates the twelve
required SVG names, roots and view boxes, then copies them and any supported
license notice into
`user-data/themes/<theme-id>/`. Settings retain the built-in theme name or an
app-owned custom theme identifier, never an arbitrary source path. SVGs are
rendered as images rather than injected as inline markup, under a policy that
blocks scripts and external resources. Invalid themes do not replace the active
theme, and the bundled default is always recoverable.

## 6. PGN, FEN, and local records

PGN import parses one or more games, headers, moves, and relevant variation trees
into validated positions. FEN import parses and validates a single position,
including side to move, castling rights, en-passant state, and move counters.
Users can select any resulting ply for analysis.

Imported files are read-only inputs. App-owned chess content remains PGN or FEN;
settings, derived analysis, training responses, and metadata use separate,
versioned JSON records linked by app-owned identifiers. Save and export always
use an explicit destination and never overwrite an import implicitly.

```text
user-data/
  settings.json
  games/
  positions/
  analysis/
  themes/
```

Persistence adapters are injected at the composition root. Interfaces establish
path authority through native CLI arguments or GUI file pickers; a browser or
local API cannot submit arbitrary paths. SQLite remains deferred until measured
volume or query needs make JSON and simple indexes insufficient.

## 7. Execution model

The Python application owns a nonblocking, bounded, cancelable analysis queue.
Initially it manages one persistent Stockfish child process and streams partial
results to the interface. Foreground work takes priority, and a newer request may
cancel obsolete work. The interface never waits synchronously for engine search.

Ordinary CPython is GIL-bound for CPU-heavy Python bytecode. Stockfish is a native
external process, so its own search threads are outside the Python GIL. The engine
manager maps semantic policy to explicit Stockfish `Threads`, `Hash`, `MultiPV`,
and search limits while enforcing one global CPU budget:

```text
engine processes × threads per engine ≤ configured CPU budget
```

Cheap 64-square Python analysis remains sequential until profiling shows a real
bottleneck. Measured CPU-heavy batch work may use process workers; Python threads
are for orchestration and I/O, not assumed multicore speedup. Multiple Stockfish
processes are added only for a demonstrated batch-analysis need.

## 8. Ownership and verification

The domain owns chess truth. Analysis owns evidence and verification. The
application owns policy resolution, sequencing, and durable record assembly.
Interfaces own presentation state and platform behavior. The explanation catalog
owns prose only. Serialized records and views never become competing authorities.

Tests mirror package boundaries and use named PGN/FEN fixtures. Required coverage
includes:

- perspective-sensitive chess facts and unsupported SEE/engine cases;
- candidate adequacy, shallow/deep disagreement, cancellation, foreground
  priority, and resource limits;
- preset resolution, sparse overrides, settings fallback, and atomic replacement;
- explanation identifier and placeholder completeness;
- bundled and custom theme contract validation, package inclusion, safe image
  rendering, and fallback to MPChess;
- malformed and multi-game PGN, FEN field validation, notation/header round trips,
  ply selection, and prevention of source overwrite.

Architecture changes update this document whenever they alter dependency
direction, durable formats, analysis ownership, or interface contracts.
