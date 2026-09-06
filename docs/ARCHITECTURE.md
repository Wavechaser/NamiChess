# NamiChess Architecture

**Status:** M2 interface and analysis contracts · **Scope:** durable boundaries and data flow

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

The implemented local exchange evaluator accepts one legal capture and searches
capture and recapture decisions on that target square with a scratch board.
Every branch uses legal moves, so moving blockers recompute slider x-rays and
king safety, pins, en passant, and capture-promotions retain ordinary chess
semantics. Each side may decline another target-square capture only when it has
a legal move outside the exchange; checking branches that also require
non-target evasions are unsupported. Terminal outcomes are also outside this
material-only model.

Exchange work is asynchronous and bounded by an injected monotonic deadline and
at most 4,096 expanded positions, yielding after every 32 positions. Typed
evidence distinguishes `completed`, `unsupported`, and `incomplete`, records a
replayable optimal UCI line, perspective, node count, and reached limit, and
uses pawn/knight/bishop/rook/queen values 1/3/3/5/9 including promotion gain.
Unsupported and incomplete results have no material result. A negative completed
result remains evidence; the evaluator has no candidate-selection call site and
cannot discard an engine candidate.

The bounded local explorer runs inside the existing application analysis job.
It orders actual-side roots as checks, captures or promotions, new direct
attacks, then UCI. A move probe explores its legal root; a piece probe explores
all legal exits of that actual-side piece within the local budget. The
application rejects illegal moves, absent pieces, opponent pieces, and stale
supplied session views before changing controller state.

Local search stops at four plies, 10,000 aggregate expanded positions, or its
monotonic deadline. Nested exchange evaluation consumes the same node allowance
through a narrow cooperative callback, so cancellation and the every-32-node
yield interval cannot reset inside SEE. Ordinary analysis retains its
five-second engine allowance and receives a separate 250 ms local allowance.
Focused work has one fifteen-second aggregate allowance after engine preparation
and caps its local portion at one second.

`LocalExploration` records resolved limits, reached limit, omitted legal roots,
and per-root reply evidence. Each root reports total and examined immediate
replies, first and omitted replies, replayable witnessed lines, branch scope,
termination reason, and optional root or reply exchange evidence. Complete
immediate-reply counts establish only that those replies were visited. A deeper
line is a selective example and never proves a forced continuation. Terminal
mate is recorded as witnessed mate rather than a general refutation.

The analysis package consumes this evidence into immutable local assessments.
Move safety distinguishes immediate replay-verified opponent mate, deeper
witnessed mate, incomplete work, and complete immediate-reply coverage where no
refutation was found. Trapping recomputes the actual-side piece's legal exits
and reports mate-refuted, unresolved, and unrefuted exits. Zero legal exits is a
separate result and never means the piece is won. Coverage names its unit as
opponent replies, legal exits, or root moves and keeps total, examined,
refuted, and unresolved counts consistent.

Material exposure is separate from mate refutation. When an immediate reply
captures the moved piece, the consumer combines root capture or promotion gain
with completed target-square exchange evidence. A negative result is only a
checked local material consequence; it does not establish unsoundness or
trapping, reject a sacrifice, or measure positional or mating compensation.
An overload candidate requires one actual-side defender of at least two
attacked friendly pieces. A witnessed conflict must show that the defender
captures one duty's attacker, loses geometric defence of a distinct duty, and
allows the original second attacker to take that piece without a legal target-square
recapture. It is not a universal overload proof.

Assessment evidence is accepted only when its position, root, immediate reply,
move-delta sequence, completed exchange line, termination, and coverage agree.
An unresolved limit line cannot become affirmative mate evidence. Shared
snapshots carry the resulting assessments, and CLI rendering consumes them
without rerunning search.

`AnalysisResult` carries the immutable `ProbeSubject`, resolved `LocalLimits`,
and optional `LocalExploration` beside engine candidates. The shared
`analysis.continuations` helper constructs identity-preserving contexts for
each witnessed ply; local evidence and engine PV evidence therefore recompute
the same structural `MoveDelta` contract without asking `Session.view()` to
search. The controller keeps one running and one pending request, and revision,
replacement, cancellation, and close rules apply to engine and local work
together.

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
retain strict structure and legality: invalid, unparseable, or silently truncated
content is rejected with an actionable error. A shared domain move resolver
accepts uniquely legal case-insensitive SAN shorthand with omitted effects and
returns the canonical legal move; imports and typed commands use the same rule.
This normalization never repairs broken PGN structure or FEN state. Composed positions
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

Submission rejects a supplied snapshot whose revision or position context no
longer matches the selected node, before resolving comparison moves or changing
controller state. Interfaces cannot restart obsolete analysis by returning a
previously displayed snapshot.

The interface-neutral serialization adapter renders the shared application view
as one `schema_version: 4` JSON snapshot; the CLI delegates to it rather than
owning the wire shape. Squares use algebraic coordinates, moves carry
UCI and SAN, and scores use tagged centipawn or mate values with explicit
perspective. Progress belongs on stderr and command results on stdout. A later
GUI consumes the same semantic references to draw arrows and highlights.
Schema version 4 retains the prior fields and adds explicit check roles to move
deltas and continuation consequences: `checked_king`, `checked_king_square`,
`checkers`, and `checker_squares`. Check squares refer to the resulting position.
`line.check` explanation pieces now identify actual checkers; the mover remains
separate in the referenced continuation consequence. Generic involved-piece
collections must never be interpreted as a substitute for these explicit roles.
Schema version 2 adds identity-bearing piece contacts, geometrically undefended
pieces, and latent slider rays to position facts and their added/removed forms to
move deltas. These remain geometric observations rather than tactical ownership
or unconditional safety claims.
It also carries immediate parent/child navigation references and typed local
assessments. Candidate preview validates the candidate/PV root and reconstructs
the requested board and facts without changing the cursor or starting analysis.
Schema version 3 adds a bounded `move_account` beside each retained raw previous-
move delta. Its typed consequences group connected structural changes, carry
position-scoped squares and piece identities, and cite exact raw delta fields.
Selection order and `omitted_count` are deterministic. Opened and blocked lines
require a matching occupied-piece contact; lost defense requires a surviving
piece to become geometrically undefended. These are geometric observations, not
claims of legal access, tactical safety, intent, or engine-score causality.
Opened-line grouping compares intervening occupancy before and after the move.
Every cleared blocker must be accounted for by the move or capture, so en
passant can connect an attack opened by clearing both pawns. The supporting
references retain the original latent ray, new contact, and additional cleared
blocker effects; a blocker remaining on the line prevents that explanation.
The application derives a separate, bounded `attention` selection from the
already-computed current facts and optional move account. It prioritizes current
check, attacked pieces that lost geometric defense, other attacked and
geometrically undefended pieces, newly pinned pieces, supported line changes,
and existing pins. Each item uses the current piece square and cites its exact
position facts and move-delta sources. The shared selection is capped at three
with an explicit `omitted_count`; it starts no search and makes no claim that a
geometrically attacked piece can legally or safely be won.
Selected analysis candidates also carry request-scoped root structure computed
once before probe partials are assembled. Each root retains its full static move
delta and move account plus at most three defense changes. A defense change
compares exact defender piece-identity sets, not counts, for pieces surviving in
every selected root. It appears only when alternatives differ; a candidate whose
state matches the baseline is retained when another root changes that state.
Current after-root squares and references to contrasting root position IDs keep
the comparison resolvable for non-CLI consumers. These structural differences
do not explain or justify an engine score.
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
