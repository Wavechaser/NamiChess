# NamiChess Architecture

**Status:** M1 documentation checkpoint · **Scope:** durable boundaries and data flow

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

M1 proves these boundaries through a persistent CLI. The application exposes
immutable `PositionContext`, `SessionView`, `PositionFacts`, `MoveDelta`,
`AnalysisPolicy`, `AnalysisResult`, and `Explanation` values. These carry stable
position, piece, square, move, request, revision, and evidence references. They
never expose mutable boards, PGN nodes, UCI processes, or terminal styling.
Each selected `SessionView` contains its `PositionFacts` and, when the selected
node has a parent, the `MoveDelta` from that parent. Interfaces filter these
shared facts for inspection; they do not reconstruct a board or run chess rules.

## 2. Analysis flow

The following is the future target flow after M1:

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

In the implemented static layer, attacks are geometric contacts for both colors,
while legal moves belong only to the position's actual side to move. Absolute
pins are explicit identity-bearing facts. Move deltas contain only recomputed
before/after facts, including separately labeled slider attack changes; none of
these values alone claims safety or tactical ownership.

For M1, policy is fixed rather than user-configurable: one engine and thread,
64 MiB hash, and five seconds per request. One second surveys up to five root
candidates; remaining time is divided across focused root-move searches,
including up to two explicit comparison moves. M1 reports analyzed rank and
coverage only. Adequacy, practical executability, and comprehensive threat
classification remain later-phase behavior.

M1 uses the narrower flow:

```text
strict PGN/FEN validation and selected position context
                 ↓
shared static facts and move delta
                 ↓
bounded Stockfish survey and focused probes
                 ↓
ranked analyzed evidence with explicit coverage
                 ↓
shared text/JSON-ready application view
```

One outer five-second monotonic search deadline starts after lazy engine startup
and configuration. Survey consumes at most one second and returns at most five
roots. Focused probes cover the unique UCI-sorted union of those roots and up to
two requested comparison moves, capped at seven; no probe starts after deadline.
Deterministic candidate IDs remain stable within a request while rank may change.
Certified rank requires exact typed scores from the original mover's perspective
and uses UCI as a tie-break; incomplete or bounded evidence remains provisional.

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
M2 currently stores only the orientation default (`white`, `black`, or `turn`)
in schema version 1. The composition root creates this interface storage at
`%LOCALAPPDATA%\NamiChess\settings.json`; adapters receive the store rather than
constructing operating-system paths. Each import reloads the default when no
explicit import or process override is present. Local flips remain adapter state.
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

The M1 session keeps the parsed starting position, move history, selected node,
and in-memory trial variations. Loads are transactional and every position
change advances a revision that invalidates stale analysis. FEN and PGN imports
are strict: invalid, incomplete, unparseable, or silently truncated content is
rejected with an actionable error, and M1 never repairs input. Composed positions
use ordinary standard-chess move generation and terminal detection; excess
material is accepted without requiring historical reachability. Engine analysis
is explicitly unsupported above 32 occupied squares, while navigation and static
inspection remain available.

A standalone FEN appears as one root-only game. Every successful load, game/node
selection, navigation, or trial move enqueues analysis. An explicit `analyze`
retries or restarts analysis, and `compare` starts a request without moving the
session cursor. Backward `goto` walks ancestors; forward `goto` and `end` follow
child 0 from the current selected node.

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

The implemented `StockfishAdapter` owns its child for preparation, search,
cancellation, and shutdown. `prepare()` completes startup/configuration before
the application starts its outer search deadline. Typed reports distinguish
completed, canceled, failed, and unsupported analysis; scores and bound direction
use White's perspective. Every PV is checked against legal history and any
root-move restriction. Failed or canceled work settles before reuse; stop/quit
grace exhaustion terminates only the owned child. Request sequencing, stale-view
filtering, and the outer five-second envelope belong to the application controller.

The Python application owns a nonblocking, bounded, cancelable analysis queue.
Initially it manages one persistent Stockfish child process and streams partial
results to the interface. Foreground work takes priority, and a newer request may
cancel obsolete work. The interface never waits synchronously for engine search.

M1 permits one running request and one pending replacement. Results include the
request and position revision, so late results cannot update a newer position.
Engine states are idle, running, completed, canceled, failed, or unsupported.
Failure leaves static inspection usable, and a later explicit request retries
startup without an automatic restart loop.

Cancellation is scoped to the request task that owns it. A concurrent replacement
cannot be stamped canceled by an older cancel operation, and cancel completion
means the owned engine operation has settled before replacement proceeds. Close
is absorbing and idempotent: once it begins, no new request is accepted, all
callers share its completion. Shutdown asks the owned child to quit or terminates
it, then waits a bounded time for its return code; final acceptance confirmed no
Stockfish child remained.

The five-second startup timeout is one outer deadline covering process opening
and configuration together. Transport ownership transfers to the adapter as soon
as opening returns, so later configuration failure or timeout terminates and
performs a bounded return-code wait for that exact child.

Each published engine-evidence snapshot keeps raw score, PV, bound flags, depth,
nodes, and elapsed time as one atomic tuple; a metadata-only update never
relabels older scored evidence. Survey and focused-probe evidence is immutable
and request/revision scoped, and distinct legal branches preserve parallel UCI
and SAN lines.

The session assembles the shared snapshot and rejects analysis from a different
position revision before any interface receives it. It also owns analysis
submission and legal comparison-move resolution, so a later GUI does not repeat
request sequencing or stale-result policy. CLI cancellation settles before a
later position request can be submitted.

The interface-neutral serialization adapter renders the shared application view
as one `schema_version: 1` JSON snapshot; the CLI delegates to it rather than
owning the wire shape. Squares use algebraic coordinates, moves carry
UCI and SAN, and scores use tagged centipawn or mate values with explicit
perspective. Progress belongs on stderr and command results on stdout. A later
GUI consumes the same semantic references to draw arrows and highlights.
The editable JSON explanation text remains under `content`; its validation and
formatting adapter lives under `interfaces` and is constructed with the engine
and controller in `composition.py`.

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
