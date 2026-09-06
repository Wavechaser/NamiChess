# NamiChess Command Line

The NamiChess CLI is a persistent local position-analysis session. It loads a
PGN or FEN, keeps the selected game and variation in memory, and presents the
same immutable application facts and engine evidence available to another
interface. The CLI parses commands and formats results; chess rules, candidate
selection, request sequencing, and stale-result filtering remain in the domain,
analysis, and application layers.

## Start and engine selection

Start with the development-default Stockfish location:

```powershell
namichess
```

Choose another local Stockfish executable explicitly:

```powershell
namichess --engine 'C:\Chess\stockfish.exe'
```

Choose an orientation for imports in this process; a command-level import choice
still takes precedence:

```powershell
namichess --orientation turn
```

NamiChess starts Stockfish lazily when a searchable position is loaded. It does
not download an engine or use a remote service. The fixed M1 budget is five
seconds per request: at most one second surveys five roots, then focused probes
cover that union plus up to two comparison moves, capped at seven. Startup has a
five-second timeout; stop and quit have a two-second grace. Stockfish uses one
thread and 64 MiB hash.

Invalid startup arguments use argparse's usage error and exit code 2. Once the
session starts, recoverable command and import errors are reported to stderr;
engine failure is a structured analysis result on stdout. The process continues
and ultimately returns 0 after ordinary EOF or `quit`.

## Typical session

Use `load C:\Games\sample game.pgn` when working from an existing file. The
following self-contained example starts from the standard initial FEN:

```text
fen rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1
inspect e4
analyze
compare e4 d4
details 1
move e4
back
json
quit
```

Wait for the completed comparison result to appear before entering `details 1`.

Loading, selecting, navigating, or playing a trial move submits bounded analysis
for the new position. Input remains usable while it runs. Progress is written to
stderr at most four times per second; command output and completed results go to
stdout. With redirected input, prompts are suppressed and the CLI waits for the
latest request at end of input.

The native CLI configures stdin, stdout, and stderr as UTF-8, including redirected
streams. Files also use the UTF-8 import rules below. Redirect consumers should
decode output as UTF-8.

## Command reference

| Command | Result |
|---|---|
| `load [--orientation <white\|black\|turn>] <path>` | Load one `.fen` position or one or more `.pgn` games. The path is the complete remainder of the command. One matching pair of single or double quotes is removed. |
| `fen [--orientation <white\|black\|turn>] <six-field FEN>` | Load one root-only composed or ordinary standard-chess position. |
| `games` | List loaded games and mark the selected game. |
| `game <n>` | Select the one-based game and its final mainline node. |
| `board` | Show the ASCII board, coordinates, turn, terminal/draw state, bounded current attention, latest current-revision analysis state, and a compact connected account of the prior move when available. |
| `flip` | Reverse this CLI's board display without changing the position, analysis request, revision, or saved default. |
| `orientation` | Show the current local orientation and the saved default. |
| `orientation <white\|black>` | Set this CLI's current orientation without saving it. |
| `orientation default <white\|black\|turn>` | Persist the orientation used by later imports that lack a command or process override. |
| `start` | Select the imported root position. |
| `end` | Follow child zero from the selected node to the end of that line. |
| `next` | Select child zero from the current node. |
| `back` | Select the parent node. |
| `goto <ply>` | Walk ancestors for a lower ply or child zero for a higher ply. Ply zero is the imported root. |
| `variations` | List the current node's child moves as SAN. |
| `variation <n>` | Select a one-based child variation. |
| `move <SAN-or-UCI>` | Add or reuse an in-memory legal trial child and select it. The imported file is unchanged. |
| `inspect <square>` | Show the occupant, geometric contacts and rays, legal access for the actual side to move, absolute pins, and available local assessments involving that piece. |
| `changes` | Show the connected account and complete identity-bearing raw relationship changes from the previous move. |
| `analyze` | Restart bounded analysis of the selected position. This also retries engine startup after failure. |
| `probe move <SAN-or-UCI>` | Resolve a legal move and start focused analysis without moving the cursor. |
| `probe piece <square>` | Resolve the side-to-move piece and analyze its legal exits without moving the cursor. |
| `line <candidate-number> <ply>` | Display candidate ply zero or a later ply as a read-only board with its bounded attention selection in the current orientation. |
| `compare <move> <move>` | Analyze two distinct legal SAN or UCI moves without changing the selected node. |
| `details <candidate-number>` | Show the candidate's immediate root structure followed by complete evidence, survey/probe scores, numbered SAN continuations, coordinates, captures, recaptures, promotions, material changes, and checks. |
| `json` | Emit one complete versioned snapshot of the shared session and current-revision analysis. |
| `cancel` | Await cancellation of active analysis before accepting a later position request. |
| `help` | Show the compact command list. |
| `quit` or `exit` | Cancel active work, close the owned engine, and exit. |

Candidate numbers are stable within one result and address every candidate,
including provisional or unranked candidates. A candidate's number is separate
from its certified rank. Scores use White's perspective and state that positive
favors White and negative favors Black. Survey and focused-probe evidence remain
separate, including their scores and bounds.

Line material deltas also use a fixed White perspective: a White capture gives
a positive delta, while the corresponding Black capture gives a negative delta.
The compact text names the captured piece and labels this perspective; White-only
field names do not imply White-only analysis. Capture-promotion deltas include
both captured material and the promotion gain. Local exchange results retain
their separately declared perspective. Board flipping changes neither value.

The analysis package also provides bounded target-square exchange evaluation for
integrated local exploration. It reports `completed`, `unsupported`, or
`incomplete`; only a completed result has a material value. That value uses the
requested White or Black perspective and 1/3/3/5/9 piece values, includes
capture-promotion gain, and is accompanied by a legally replayable UCI line,
node count, and limit metadata. The evaluator explores at most 4,096 positions
under its caller's monotonic deadline and yields every 32 positions. When local
exploration calls it, SEE consumes the enclosing 10,000-node allowance and
cooperative yield schedule instead of resetting either limit. It does not rank
or remove candidates.

The interface-neutral application API accepts a typed focused move or piece
`ProbeSubject`. `Session.request_probe` validates the selected revision and
position, legal UCI move, or actual-side piece identity before submitting work.
Its `AnalysisResult` exposes the subject, immutable resolved local limits, and
typed local exploration evidence. Ordinary requests add at most 250 ms of local
work to the existing five-second engine allowance. Focused requests use at most
fifteen seconds after engine preparation, with local work capped at one second;
both modes stop local work at depth four or 10,000 aggregate nodes.

Per-root local coverage distinguishes visited immediate replies from omitted
replies and records why each replayable branch stopped. A complete reply count
does not turn a selective deeper line into exhaustive defence or a forced
claim. Focused piece probes cover every legal exit locally within the budget,
while restricted engine verification remains capped at seven roots. `probe move`
and `probe piece` expose the same requests through the CLI; they leave the
selected game position unchanged.

The interface-neutral assessment consumer produces immutable results that
identify position and subject, reference
local line or exchange evidence, and declare coverage in opponent replies,
legal exits, or root moves. Safety distinguishes immediate mate failure, deeper
witnessed failure, incomplete work, and no refutation found. Trapping lists
legal, refuted, unresolved, and locally material-exposed exits. Material
exposure accounts for root capture and promotion gain but does not state that a
move is unsound or a piece is won. Overload output is limited to witnessed
conflicting duties. The analysis snapshot exposes `move_safety`, `trapping`, and
`overload`; concise output, `inspect`, and candidate `details` render their
qualified conclusions and coverage.

Import orientation resolves in this order: command-level `--orientation`, the
process-level option, then the saved default. `turn` resolves once from the
newly loaded root; navigating a game does not turn the display again. The saved
setting is reloaded on each unoverridden import. If it is malformed, NamiChess
uses White at the bottom, reports the fallback, and leaves the settings file
untouched.

## Input and file rules

Commands are limited to exactly 16,384 characters. A `load` path may contain spaces and Windows
backslashes; backslashes are not escapes and the value is never executed as a
shell command. Only `.pgn` and `.fen` files are accepted, up to 10 MiB, as UTF-8
with an optional BOM. Imports are read-only and a failed load leaves the current
session unchanged.

FEN input requires all six fields, canonical decimal move counters, coherent
castling and en-passant state, one king per color, and a valid standard-chess
position under the documented composed-position rules. PGN input requires
well-formed tags and variations, legal moves, and one terminating result marker
per game. Import errors identify what must be corrected before reloading.

PGN movetext and typed `move`, `compare`, and `probe move` share a shorthand
contract. Canonical SAN is accepted directly; otherwise case-insensitive SAN may
omit capture (`x`) and check/mate (`+`, `#`) markers when it identifies exactly
one legal move. For example, `qg7` can resolve to `Qxg7#`. Supplied effect markers
must be correct. Required source disambiguation and the promotion piece cannot
be guessed. Ambiguous shorthand is rejected; use canonical SAN or, in typed
commands, UCI. Exact canonical SAN takes precedence to preserve pawn/bishop
notation that would collide if case were discarded.

Accepted shorthand is represented as canonical SAN in the in-memory game and
analysis. This infers move effects from the board; it does not repair malformed
PGN structure, illegal moves, or FEN fields, and never rewrites the imported file.

The session accepts at most 1,000 games, 100,000 total move nodes, and variation
depth 64. Positions above 32 occupied squares remain navigable and inspectable;
engine analysis reports unsupported and does not launch Stockfish for them.

## Text results and recovery

A running request has a concise acknowledgment without recurring elapsed-time
lines. Completion reports recorded root probes and their known depth or depth
range; survey lines and unfinished roots are excluded. Coverage still reports
interruption. Compact numeric scores and material deltas omit repeated
perspective labels; their documented White-positive convention is unchanged.

Board and candidate-line previews lead the previous-move account with SAN and
always retain direct capture, promotion, castling, and check effects. They then
show observed check and attack mechanisms supplied by the shared application
view before other connected consequences, such as a newly unguarded piece or an
opened slider line. Check text names the actual checker or checkers and identifies
direct and discovered roles when the preceding move establishes them. Structural
forks include every geometrically attacked target, including a checked king, but
do not claim that a target is capturable or won. When the shared
account omits additional consequences, compact output reports the count and
points to `changes` for full raw details; `changes` retains the complete raw
relationship categories. These statements describe recorded move effects and
geometric relationships without asserting tactical wins or intent.

`Attention:` presents the bounded selection already attached to the current
session or candidate-line view. It can identify the checked king, attacked and
geometrically undefended pieces, lost defense under attack, pins, and opened or
blocked slider lines. It does not run another query or claim that a piece is
won, a move is safe, or a geometric defender can legally respond. When an
attention item, mechanism, and connected move account cite the same complete set
of raw move facts, the compact board shows that relationship once. Sharing only
one source does not suppress a distinct fact, such as a pin that also establishes
an attack. Direct move effects remain in the SAN header, and `changes` remains
the source for full raw details.

A completed result shows its state and coverage, current-position check or
legal-mate facts, and then the candidate table. Bounded local assessments follow
the table. Without a selected checking-threat conclusion, candidate rows lead
with the shared immediate root structure. When selected
roots differ in a piece's geometric defenders, the row identifies added,
removed, or replaced defender identities; it says defense is unchanged only
when the shared comparison records equality with another differing root. Check,
attack, and fork mechanisms precede one or two such contrasts and remaining
bounded root-account effects. Compact rows show at most three structural clauses
plus one combined direct-effect clause. Check mechanisms absorb the generic check
effect so the row does not repeat it. Fork and attack clauses remain geometric
even when their actor is pinned.
Root-local omission counts stay explicit. A candidate without shared root
structure says that structure is unavailable. Ordinary captures and checks later in a
principal variation remain in `details` instead of displacing immediate
structure in the compact table. A direct candidate mate-in-one warning remains
in that candidate's row and takes priority over repeated engine mate prose. The
engine score column already displays a mate score; the qualified reported-mate
sentence and survey/probe disagreement prose remain in `details` with the
complete evidence.

When bounded local evidence examines a checking move's replies, the candidate
row can state whether an attacked target has an immediate legal capture after
every reply, after only some replies, or with incomplete coverage. The row uses
the application's ordered selection of at most two targets and response groups;
it does not regroup responses or recalculate chess facts. The compact row shows
the first selected target so its supporting mechanisms remain visible. One
outcome clause and its supporting check or attack mechanisms share the existing three-clause
structural budget. An opponent mate-in-one warning remains first. Extra targets
or branch groups point to `details` instead of expanding the table.

`details` places `Checking-threat evidence` before engine continuation evidence.
It lists every retained target and legal response with SAN and UCI, the response
roles actually recorded by the verifier, the target's response-position square,
and any legal immediate capture witness. When the target-square exchange model
ran, its status, model, node coverage, limit, and material result are supporting
detail. Capture availability does not mean that the capture is safe or profitable,
that the target is won, or that the checking move forces a material gain.

`failed` means the engine request failed while the static session remains usable.
If the configured file was temporarily unavailable, restore it at the same path
and run `analyze` to retry. To select a different path, exit and restart with the
correct `--engine` argument. `unsupported` explains a
position boundary such as more than 32 occupied squares. `canceled` is distinct
from failure. Ctrl+C cancels active analysis; with no active analysis it clears
the current input. `quit` does not wait for a full search.

## JSON snapshot

`json` emits one object with `schema_version: 4`, `session`, and `analysis`.
The CLI delegates this shape to the shared interface serialization adapter so a
future GUI consumer does not need to import CLI rendering code. Schema version 2
preserves every version-1 field and encoding while adding structural facts,
local evidence and assessments, and immediate navigation references.
Schema version 4 retains previous fields and adds `checked_king`,
`checked_king_square`, `checkers`, and `checker_squares` to move deltas and
continuation consequences. Checker and king squares belong to the resulting
position. A `line.check` explanation now references the actual checking pieces;
its continuation consequence retains the mover separately. Consumers should
use those explicit roles for highlights, including discovered and double check.
Session, preview, and candidate-root records also carry `mechanisms`, describing
check roles, new attacks, and geometric forks. Candidate `threat_selection`
references retained `analysis.local.roots[].threats`; each local root retains
`root_delta` for the effect's raw fact sources. A threat reference carries the
original position, request-scoped root position, root UCI, and threat index.
Selected response groups carry indices into the raw responses. Their target
coordinate is a grouping key; use each raw response's scoped square references
for highlights. Selection omissions do not remove raw evidence.
Schema version 3 preserves those fields and adds an optional bounded
`move_account` beside `previous_move`. Each consequence carries typed piece and
position-scoped square references plus `supporting_facts` that resolve to the
retained raw delta. `omitted_count` reports consequences outside the shared
selection. Consequences describe geometric or directly recorded move effects;
they do not assert legal access, tactical safety, intent, or score causality.
Candidate records may also contain `root_structure`, which holds the candidate
root delta and bounded move account plus explicit defender comparisons against
the other selected roots. Defender comparisons retain baseline and resulting
piece identities, the current subject square, and the roots whose resulting
defense differs. Changed defense identities carry source references to their
exact added or removed defense contacts; an explicitly unchanged comparison has
no changed-contact source. Their root-local `omitted_count` does not imply that
an absent piece or relationship was unchanged.
The snapshot is assembled by the application and includes analysis only when its
position revision matches the selected session revision. `analysis` is `null`
when no current result exists.

This is a snapshot command inside the ordinary CLI stream, not a JSON-only
process mode. Stdout may also contain earlier command output and asynchronously
completed text results. A `json` command issued while analysis is running shows
that running state immediately; redirected EOF subsequently waits and prints the
latest completed result as text.

The session object contains position context, board rows, piece placements,
geometric attacks, identity-bearing attack/defence contacts, geometrically
undefended pieces, latent slider rays, actual-side legal moves, absolute pins,
check facts, an optional previous-move delta, `parent_position_id`, and
`child_position_ids` for immediate variations. It does not serialize the whole
game tree. Move deltas contain before/after piece placements and added and
removed structural facts. Moves carry UCI and SAN. Piece, square, position,
candidate, explanation, evidence, request, and revision identities remain
structured; a consumer does not parse prose to draw arrows or highlights.

The analysis object contains state, engine identity, coverage, candidates,
explanations, evidence, the focused subject when present, local exploration,
resolved limits, typed local assessments, and `assessment_pieces` containing
current placements for the assessed trapping/overload subjects. These placements
let standalone result rendering name the piece without replaying chess rules.
Scores are tagged with centipawn/mate and bound data;
JSON preserves `null` separately from numeric zero. Evidence includes UCI and SAN
lines, legal alternative branches, source/target/capture squares, and engine
depth, nodes, and elapsed seconds when present. `json` is a point-in-time view, not a separate network
protocol or subscription stream.

This abridged illustrative snapshot shows the stable top-level shape. Omitted
nested fields remain named typed values rather than encoded prose:

```json
{
  "schema_version": 4,
  "session": {
    "revision": 3,
    "position": {"current_fen": "...", "moves": ["e2e4"]},
    "facts": {"pieces": [], "attacks": [], "contacts": [], "geometrically_undefended": [], "latent_rays": [], "legal_moves": [], "pins": []},
    "previous_move": {"uci": "e2e4", "san": "e4"},
    "move_account": {"uci": "e2e4", "consequences": [], "omitted_count": 0}
  },
  "analysis": {
    "request_id": 4,
    "revision": 3,
    "state": "completed",
    "coverage": {"surveyed": 5, "probed": 5, "requested": 5, "total_legal": 20},
    "candidates": [],
    "explanations": [],
    "evidence": []
  }
}
```

## Shared application interface

`Session` owns loading, selection, navigation, trial moves, static facts, and
revision-safe view assembly. `Session.request_analysis(controller, compare=...)`
submits the selected immutable `PositionContext` and returns the shared
`SessionView`; `Session.analysis_view(controller)` attaches only a
matching-revision `AnalysisResult`. `Session.resolve_moves()`
validates SAN/UCI comparison moves without moving the cursor.
`Session.resolve_probe()` resolves a CLI-style move or square to a typed subject;
`Session.request_probe()` applies the same revision-safe submission boundary.
Supplied submission views must match the selected revision and position context;
stale views are rejected before comparison resolution or controller mutation.

`preview_candidate_line(view, candidate_number, ply)` reconstructs an immutable
candidate preview from the current result. Ply zero is the selected source
position; later plies carry request-scoped continuation positions and exact
history, facts, placements, and move changes. It validates the candidate/PV root
and revision and never changes the session cursor, adds a variation, or starts
analysis. Preview and session coordinates stay canonical; each interface renders
the board using its own orientation. Immediate preview parent/child references
describe that candidate line rather than eagerly expanding the game tree.

`AnalysisController.submit()` is nonblocking. It retains the latest request and
at most one pending replacement. `wait()`, `cancel()`, and `close()` are awaited;
late or superseded results cannot populate a newer shared view. Interfaces read
immutable `SessionView`, `PositionFacts`, `MoveDelta`, `AnalysisResult`,
`Explanation`, and `Evidence` values. `composition.py` alone constructs the
Stockfish adapter, controller, session, and explanation catalog.

`cancel()` targets the request captured when cancellation begins; it neither
cancels nor waits for a replacement submitted concurrently. `close()` is
idempotent and shared across callers. As soon as close begins, a new `submit()`
is rejected with `RuntimeError`, and every close caller awaits the same cleanup.
