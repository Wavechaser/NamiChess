# M1 — Interactive CLI Position Analysis

**Status:** Complete
**Last updated:** 2026-09-06

This document owns M1's implementation sequence, acceptance gates, recorded
investigation evidence, and resumption state. Product and architectural rules
remain owned by their respective documents.

## Main objectives

M1 loads PGN or FEN, navigates positions in a persistent CLI session, explains
board relationships and move changes, and compares candidates with bounded
Stockfish evidence. Its application operations and structured views are shared
with a later GUI; only rendering and interaction belong to the CLI.

Included: standard chess rules over ordinary and composed layouts, unusual
material, multi-game PGN and variations, ASCII inspection, move deltas, a
persistent cancelable Stockfish process, ranked analyzed candidates, and narrow
threat evidence for checks, immediate mates, captures, legal replies, and
consequences in verified lines.

Deferred beyond M1: GUI, active recall and training, practical-best ranking,
comprehensive bilateral threats, strategic plans, SEE, saved analysis caches,
settings persistence, export, custom themes, Chess960, and other rule variants.
Syzygy and tablebase redistribution are excluded from the product. M1 never
labels a move adequate, equivalent, safe, uniquely correct, or easier for a
human from a capped engine survey. Mate distance is evidence, not an instruction
to memorize a line.

## Established decisions and evidence

### Composed positions

Use one validation and move-generation path for ordinary and unusual layouts.
Accept excess material and positions that need not be historically reachable.
Require exactly one king per color, valid turn data, coherent castling and
en-passant state, no back-rank pawns, and no check against the side that just
moved. Preserve all six FEN fields and do not silently repair invalid state.
Retain python-chess rejection of impossible-check configurations while relaxing
material-count validity. Starting checkmate and stalemate use the normal legal
move path and produce terminal results without candidates.

Stockfish 18 was probed locally with one thread, 16 MiB hash, and short bounded
searches. It returned legal continuations for the standard start, positions with
fifteen and twenty queens from both color perspectives, and nine pawns; it
correctly handled starting mate/stalemate and remained usable after canceling an
unusual-position search. Separately, python-chess parsed an unusual FEN-backed
PGN into a board that Stockfish analyzed. Preserve these fixtures:

```text
6rk/6pp/8/8/8/8/QQQQQQQQ/KQQQQQQQ w - - 0 1
6rk/6pp/8/8/8/QQQQQ3/QQQQQQQQ/KQQQQQQQ w - - 0 1
```

These observations do not prove reliable evaluation for every composition.
Stockfish 18's NNUE [feature definition](https://raw.githubusercontent.com/official-stockfish/Stockfish/sf_18/src/nnue/features/half_ka_v2_hm.h)
has capacity for 32 occupied squares, and its [feature construction](https://raw.githubusercontent.com/official-stockfish/Stockfish/sf_18/src/nnue/features/half_ka_v2_hm.cpp)
appends one entry per occupied square. Positions above that boundary remain
navigable and inspectable but return `unsupported` for engine analysis; never
pass them to the M1 adapter.

### Shared contracts

Follow the existing layers and add no general framework. Domain owns validation,
immutable position/move/piece references, and terminal rules. Analysis owns
static facts, deltas, the narrow engine adapter, and evidence. Application owns
session state, selection, scheduling, candidate orchestration, and shared views.
Interfaces own native file scope, command parsing, text rendering, and JSON.
Content owns stable explanation identifiers/templates. `composition.py` alone
constructs infrastructure.

Minimum frozen dataclasses/enums:

- `PositionContext`: root position, legal move history, selected-node identity,
  current FEN, and whether prior history is available.
- `SessionView`: games, selection, board, terminal/claimable-draw status, and
  current analysis state.
- `PositionFacts` and `MoveDelta`: identity-bearing pieces, attacks, legal moves,
  pins, and supported before/after changes.
- `AnalysisPolicy`: immutable search budget, candidate limit, and engine limits.
- `AnalysisResult`: request identity, position revision, coverage, candidates,
  explanations, evidence, and completion state.
- `Explanation`: stable ID, typed values, piece/square/move references, and
  evidence references.

Public views never expose mutable `chess.Board`, engine processes, or PGN nodes.
Piece identity starts at source-node placement and follows moves, promotion, and
castling. A square reference includes its position/node identity.

### Session and analysis lifecycle

Operations are load, select game/node, navigate, play a trial move, inspect,
analyze, compare, cancel, and close. Load is transactional. Trial moves create
in-memory child variations and reuse a matching child. Imported content remains
unchanged. Every position change increments a revision and supersedes obsolete
analysis. States are idle, running, completed, canceled, failed, and unsupported.

Allow one running engine job and at most one pending replacement; cancellation
finishes before the next search begins. Late results carry request/revision IDs
and cannot populate a newer view. Retain only current analysis and bounded
progress. Engine failure preserves navigation/static inspection; an explicit
later `analyze` retries startup without an automatic restart loop.

### CLI and shared presentation

Launch with `namichess` or `python -m namichess`. Use `prompt_toolkit` 3.x for
asynchronous input/output. ASCII and coordinates are always sufficient; chess
glyphs and color are optional. Results show status, at most three priority facts,
and a candidate table with rank, SAN, score, and concise explanation. Scores say
explicitly `+ favors White / − favors Black`. Details show numbered SAN lines,
coordinates, evidence type, and search coverage. Relationship sentences and
JSON derive from the same typed references that a GUI can later render as arrows
or highlights.

Commands:

| Command | Contract |
|---|---|
| `load <path>` | Read `.pgn` or `.fen`; select game 1's final mainline node |
| `fen <six-field FEN>` | Load a composed position as one root-only game |
| `games`, `game <n>` | List/select one-based games |
| `board` | Board, coordinates, side to move, and status |
| `start`, `end`, `next`, `back`, `goto <ply>` | Navigate relative to the imported root |
| `variations`, `variation <n>` | List/select children |
| `move <SAN-or-UCI>` | Add/reuse an in-memory legal child |
| `inspect <square>` | Occupant, attackers, legal access, and relevant pins |
| `analyze` | Start/restart bounded current-position analysis |
| `compare <move> <move>` | Analyze two legal moves without moving the cursor |
| `details <candidate-number>` | Latest result evidence and continuation |
| `json` | One complete `schema_version: 1` shared-view object |
| `cancel`, `help`, `quit` | Control work and lifecycle |

FEN input creates one root-only game, so `games` lists it and `game 1` selects it.
For a backward `goto`, walk the selected node's ancestors; for a forward `goto`,
follow child 0 from the current node. `start` selects the root and `end` follows
child 0 from the selected node. Every successful load, game/node selection,
navigation, and trial move automatically enqueues analysis after engine
integration. `analyze` explicitly retries/restarts it, and `compare` starts a new
request. `load` consumes the remaining command as a
Windows path and removes one matching pair of quotes; it does not treat
backslashes as escapes or execute shell content.

Progress goes to stderr and results to stdout, with updates coalesced to at most
four per second. `json` emits a snapshot, not a separate protocol. Redirected
input suppresses prompts and waits for latest analysis at EOF. `quit` cancels
immediately. Ctrl+C cancels active analysis and otherwise clears input.

## Checkpoint gates

| ID | Accepted outcome | Dependency | Primary verification | Status |
|---|---|---|---|---|
| M1-01 | Consistent documentation and contracts | — | Contract cross-check; baseline suite | complete |
| M1-02 | Navigable CLI session for validated PGN/FEN | M1-01 | Parser fixtures; session transcripts | complete |
| M1-03 | Correct shared board facts and move changes | M1-02 | Structured mirrored fixtures | complete |
| M1-04 | Bounded, cancelable persistent engine analysis | M1-02 | Fake lifecycle tests; real Stockfish | complete |
| M1-05 | Evidence-backed comparisons and tactical explanations | M1-03, M1-04 | Counterexample fixtures | complete |
| M1-06 | Complete text/JSON analysis workflow | M1-05 | Consumer tests; Windows check | complete |

### M1-01 — Documentation and contract baseline

Align the specification, features, architecture, README, changelog, and this
plan. Remove Syzygy commitments, defer recall and practical-best ranking, move
bounded engine verification into Phase 1, and record input, lifecycle, CLI, and
engine-evidence semantics. Verify every promise has an owning checkpoint, search
for conflicting phase/GUI-first language, and run the baseline suite. Planned
features must remain labeled unimplemented. Gate: documentation review and
baseline pass. Commit: `docs(m1): Define CLI analysis scope and checkpoint plan`.

**Objective:** Make M1 implementable without conflicting product promises.  
**Scope/approach:** Align all owning documents and preserve the approved contracts.  
**Acceptance criteria:** Every promise has a checkpoint; phases agree; runtime work remains pending.  
**Regression watchlist:** Durable invariants and later-phase intent remain intact.  
**Tests/evidence:** Documentation searches, probe record, and baseline pytest.  
**Documentation/handoff:** Maintain status, commands, decisions, and deviations here.  
**Adversarial review:** Challenge exhaustive-threat and arbitrary-position claims.  
**Commit gate:** Documentation review and baseline pass with no runtime changes.

### M1-02 — Validated inputs and navigable session

Implement PGN/FEN parsing, session operations, ASCII board display, navigation,
and legal trial moves. Read UTF-8 with optional BOM and CRLF; reject invalid
encoding. Require six-field FEN, valid placement/state, nonnegative halfmove and
positive fullmove counters. Counters use canonical ASCII decimal without leading
zeros (except halfmove `0`) and are capped at 1,000,000,000 so malformed input
cannot create unbounded integers or overflow the later engine boundary. `fen`
and `load` reject incomplete, invalid, or
unparseable input with actionable errors; no M1 command repairs input.

Preserve standard PGN headers, comments, NAGs, and nested variations. Original
move tokens must match canonical
standard SAN, including accurate check/mate suffixes. Coordinate or overspecified
notation is rejected in PGN; interactive `move` still accepts legal SAN or UCI.

Headers are optional, but every present tag must be valid. Every game, including a
zero-move game, has exactly one terminating mainline result marker (`1-0`, `0-1`,
`1/2-1/2`, or `*`), with no following SAN in that game. A result marker inside a
variation is rejected, and a `Result` header must match the
movetext marker. Reject missing markers, unmatched braces/parentheses, malformed
tags, illegal or ambiguous SAN, parser errors, and all leftover/truncated text;
never accept parser recovery as complete input. `SetUp` is only `0` or `1`;
`SetUp "1"` requires `FEN`, while a valid `FEN` without `SetUp` is accepted.
Errors identify the game and line/column when available, state the problem, and
tell the user to correct and reload. Limits: 10 MiB/file, 1,000 games,
100,000 total move nodes, variation depth 64, 16 KiB/command. Name exceeded
limits in errors. Retain history; standalone FEN lacks repetition history.
Separate board outcomes, claimable draws, and recorded PGN result metadata.

Accept when navigation and trial branches work for ordinary/composed positions,
terminal states are correct, failed loads leave state unchanged, and imports are
never written. Cover multi-game PGN, unusual starts, black to move, comments,
NAGs, repetition, malformed input, rights, en passant, promotion, terminal
states, and limits with fixtures/transcripts. Adversarially check ambiguous SAN,
root/end navigation, oversized input, and source hashes. Commit:
`feat(cli): Add PGN and FEN session navigation`.

**Objective:** Deliver the first usable CLI and shared session foundation.  
**Scope/approach:** Implement the parsing, session, limit, and command contracts above.  
**Acceptance criteria:** Valid inputs navigate/branch; invalid loads are transactional; imports are unchanged.  
**Regression watchlist:** FEN normalization, parser recovery, duplicate children, lost variations.  
**Tests/evidence:** Named parser/history fixtures and scripted CLI transcripts.  
**Documentation/handoff:** Record grammar, limits, navigation semantics, examples, and evidence.  
**Adversarial review:** Exercise ambiguity, invalid-after-valid loads, boundaries, and source hashes.  
**Commit gate:** Parser/session criteria and ordinary suite pass.

### M1-03 — Shared board facts and move deltas

Compute geometric attacks for both colors, actual-side legal moves, absolute
pins, check, and before/after attack changes. Track moved, captured, promoted,
and castling-rook identities and only geometry-supported slider changes. Never
flip turns to invent access or infer safety/ownership from contact. Test mirrored
pins, rays, captures, castling, en passant, promotion, and unusual material.
Review every sentence for claims stronger than its fact. Commit:
`feat(analysis): Explain board relationships and move changes`.

**Objective:** Make static explanations trustworthy before engine composition.  
**Scope/approach:** Implement identity-bearing facts and deltas through the shared layers.  
**Acceptance criteria:** References are explicit; deltas reconstruct moves; consumers share facts.  
**Regression watchlist:** Pinned control, en passant, castling, and promotion identity.  
**Tests/evidence:** Named, mirrored structured fixtures and independent delta recomputation.  
**Documentation/handoff:** Document exact meanings and unsupported claims.  
**Adversarial review:** Read every sentence as a stronger inference than intended.  
**Commit gate:** Static semantics, mirrors, consumer checks, docs, and suite pass.

### M1-04 — Persistent engine and bounded lifecycle

Use python-chess's asynchronous UCI interface behind an injected adapter. Default
to the established local Stockfish path with optional explicit native launch
argument. Use one engine, one thread, 64 MiB hash, five seconds/request, five
seconds startup timeout, and two seconds stop/quit grace. Start lazily for
eligible nonterminal positions and send root plus history. Return typed,
perspective-explicit scores, mate/bounds, engine identity, depth, nodes, elapsed
time, and legal PVs; malformed PVs fail evidence. Budget exhaustion is bounded
completion, distinct from cancellation/failure.

Test with fake engines for late output, crashes, startup/stop timeout, rapid
supersession, illegal PV, bounds, and shutdown. Mandatory gate includes real
Stockfish probes for unusual material, cancellation recovery, and terminal
states using `NAMICHESS_TEST_ENGINE`. Verify no owned child remains. Commit:
`feat(engine): Add bounded persistent Stockfish analysis`.

**Objective:** Reuse bounded analysis without stale results or leaked processes.  
**Scope/approach:** Implement the injected lifecycle and typed evidence contract above.  
**Acceptance criteria:** One reused process/search; clean cancellation; stale rejection; usable failure state.  
**Regression watchlist:** Lost history, perspective inversion, growing queues, mislabeled cancellation.  
**Tests/evidence:** Fake lifecycle cases and mandatory real-Stockfish probes.  
**Documentation/handoff:** Record defaults, baseline, failures, startup, and cancellation evidence.  
**Adversarial review:** Stall engines, deliver late results, and inspect owned-process cleanup.  
**Commit gate:** Lifecycle tests, real-engine checks, docs, and suite pass.

### M1-05 — Candidate comparison and tactical evidence

Use one outer five-second search envelope measured by a monotonic deadline after
lazy startup/configuration; the five-second startup timeout and two-second
stop/quit grace are outside it. Spend at most one second surveying five roots.
Form the unique union of those roots and up to two explicit legal comparison
moves (at most seven), sort it by UCI for deterministic stable candidate IDs,
then divide remaining time equally and re-search each from the original root.
Start no probe after the deadline. Candidate rank is separate from identity and
may change. Final certified rank orders exact typed scores from the original
mover's perspective, then UCI as a tie-break; bound-only, missing, or interrupted
evidence stays provisional and receives no certified rank.
Enumerate current check and mate-in-one directly. Replay legal engine lines and
describe checks, captures, recaptures, and material changes only as consequences
in that line. Test immediate mate after candidates across all legal replies;
label longer mates as Stockfish-reported with metadata. Surface final/survey sign
or mate-status disagreement and coverage. Never infer forced gain from one PV.

Use deterministic engine doubles plus poisoned-capture, sound-sacrifice,
pinned-recapture, forced-evasion, capped-choice, mate-over-material, and mirrored
fixtures. Validate historical spec positions before making them goldens; do not
pin old centipawn values. Commit:
`feat(analysis): Compare candidates with concrete tactical evidence`.

**Objective:** Rank and explain candidates without overstating coverage.  
**Scope/approach:** Apply the bounded allocation and legal-evidence rules above.  
**Acceptance criteria:** Evidence states and coverage are explicit; mate and legal-line claims are correct.  
**Regression watchlist:** Sacrifice dismissal, score inversion, provisional rank, truncated PV claims.  
**Tests/evidence:** Deterministic doubles, named counterexamples, mirrors, and engine smoke tests.  
**Documentation/handoff:** Publish claim vocabulary, allocation, coverage, and catalog ownership.  
**Adversarial review:** Try to refute every explanation with a legal alternative.  
**Commit gate:** Comparisons, counterexamples, catalog, docs, and suite pass.

### M1-06 — Complete CLI and shared consumer contract

Finish progressive tables, priority explanations, details, inspection, and JSON
snapshots. JSON uses `schema_version: 1`, algebraic squares, UCI plus SAN moves,
tagged centipawn/mate scores, and distinct absent versus zero evidence. CLI owns
no candidate selection or chess classification. Candidate numbers remain stable
within a result revision. Test text/JSON parity, placeholders, redirected input,
current-revision details, bounded updates, and Windows interaction while typing,
canceling, loading spaced paths, and recovering from engine failure. Confirm a
hypothetical GUI can render every fact without parsing prose or inferring chess.
Commit: `feat(cli): Present shared analysis results and evidence`.

**Objective:** Deliver a usable CLI whose shared information can drive a later GUI.  
**Scope/approach:** Complete progressive text, details, inspection, interrupts, and JSON.  
**Acceptance criteria:** Input remains usable; revisions match; consumers need no prose parsing.  
**Regression watchlist:** Drifting IDs, stale details, consumer disagreement, Unicode, render queues.  
**Tests/evidence:** Parity, placeholders, transcripts, revision/update bounds, Windows interaction.  
**Documentation/handoff:** Add runnable examples, recovery guidance, Windows evidence, and schema.  
**Adversarial review:** Reconstruct a GUI from JSON alone and flag missing semantics.  
**Commit gate:** Consumer parity, Windows integration, docs, and full suite pass.

## Final milestone verification

Run an end-to-end PGN workflow through navigation, variation, analysis,
comparison, inspection, trial move, return, JSON, and close. Repeat with the
fifteen-queen position and its mirror; confirm over-32-piece positions are usable
with engine analysis unsupported. Exercise malformed transactional loads,
repeated cancellation, engine crash/retry, and source-file hash preservation.
Run the full suite with real Stockfish, inspect distribution contents/licenses,
verify bounded retained work and process cleanup, record elapsed/cancellation
observations, and review the complete diff for false chess claims, GUI assumptions,
scope expansion, and unresolved regression risks.

## Final state

The user added a final combined invariant review after the implementation and
original checkpoint verification completed. This audit is an explicit additional
milestone acceptance gate; it does not silently redefine the completed checkpoint
criteria. Evidence and findings are recorded in `M1-INTEGRATION-REVIEW.md`.

- Checkpoint commits: M1-01 `7f15bd6`, M1-02 `10922dc`, M1-03 `782aac7`,
  M1-04 adapter `bfa613c`, and M1-05 `577902e`. Strict import follow-up:
  `6b4fdb7`. M1-06 and combined-audit identifiers remain pending.
- Final real-engine suite: 155 passed in 24.94 seconds with Stockfish 18 enabled,
  including the joined real CLI workflow and all invariant regressions.
- Native Windows verification covered redirected UTF-8 input/output, five-root
  survey and five focused probes, exact and provisional ranks, rapid PGN
  navigation, trial/back, comparison, inspection, cancel/replacement sequencing,
  typed-buffer preservation, invalid FEN, fifteen queens, and the over-32 guard.
- Final wheel SHA-256:
  `caf44c3ca108ca3f8ce357bb30a341009b97ca5f475608a9ad59c0c803f2959c`.
  Temporary isolated extraction/import/CLI-quit verification passed. The wheel
  contains the catalog, twelve SVG pieces, project/art licenses and notices, and
  no engine binaries or tests.
- Independent adversarial reviews closed lifecycle, evidence, stale-result,
  rendering, and consumer-reconstruction findings. No confirmed substantive M1
  defects remain.
- No Stockfish process remained after final verification.
- Deferred work remains GUI, training, practical-best ranking, broad threats,
  SEE, persistence/export, and the other exclusions above.
