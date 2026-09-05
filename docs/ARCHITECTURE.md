# NamiChess Architecture

**Status:** pre-implementation · **Scope:** durable boundaries and data flow

## 1. Architectural intent

NamiChess is a local chess-analysis and training tool for players around
1200–1400 Elo. Its backend explains board relationships, threats, plans, and
practical continuations; it is not an engine-ranking wrapper.

The backend is platform- and interface-agnostic. A Windows 11 GUI, CLI, or
future local presentation surface is an adapter around the same application
use cases. No interface owns chess policy, engine protocol, or persistence
format decisions.

The first implementation is intentionally small. It does not introduce a
database, remote service, plugin system, distributed workers, or a generalized
message bus.

## 2. Dependency direction

```text
interfaces  →  application  →  analysis  →  domain
```

The four primary layers have one-way dependencies:

### Domain

`src/namichess/domain/` contains typed chess facts and rules. It may use
`python-chess` for board legality and notation, but it never imports Stockfish,
file storage, GUI, web, or operating-system adapters.

The core model keeps geometric control, legal access, and tactical ownership
separate. Piece-square relationships are represented through facts such as
`SquareInterest`, `PieceProfile`, `MoveDelta`, and their deltas. Counts are
never treated as proof of safety; identities and legal context remain available.

### Analysis

`src/namichess/analysis/` derives static facts, causal explanations, tactical
assessments, and practical candidate comparisons. Static analysis proposes
facts and hypotheses; search verifies or rejects tactical claims. Engine values
belong to resulting positions and are not attributed to a square or piece
without verified causal evidence.

Stockfish is hidden behind a narrow injected adapter. No domain object depends
on UCI, a process, or an executable path. Analysis work is progressive and
bounded: begin with a broad shallow survey, deepen forcing or uncertain
branches, and stop or switch to plan mode when the decision budget is spent.
Background work is cancelable, and a newer foreground request may supersede
obsolete work.

### Application

`src/namichess/application/` owns use cases and is the only layer that composes
independent analysis, training, and persistence collaborators. It coordinates
review order, candidate selection, training events, and durable writes without
leaking adapter details into the domain.

### Interfaces

`src/namichess/interfaces/` contains the CLI, local presentation/API boundary,
and optional Windows shell. Interfaces translate user input to application
requests, own file-picker and launch behavior, and render progressive results.
They do not make chess decisions or construct engines directly.

## 3. Analysis data flow

```text
PGN/FEN or board input
        ↓
validated domain position
        ↓
static facts and MoveDelta
        ↓
candidate and threat assessment
        ↓
bounded Stockfish probes / verification
        ↓
adequate moves, evidence, and practical explanation
        ↓
progressive interface view + optional saved record
```

For a reviewed move, the application first establishes position status and the
last-move delta, then checks urgent forcing resources. It compares only
adequate candidates: tactically sound moves within configured engine-WDL loss
of the best available outcome, or best resistance when all moves are bad.
Engine-best and practical-best may therefore differ. Explanations are
contrastive and start at the earliest verified causal difference.

Static computation should expose affected squares and pieces, including opened
or closed rays, newly attacked or defended pieces, pins, overloads, safe
mobility, threats, and enabled breaks. SEE and latent-ray evidence may be
`unsupported`; it must not be silently guessed. Search verifies tactical
claims, while a line remains an example realization rather than an instruction
to memorize.

The interface receives a compact initial review (status, changed facts, urgent
resources, plan, and choice). Full maps, candidates, engine evidence, and
continuations are expandable. When future branching becomes too costly to
explain move by move, the application returns a durable plan with triggers,
routes, and preserved options.

## 4. Persistence and file boundaries

PGN and FEN remain the interchange formats for chess content. Small app-owned
records use versioned UTF-8 JSON with explicit typed readers and writers. A
record may reference original PGN/FEN, derived analysis evidence, training
responses, and user metadata, but those categories remain distinguishable.

SQLite is explicitly deferred. It becomes a candidate only after measured data
volume or query needs demonstrate that JSON files and straightforward indexes
are insufficient. No repository or schema abstraction should be added merely
to anticipate that possibility.

Imported game files are read-only inputs. Saving or exporting always targets a
distinct, user-confirmed destination; source and destination must not be
confused. User and development data stay outside the source tree, and
`.tools/` is reserved for ignored machine-local Stockfish binaries.

Persistence collaborators are injected at the application composition root.
The backend accepts explicit paths supplied by a native CLI or GUI file picker;
the runtime has no remote file or server access.

## 5. Composition and ownership

`src/namichess/composition.py` is the sole composition root. It wires the clock,
domain services, analysis components, Stockfish adapter, interfaces, and
JSON/PGN/FEN storage. Lower layers receive collaborators instead of constructing
infrastructure. Typed immutable facts should be preferred internally;
validation belongs at external and persistence boundaries.

The domain owns chess truth. Analysis owns evidence and verification. The
application owns sequencing and durable record assembly. Interfaces own
presentation state and platform behavior. Each fact has one semantic owner;
views and serialized copies cannot become competing authorities.

## 6. Verification boundaries

Tests mirror package boundaries under `tests/`, with reusable named FEN/PGN
fixtures. Domain facts are tested independently of engines and files. Analysis
tests cover perspective-sensitive metrics, unsupported SEE/engine cases, and
causal attribution. Application tests cover candidate adequacy, progressive
budgeting, cancellation, and record separation. Interface tests cover input
translation and safe save/export behavior.

The ordinary suite must run before a mergeable change. Architecture changes
must update this document when they alter layer dependencies, durable formats,
analysis ownership, or interface contracts.

## 7. Deferred direction

Later work may add richer personalization, trajectory analysis, indexing, or a
database if actual use justifies it. Such additions must preserve the same
dependency direction, local-only runtime, explicit file scope, verified
analysis evidence, and progressive user experience. They are not part of the
initial architecture.
