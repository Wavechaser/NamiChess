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
| `load <path>` | Load one `.fen` position or one or more `.pgn` games. The path is the complete remainder of the command. One matching pair of single or double quotes is removed. |
| `fen <six-field FEN>` | Load one root-only composed or ordinary standard-chess position. |
| `games` | List loaded games and mark the selected game. |
| `game <n>` | Select the one-based game and its final mainline node. |
| `board` | Show the ASCII board, coordinates, turn, terminal/draw state, latest current-revision analysis state, and the prior move change when available. |
| `start` | Select the imported root position. |
| `end` | Follow child zero from the selected node to the end of that line. |
| `next` | Select child zero from the current node. |
| `back` | Select the parent node. |
| `goto <ply>` | Walk ancestors for a lower ply or child zero for a higher ply. Ply zero is the imported root. |
| `variations` | List the current node's child moves as SAN. |
| `variation <n>` | Select a one-based child variation. |
| `move <SAN-or-UCI>` | Add or reuse an in-memory legal trial child and select it. The imported file is unchanged. |
| `inspect <square>` | Show the occupant, geometric attackers from both colors, legal access for the actual side to move, and relevant absolute pins. |
| `analyze` | Restart bounded analysis of the selected position. This also retries engine startup after failure. |
| `compare <move> <move>` | Analyze two distinct legal SAN or UCI moves without changing the selected node. |
| `details <candidate-number>` | Show the selected result's evidence, survey/probe scores, numbered SAN continuations, coordinates, captures, recaptures, promotions, material changes, and checks. |
| `json` | Emit one complete versioned snapshot of the shared session and current-revision analysis. |
| `cancel` | Await cancellation of active analysis before accepting a later position request. |
| `help` | Show the compact command list. |
| `quit` or `exit` | Cancel active work, close the owned engine, and exit. |

Candidate numbers are stable within one result and address every candidate,
including provisional or unranked candidates. A candidate's number is separate
from its certified rank. Scores use White's perspective and state that positive
favors White and negative favors Black. Survey and focused-probe evidence remain
separate, including their scores and bounds.

## Input and file rules

Commands are limited to exactly 16,384 characters. A `load` path may contain spaces and Windows
backslashes; backslashes are not escapes and the value is never executed as a
shell command. Only `.pgn` and `.fen` files are accepted, up to 10 MiB, as UTF-8
with an optional BOM. Imports are read-only and a failed load leaves the current
session unchanged.

FEN input requires all six fields, canonical decimal move counters, coherent
castling and en-passant state, one king per color, and a valid standard-chess
position under the documented composed-position rules. PGN input requires
well-formed tags and variations, legal canonical SAN, and one terminating result
marker per game. Import errors identify what must be corrected before reloading.

The session accepts at most 1,000 games, 100,000 total move nodes, and variation
depth 64. Positions above 32 occupied squares remain navigable and inspectable;
engine analysis reports unsupported and does not launch Stockfish for them.

## Text results and recovery

A completed result shows its state and coverage, at most three priority facts,
and a candidate table. Priority favors current check, direct mate, and a
candidate allowing an opponent mate before ordinary line facts. Candidate facts
are prefixed with the candidate's root SAN so facts from different continuations
cannot be confused. Each table row contains one concise priority explanation;
`details` contains the complete evidence.

`failed` means the engine request failed while the static session remains usable.
If the configured file was temporarily unavailable, restore it at the same path
and run `analyze` to retry. To select a different path, exit and restart with the
correct `--engine` argument. `unsupported` explains a
position boundary such as more than 32 occupied squares. `canceled` is distinct
from failure. Ctrl+C cancels active analysis; with no active analysis it clears
the current input. `quit` does not wait for a full search.

## JSON snapshot

`json` emits one object with `schema_version: 1`, `session`, and `analysis`.
The snapshot is assembled by the application and includes analysis only when its
position revision matches the selected session revision. `analysis` is `null`
when no current result exists.

This is a snapshot command inside the ordinary CLI stream, not a JSON-only
process mode. Stdout may also contain earlier command output and asynchronously
completed text results. A `json` command issued while analysis is running shows
that running state immediately; redirected EOF subsequently waits and prints the
latest completed result as text.

The session object contains position context, board rows, piece placements,
geometric attacks, actual-side legal moves, absolute pins, check facts, and an
optional previous-move delta. Moves carry UCI and SAN. Piece, square, position,
candidate, explanation, evidence, request, and revision identities remain
structured; a consumer does not parse prose to draw arrows or highlights.

The analysis object contains state, engine identity, coverage, candidates,
explanations, and evidence. Scores are tagged with centipawn/mate and bound data;
JSON preserves `null` separately from numeric zero. Evidence includes UCI and SAN
lines, legal alternative branches, source/target/capture squares, and engine
depth, nodes, and elapsed seconds when present. `json` is a point-in-time view, not a separate network
protocol or subscription stream.

This abridged illustrative snapshot shows the stable top-level shape. Omitted
nested fields remain named typed values rather than encoded prose:

```json
{
  "schema_version": 1,
  "session": {
    "revision": 3,
    "position": {"current_fen": "...", "moves": ["e2e4"]},
    "facts": {"pieces": [], "attacks": [], "legal_moves": [], "pins": []},
    "previous_move": {"uci": "e2e4", "san": "e4"}
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

`AnalysisController.submit()` is nonblocking. It retains the latest request and
at most one pending replacement. `wait()`, `cancel()`, and `close()` are awaited;
late or superseded results cannot populate a newer shared view. Interfaces read
immutable `SessionView`, `PositionFacts`, `MoveDelta`, `AnalysisResult`,
`Explanation`, and `Evidence` values. `composition.py` alone constructs the
Stockfish adapter, controller, session, and explanation catalog.
