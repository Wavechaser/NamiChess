# M2 Implementation Plan — Continuity and Local Tactical Understanding

Status: active. M2.01 is committed; M2.02 and M2.03 have passed independent review; M2.04/M2.05 are in progress.

## Main objectives

- Explain how a legal move changes piece relationships, lines, defensive resources, and immediate possibilities.
- Add bounded exchange and forcing analysis with qualified local safety, trapping, and overload assessments.
- Expose these capabilities through CLI and interface-neutral application snapshots that a later GUI can consume.
- Persist one shared orientation default while keeping in-session flipping local to each interface.

## Scope and decisions

M2 delivers analysis and GUI preparation, not an interactive GUI. Included work is identity-bearing relationship continuity, latent slider rays, static exchange evaluation (SEE), bounded forcing continuations, evidence-backed local assessments, promotion and special-move regressions, shared orientation settings, CLI orientation controls, shared serialization, evidence previews, and focused move or piece probes.

Comprehensive bilateral threat classification, practical-best ranking, WDL adequacy, strategic plan generation, training, export, saved-analysis caches, GUI hosting, custom themes, network transports, generic graph frameworks, worker pools, databases, and generalized event systems are explicit non-goals. M2 must not state unconditionally that a move is safe, a restricted piece is won, or multiple defensive contacts establish overload.

The analysis invariants in `AGENTS.md` govern every checkpoint: geometric control, legal access, and tactical ownership remain distinct; identities replace bare counts; static analysis proposes and search verifies; engine values belong to resulting positions; and background work is bounded, cancelable, revision-scoped, and truthfully incomplete when limits are reached.

Ordinary engine analysis retains M1's five-second search budget and resource settings. Additional ordinary local search is capped at 250 ms. An explicit focused probe gets a fifteen-second aggregate budget after engine preparation, with at most one second for local search. Local forcing exploration stops at four plies, 10,000 expanded positions, or its deadline, and checks cancellation at least every 32 expanded positions. These are policy limits rather than performance claims; exhaustion yields incomplete coverage.

Orientation persists as `white`, `black`, or `turn`; absent settings default to `white`. Both adapters must use the same typed reader and resolver. Import precedence is explicit import choice, process override, then saved default. `turn` resolves once from the newly selected imported root. Navigation does not auto-flip. A local flip does not save, revise the position, transform canonical coordinates or score perspective, or submit analysis. Imports without overrides reload the saved default so running interfaces observe another interface's saved change.

Promotion already retains piece identity, changes type, recomputes static facts, and appears in move delta and continuation material evidence. M2 expands coverage to all four promotion types and capture-promotions. FEN alone cannot reconstruct promotion provenance.

Baseline commit `8b03c09` records the approved continuity-first roadmap. Baseline evidence before implementation was 145 ordinary tests passed with 10 optional integrations skipped, and 155 Stockfish-enabled tests passed in an isolated temporary directory. A prior shared pytest temporary directory produced permission errors; fresh `--basetemp` is the established remedy. No product decisions remain unresolved. Broader semantics, new dependency families, larger resource limits, or expanded milestone scope require review.

Implementation may be delegated by checkpoint, but each coherent commit requires an independent adversarial reviewer without builder context. The coordinating agent owns integration and commits exact paths. If reviewers or tests expose consecutive defects in the same category or subsystem, pause local patching and assess the upstream contract or architecture; land a separate focused refactor when the weakness is systemic.

## Investigation and regression map

| Existing entry point or contract | Failure risk | Detection gate |
|---|---|---|
| `Session.play`, navigation, and `PositionContext` replay | Trial analysis mutates the selected game or loses repetition history | M2.03, M2.07, final sweep |
| `PieceId`, placement reconstruction, `PositionFacts`, and `MoveDelta` | Promotion becomes a new piece; captures or castling leave stale relationships | M2.03 |
| Actual-side legal moves versus bilateral attacks | Turn alternation is misreported as mobility loss; pinned geometric defenders disappear | M2.03–M2.06 |
| `AnalysisController` request and revision sequencing | Local probes block input, leak into a new position, or survive cancellation | M2.05, final sweep |
| Stockfish scores and replayed evidence | A cooperative PV becomes a forced claim; negative SEE rejects a sound sacrifice | M2.04–M2.06 |
| Shared snapshot serializer and explanation catalog | Consumers parse prose; references resolve against the wrong continuation | M2.01, M2.07 |
| Native imports and settings storage | Settings writes damage imports; malformed settings disappear silently | M2.02 |
| Composed-position support | New algorithms assume ordinary material or bypass the 32-piece engine boundary | M2.03–M2.06 |
| Progressive snapshot assembly | Rendering repeats search or retains obsolete evidence | M2.05, M2.07, final sweep |

Static relationships remain usable without an engine. Local search belongs to the bounded analysis lifecycle and never runs from rendering or an unbounded `Session.view()` call.

## Checkpoint register

| ID | Accepted outcome | Depends on | Primary verification | Status |
|---|---|---|---|---|
| M2.01 | Explicit M2 contracts and shared serialization boundary | — | Serializer characterization and ordinary suite | complete |
| M2.02 | Shared orientation defaults and local CLI flipping | M2.01 | Settings round trips and orientation invariance | complete |
| M2.03 | Complete structural move continuity | M2.01 | Named mirrored relationship fixtures | review passed; commit pending |
| M2.04 | Bounded, legality-aware local exchange evidence | M2.03 | Exchange fixtures and unsupported cases | pending |
| M2.05 | Cancelable local exploration and deeper probes | M2.04 | Coverage, budgets, cancellation, engine integration | pending |
| M2.06 | Evidence-backed local assessments | M2.05 | Positive and adversarial counterexamples | pending |
| M2.07 | Integrated CLI explanations and GUI-ready views | M2.02, M2.06 | Shared-consumer and interactive CLI tests | pending |
| M2.08 | Accepted end-to-end M2 delivery | M2.07 | Integration and adversarial sweep | pending |

This register is the completion denominator. New findings are recorded separately and do not silently add requirements.

## Findings ledger

| Checkpoint | Source | Evidence or finding | Disposition |
|---|---|---|---|
| M2.01 | Builder focused verification | Shared serializer and CLI characterization: 21 passed; the first run's missing `.tmp` parent caused one setup error before an explicit workspace temp directory was used | Serializer behavior green; independent review pending |
| M2.01 | Independent reviewer `review_contracts` | Missing terminal/promotion characterization and duplicated architecture sentence | Fixed and independently rechecked: 22 focused passed; ordinary review run 174 passed, 10 skipped; no remaining blockers |
| M2.02 | Independent reviewer `exchange` | 36 focused tests and cross-instance settings/import/flip counterexamples passed | Accepted; empty LOCALAPPDATA fallback tightened to prevent working-directory user data |
| M2.03 | Independent reviewer `review_contracts` | Missing exact special-move relationship tests, mirrors, and above-engine-limit fixture | Added named mirrored assertions and 48-piece fixture; reviewer became test builder and did not approve own changes |
| M2.03 | Independent reviewer `orientation` | Independently checked identities, geometry, special moves and schema; 51 focused static/serialization/exchange tests passed | Accepted; no concrete algorithm defect found |
| M2.01/M2.03 | Coordinator | Consecutive coverage gaps claimed old tests as evidence for new semantics | Verification-process weakness: require explicit claim-to-test mapping; no evidence justifying a runtime refactor |

Append substantive findings here with their checkpoint, independent source, direct evidence, and disposition. Similar consecutive findings must explicitly record whether they reveal an upstream design defect.

## Detailed checkpoints

### M2.01 — Contracts and shared serialization

#### Objective

Establish stable meanings and ownership for M2 results before later producers and consumers depend on them.

#### Scope and approach

Record this active plan, correct the roadmap to defer the actual GUI, and extract schema-version-1 serialization from CLI rendering into an interface-neutral adapter. Keep `render_json` as a delegating compatibility entry point. Preserve the top-level `session` and `analysis` shape and every existing field meaning. Schema version 2 begins only when new public fields land. Add frozen structural, assessment, and coverage values only together with their producing behavior; M2.01 introduces no placeholder model. Every future assessment must identify position, subject, scope, evidence, and coverage, distinguishing observed facts, local-model results, engine evidence, incomplete work, and unsupported cases. Orientation stays out of chess facts and snapshots.

#### Acceptance criteria

- Existing CLI JSON remains semantically identical and deterministic.
- A non-CLI consumer can call the serializer without importing CLI rendering.
- `null`, numeric zero, enums, tuples, nested identities, running analysis, absent analysis, and promoted pieces retain their version-1 encodings.
- Documentation distinguishes witnessed continuations from results established across relevant replies.
- No unused framework or placeholder type is introduced.

#### Regression watchlist

Watch enum encoding, `null` versus zero, White score perspective, nested identities, analysis detachment under the top-level field, and stale-analysis filtering already performed by the application.

#### Tests and evidence

Characterize complete and running snapshots, terminal positions, absent analysis, and promoted pieces. Assert direct shared-serializer output equals the CLI delegate and decoded version-1 shapes remain unchanged. Run `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp <fresh-temp-path>`; pass means all ordinary tests complete without failure.

#### Documentation and handoff

Update `FEATURES.md`, `ARCHITECTURE.md`, `COMMANDLINE.md`, `CHANGELOG.md`, and this plan with ownership, GUI deferral, versioning, evidence semantics, verification results, and current status.

#### Adversarial review

Inspect every serialized reference, verify no application or analysis dependency points into CLI rendering, compare before/after decoded payloads, and reject any unrelated abstraction or schema change. Record reviewer findings and their disposition before closing.

#### Commit gate

Characterization, focused tests, ordinary suite, documentation, and independent review must pass. Commit title: `refactor(interfaces): establish shared M2 view contracts`.

### M2.02 — Shared orientation defaults

#### Objective

Make default import orientation consistent across interfaces while keeping in-flight flips local and cheap.

#### Scope and approach

Add a typed versioned settings reader/writer and shared resolver, constructed only in `composition.py`. Windows storage is `%LOCALAPPDATA%\NamiChess\settings.json`, with injected test locations. Bound input to 64 KiB. Missing files use defaults. Invalid or unsupported files remain untouched and produce a visible fallback; saving must not replace them silently. Save valid changes via a sibling temporary file and atomic replacement while preserving unrelated valid fields.

Add process `--orientation white|black|turn`; leading `--orientation` for `load` and `fen`; local `flip` and `orientation white|black`; persistent `orientation default white|black|turn`; and `orientation` reporting. Saved changes affect subsequent imports, not the current board. Failed imports change neither board nor orientation. Recognized leading options must preserve quoted Windows paths.

#### Acceptance criteria

Fresh adapters resolve the same saved preference; automatic orientation resolves once; flips leave FEN, identities, revision, request ID, and engine activity unchanged; and failed writes preserve the previous settings file with actionable output.

#### Regression watchlist

Windows paths with spaces, malformed imports, local versus persisted state, reversed labels, and accidental changes to shared canonical `board_rows`.

#### Tests and evidence

Test both orientations, two flips, Black-to-move import, all precedence levels, settings reload, failed import, malformed JSON, unsupported version, and failed atomic replacement. Compare canonical analysis snapshots before and after flipping. Run focused interface tests and the ordinary suite.

#### Documentation and handoff

Document commands, settings path, schema, defaults, precedence, failure behavior, and the future GUI's shared-resolver obligation. Update plan evidence and status.

#### Adversarial review

Prove writes touch only the settings file and its owned temporary sibling. Verify flip neither persists nor submits work and permissive option parsing cannot consume a path.

#### Commit gate

All settings, CLI, regression, documentation, and independent review gates pass. Commit title: `feat(interfaces): persist orientation defaults and add local flipping`.

### M2.03 — Structural move continuity

#### Objective

Explain precisely which identity-bearing relationships change after a legal move.

#### Scope and approach

Extend the existing static analyzer without adding a generic graph. Record piece-to-piece attack and geometric-defence relationships, gained and lost contacts, newly geometrically undefended targets, pin changes, and slider-line openings or blockages. A latent ray identifies slider, direction, first blocker, and squares beyond it through the next occupied square. Hypothetical blocker removal remains a geometric diagnostic and is never sent to Stockfish. Reuse the delta builder for played, candidate, and continuation moves. Do not compare opposite turns' legal lists as mobility continuity. Cover captures, castling, en passant, and every promotion choice for both colors.

#### Acceptance criteria

Every relationship delta equals independently recomputed before/after facts; persistent relationships are not re-created; explanations distinguish losing a geometric defender from being tactically lost; and static inspection works above the engine's 32-piece limit.

#### Regression watchlist

En-passant removal away from destination, castling's second mover, pawn-to-slider promotion, pinned defenders, and moving targets that retain relationships.

#### Tests and evidence

Use named, color-mirrored fixtures for cleared and blocked lines, moving defenders, captures, en passant, castling, and underpromotion. Assert exact identities and relationships. Run static/domain/session tests then the ordinary suite.

#### Documentation and handoff

Document new facts and deltas in architecture and interface contracts; add catalog prose only for supported structural claims; update plan evidence.

#### Adversarial review

Reconstruct every fixture independently and challenge each causal phrase. A discovered line must not automatically become a tactic.

#### Commit gate

Focused and ordinary tests, documentation, and independent review pass. Commit title: `feat(analysis): explain structural continuity across moves`.

### M2.04 — Static exchange evaluation

#### Objective

Provide inspectable local exchange evidence without treating material arithmetic as overall move soundness.

#### Scope and approach

Implement target-square capture/recapture minimax on a scratch board with legal captures rather than attacker counts or a least-valued shortcut. Use pawn 1, knight/bishop 3, rook 5, queen 9; include captures and promotion gains; permit legal decisions to stop exchanging; recompute x-rays; respect king safety, pins, en passant, and promotion. Checking positions needing replies outside this model are `unsupported`. Cap evaluation at 4,096 exchange positions and the enclosing deadline. Return line, material result, perspective, status, and limits. Negative SEE never filters engine candidates.

#### Acceptance criteria

All returned lines replay legally; accounting is correct for both colors and capture-promotions; unsupported or incomplete never becomes zero or favorable; negative SEE cannot remove a candidate.

#### Regression watchlist

Illegal king captures, pinned recaptures, intermezzos, special captures, and composed material.

#### Tests and evidence

Use hand-checkable exchange trees, x-rays, alternative orders, both pin directions, en passant, promotion, checking unsupported cases, and a sound-sacrifice candidate-preservation regression. Run focused and ordinary suites.

#### Documentation and handoff

Document the exact model, limits, status, perspective, and replayable evidence; update plan evidence.

#### Adversarial review

Try to produce `completed` where a nonlocal evasion is required and verify each stop choice is legal.

#### Commit gate

Exchange, preservation, ordinary regression, documentation, and independent review pass. Commit title: `feat(analysis): add bounded legal exchange evidence`.

### M2.05 — Local exploration and focused probes

#### Objective

Explore immediate resources under the existing cancelable lifecycle and expose truthful coverage.

#### Scope and approach

Extend immutable request policy/data with ordinary versus focused-probe mode and optional move or piece. Generate checks, captures, promotions, and new direct attacks in deterministic order: checks, captures/promotions, direct attacks, UCI tie-break. Recompute continuity each ply and cover counterchecks, intermediate moves, and quiet defences where a universal claim requires them. Selective exploration yields examples; forced conclusions require complete relevant reply coverage. Ordinary requests share the 250 ms aggregate local budget; focused probes prioritize their subject and may use restricted Stockfish verification. Never flip side-to-move to probe an opponent piece. Run cooperatively in the existing one-running/one-pending controller lifecycle.

#### Acceptance criteria

Node/time limits and coverage are visible; cancel, replacement, and close settle local and engine work; stale partials never attach to new revisions; rendering does not search; terminal and engine-unsupported positions retain useful static output.

#### Regression watchlist

Deadline accounting, startup versus search time, repeated snapshot work, superseded requests, and background tasks after shutdown.

#### Tests and evidence

Use injected clocks and counting collaborators for exact limits. Interrupt local work, preparation, and verification; replace then close; run fake-engine lifecycle tests and Stockfish integration.

#### Documentation and handoff

Record budgets, coverage meanings, scheduling, focused-request contract, results, and current plan status.

#### Adversarial review

Attempt budget escape through nested SEE or result assembly and inspect cancellation yield frequency and retained state.

#### Commit gate

Budget/lifecycle tests, engine suite, documentation, and independent review pass. Commit title: `feat(analysis): add bounded local exploration and focused probes`.

### M2.06 — Local safety, trapping, and overload

#### Objective

Turn local evidence into useful assessments without overstating completeness.

#### Scope and approach

Move safety reports observed failure, locally established failure under declared coverage, or no refutation found. Trapping enumerates actual-turn legal exits and reports total, examined, refuted, unresolved; only complete supported coverage permits “no locally surviving exit,” while zero exits does not prove the piece is won. Overload is initially limited to concrete defence of attacked friendly pieces: multiple duties nominate a candidate, but legal play must demonstrate that fulfilling one abandons another. Account for removing attackers, counterchecks, and declining captures before a locally established overload. Engine/local disagreement remains visible. Verified mate outranks material recommendations.

#### Acceptance criteria

Shared defenders alone never confirm overload; each refuted exit has a legal reply and identity; restricted mobility does not claim a forced win; and disagreement blocks unconditional wording.

#### Regression watchlist

Cooperative lines, quiet escapes, compensation, counter-threats, and defenders moving legally along a pin.

#### Tests and evidence

Pair each positive fixture with a near-identical counterexample, including trapped-but-not-won, unsearched escape, quiet saving move, overload relieved by countercheck, and negative-SEE compensation. Mirror perspectives.

#### Documentation and handoff

Define every label, prerequisite, and uncertainty phrase; update content and the plan together.

#### Adversarial review

Produce a claim-to-evidence table listing branches and omissions for each fixture and verify the permitted wording.

#### Commit gate

Counterexamples, ordinary/engine tests, docs, and independent review pass. Commit title: `feat(analysis): assess local safety trapping and overload`.

### M2.07 — CLI integration and GUI preparation

#### Objective

Make M2 usable in CLI while proving a future GUI can consume the same semantics.

#### Scope and approach

Expand `inspect <square>` with relationships, rays, and local assessments; add `changes`, `probe move <SAN-or-UCI>`, `probe piece <square>`, richer `details <n>`, and read-only `line <candidate-number> <ply>` preview. Preview cannot move the session, add PGN variations, or start analysis. Resolve commands against the current revision with existing strict SAN/UCI and size bounds. Publish schema-version-2 self-contained snapshots with shared preview operations and immediate parent/child navigation references, not the whole game tree. Stable references remain request-scoped. M2 adds no HTTP server, stream protocol, shell, or GUI. Concise output shows at most three priority explanations before progressive detail.

#### Acceptance criteria

CLI and a test-only non-CLI consumer derive identical structured results; preview leaves position, revision, variations, and source bytes unchanged; flipping changes display only; stale references fail without mutation; snapshots contain no mutable board, engine, path authority, or terminal-only encoding.

#### Regression watchlist

Candidate reorder, continuation-position references, mixed stdout JSON, repeated computation, and full-tree snapshot growth.

#### Tests and evidence

Exercise commands through dispatch, including special-move preview. A non-CLI test consumer must resolve every piece, square, explanation, and evidence reference without CLI helpers. Run focused, ordinary, and engine suites.

#### Documentation and handoff

Update README, CLI contract, schema version, preview semantics, GUI ownership, and active-plan evidence. State clearly that the actual GUI remains future work.

#### Adversarial review

Remove any hidden prose/CLI dependency from the consumer and test stale preview plus rapid navigation while a probe completes.

#### Commit gate

Consumer/CLI tests, engine suite, docs, and independent review pass. Commit title: `feat(cli): expose continuity and focused tactical inspection`.

### M2.08 — Overall final sweep

#### Objective

Accept the combined workflow only after all checkpoint gates pass.

#### Scope and approach

Exercise a Unicode-path multi-game PGN through navigation, relationship inspection, capture-promotion play/undo, candidate comparison, evidence preview, focused probe, flip, cancellation, and retry. Verify source hashes, history, canonical coordinates, perspective, and references throughout. Cover malformed settings, invalid imports, engine failure, and positions above 32 occupied squares. Run fifty rapid navigation/probe replacements with a fake engine and verify settlement, bounded retained state, one active/one pending maximum, and no owned child after close. Reconcile every regression-map row and finding; do not raise limits to hide failure.

#### Acceptance criteria

Every preceding checkpoint is closed; the integrated workflow passes; lifecycle/resource observations meet declared bounds; all public docs agree; no unsupported claim, accidental write, or speculative framework remains.

#### Regression watchlist

Cross-checkpoint state drift, settings/import collision, stale evidence after orientation change, resource retention, platform path behavior, and schema/document inconsistency.

#### Tests and evidence

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $m2TestTemp
```

With Stockfish:

```powershell
$env:NAMICHESS_TEST_ENGINE = (Resolve-Path '.\.tools\stockfish\stockfish-windows-x86-64-avx2.exe').Path
$m2TestTemp = Join-Path $env:TEMP ('namichess-m2-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $m2TestTemp
```

Also complete the interactive Windows workflow and `git diff --check`. Record command, terminal result, fixture evidence, timing diagnostics, and lifecycle observations; test counts alone do not close coverage.

#### Documentation and handoff

Ensure README, features, architecture, CLI contract, changelog, and this plan agree. Move this plan to `docs/obsolete/` only after acceptance and incoming-link cleanup.

#### Adversarial review

Review the complete diff and workflow independently of builder context. Trace every chess claim to facts and appropriately scoped evidence, and every acceptance criterion to an observation.

#### Commit gate

All integration, platform, repository-cleanliness, documentation, and independent review evidence passes. Commit title: `test(m2): verify continuity analysis across the complete workflow`.

## Overall final sweep

M2.08 is a separate gate, not a substitute for checkpoint-owned regressions. It must exercise behavior across checkpoint boundaries, the broadest ordinary and Stockfish suites, Windows CLI behavior, parser rejection and recovery, settings permissions and atomicity, truthful unsupported/incomplete results, cancellation and retained lifetimes, source-file preservation, public-contract consistency, and repository cleanliness. Overall completion requires recorded terminal observations and an independent adversarial review; green checkpoint tests alone are insufficient.

## Resumption block

- **Current checkpoint:** M2.02/M2.03 commits, followed by M2.04/M2.05. M2.01 committed as `98268b5`.
- **Completed evidence:** Baseline commit is `8b03c09`; pre-M2 baselines were 145 passed plus 10 skipped ordinarily and 155 passed with Stockfish in an isolated temporary directory. M2.01 focused serializer/CLI verification passed 21 tests after creating the missing workspace temp parent.
- **Next action:** Complete orientation CLI integration and structural continuity verification; commit each independently with its tests, documentation, and fresh reviewer evidence.
- **Established verification:** `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp <fresh-temp-path>`; use `NAMICHESS_TEST_ENGINE` and the executable above for the final engine sweep.
- **Blockers/unresolved decisions:** None currently. A shared Windows pytest temp permission failure is handled with a fresh directory.
- **Preserve:** Imported files, `.tools`, virtual environments, local settings, unrelated worktree changes, and all source content outside the named checkpoint paths.
- **Deferred findings:** Actual GUI, comprehensive threats, practical ranking, training, export, themes, network transport, and analysis persistence.
- **Stop for review if:** implementation needs broader chess semantics, unsupported-case guessing, increased budgets, new runtime dependency families, weakened import/lifecycle contracts, or scope beyond this register.
