# NamiChess — Core Product Spec

**Version** 0.4 (draft) · **Date** 2026-09-05 · **Status** pre-implementation

## 1. Product

Engines answer "what is strongest under exact play." NamiChess answers:

- What does this position permit?
- What did the last move change or enable?
- What is urgent?
- Why is one reasonable move preferable to another?
- Can this user understand and continue the resulting position?

The backend is rating-agnostic and adapts its search, disclosure, and continuation
burden through explicit settings rather than an inferred skill profile. Search
length is not human difficulty: a forcing mate in twelve may be easy to execute,
while a three-move line containing one inexplicable quiet move may be unusable.

NamiChess optimizes for **executable chess**:

```text
maximize  P(this user retains an acceptable outcome through the analyzed line)

subject to
  - no verified near-term tactical failure, unless every move fails
  - no meaningful concession from the best available outcome
```

Engine-best and practical-best may differ. Show both; prefer the practical move
when it preserves substantially the same outcome with lower execution burden.

| Error | Definition | Priority |
|---|---|---|
| **Omission** | A meaningfully better resource was available but not played | Primary |
| **Continuation** | The resource was found, but its idea or follow-up was missed | Primary |
| **Trajectory** | Control, activity, or initiative decayed over several moves | Secondary |
| **Commission** | A move immediately loses material, position, or mate | Safety baseline |

### Rules

1. Reject tactically unsound moves before comparing executability.
2. Treat near-equivalent moves as a class; exact engine rank is evidence, not instruction.
3. Explain moves contrastively, from the earliest causal difference.
4. Extend analysis through legible decisions; spend its budget at quiet, branching,
   or counterintuitive nodes.
5. Static analysis proposes facts and causal stories; search falsifies them.
6. Report consequences of opponent moves, not invented intent.
7. Compute broadly, store completely, and disclose progressively.
8. Make every metric perspective-explicit and mirror-tested.
9. Derive principles and familiar motifs from verified piece–square relationships;
   neither opening books nor annotation glyphs are explanations.

## 2. Analysis

### 2.1 Adequate moves

A move is adequate when it survives verified tactics, remains within a configured
engine-WDL loss from the best move, and—when winning—remains above a clearly-winning
floor. When all moves lose, adequacy is relative to the best resistance available.
Engine WDL is labeled as engine self-play calibration, not personal win probability.

### 2.2 Piece–square model

The common representation is a graph whose nodes are pieces and squares and whose
edges mean attack, defence, occupation, access, blockage, pin, route, or enablement.
Moves add and remove edges. Tactical lines and strategic plans are different ways
those changes propagate.

Keep three distinct views of every square:

1. **Geometric control** — pieces attacking it under chess attack rules.
2. **Legal access** — pieces able to move or capture there now.
3. **Tactical ownership** — the result of the ordered exchange sequence.

Counts expand to piece identities. Counts alone never establish safety.

`SquareInterest` records why a square matters to each side:

- contested ownership, tactical pivots, defensive keystones, and king access;
- safe reachability and resistance to pawn or piece challenges;
- outposts, entry and blockade squares, piece routes, and break enablers;
- resources, mobility, or restriction enabled by occupation or control.

A formal hole is interesting only when it is useful, reachable, and persistent.

`PieceProfile` projects the same graph from a piece:

- legal, safe, and latent mobility;
- useful destinations and routes;
- important squares controlled and targets approached;
- current and prospective attackers, defenders, and challengers;
- pins, overloads, blocking duties, king shielding, and retreat options;
- activation distance to a forcing, restricting, or necessary defensive role.

Labels such as good bishop, bad bishop, or knight outpost must expand to this
evidence. An apparently inactive piece may still be a critical defender or blocker.

Every move produces a `MoveDelta` containing:

- control gained and lost;
- pieces newly attacked, defended, loose, pinned, or overloaded;
- rays opened and closed;
- checks, captures, threats, and pawn breaks enabled;
- safe mobility and king flight squares gained or lost.

`SquareInterestDelta` and `PieceProfileDelta` expose the affected squares and
pieces. Together they are the base explanation of the opponent's last move and
every candidate comparison.

### 2.3 SEE, latent rays, and enablement

python-chess 1.11.2 has no SEE method. Implement and validate SEE with a scratch
board so removed attackers reveal x-rays. Promotions, en passant, and pinned
recaptures must be handled or return `unsupported`. SEE is evidence, not a gate on
sound sacrifices.

For each slider, remove its first blocker and recompute its attacks. Chain newly
reached pieces and squares into causal paths:

```text
move → blocker vacated → ray opened → defender displaced → resource enabled
```

Cage and self-block deletion tests are attribution signals, not simulations of an
actual capture.

### 2.4 Decision burden

At each future **user** turn, compute the adequate move set. Many adequate moves are
forgiving; one may still be easy when it is an obvious check, capture, recapture,
or continuation of a stated plan.

At each **opponent** turn, group credible replies by the distinct response or plan
they demand. Several moves permitting the same plan form one reply family.
Credible replies include near-best moves and forcing deviations that create a
distinct user problem even when objectively inferior.

Record:

- user choice width;
- opponent reply-family width;
- user bottleneck count and difficulty;
- forcing coverage;
- distance to visible payoff or stable resolution;
- required plan changes and stability across deviations.

Initial findability is heuristic. With enough personal data:

```text
P(hold at node) = sum P(user chooses move) over adequate moves
line executability = product of P(hold) over future user decisions
```

Across opponent reply families, report the burden range and worst supported branch
rather than assuming reply probabilities. Line length has a small cumulative cost;
report the worst bottleneck separately.

### 2.5 Threats and responses

`ThreatAssessment` is bilateral and distinguishes contact from consequence:

```text
source and target
geometric contact and legal executability
soundness              illusory | conditional | sound
immediacy              current | next move | preparatory
response cost          free | useful | costly | only move
persistence            expires | renews | transforms
severity and payoff
preconditions, adequate responses, and verification
```

For each apparent defender, record geometric defence, legal recapture, exchange
soundness, tactical availability, and any pin ray. python-chess detects absolute
pins and legal moves but counts pinned pieces as geometric attackers. A pinned
piece may defend along its pin line or constrain the enemy king; it is removed only
from recaptures it cannot legally or tactically make. Relative pins and overloaded
defenders require SEE and search.

After every response, recompute the threat. Direct defence, evacuation, blocking,
counter-threats, intermezzi, and development-with-tempo may neutralize, supersede,
or transform it. A forced response can have negligible or negative cost when it
develops a piece or attacks something more urgent.

Named combinations such as Greek gifts and fishing poles are labels on verified
enablement graphs. Show present prerequisites, missing prerequisites, and triggers;
do not mark a motif sound because its shape is familiar.

### 2.6 Complexity-bounded traversal

The analyzer has a hard compute cap and a separate decision budget:

- extend checks, forced replies, recaptures, and stable-plan continuations cheaply;
- charge more for quiet only-moves, branching replies, delayed payoff, temporary
  material loss, and plan changes;
- stop giving move-by-move instruction when the decision budget is exhausted;
- switch to a durable plan explanation at that boundary.

Mate distance is metadata. A verified M12 can be practical when its burden is low;
a shorter opaque line can lose to an adequate, steadfast alternative.

Static search proposes tactics by enumerating checks, captures, direct attacks, and
candidate sacrifices without pruning by material sign. A mate claim must consider
every legal defence and be verified by Stockfish, Syzygy, or complete proof search.
Selective forcing search never proves mate by itself.

### 2.7 Principles and closed positions

Opening principles are a default policy under uncertainty, not book authority.
After concrete threats and tactics, prefer moves that secure the king, contest
important central squares, develop the least useful piece into a durable role,
improve coordination, preserve future choices, and avoid unjustified irreversible
moves or lost tempi. Each claim is derived from `SquareInterest`, `PieceProfile`,
and their deltas.

An opponent's unusual move may create a real threat, a free-response threat, or no
useful effect. State what it creates and concedes. Safe development that answers an
attack can be preferable to passive defence; hanging material and concrete mating
threats override general principles.

When no concrete line is sufficiently forcing, explain durable changes:

- safe routes for poorly placed pieces;
- pawn-break preparation and prevention;
- outposts and durable destination squares;
- open and semi-open line access;
- favorable exchanges and preserved defenders;
- space, restriction, safe mobility, and prophylaxis;
- plans that survive several reply families.

The engine line is an example realization, not a sequence to memorize.

## 3. Explanation and learning

### 3.1 Review order

```text
[1] STATUS     outcome class · verified mate · practical complexity
[2] CHANGED    consequences of the last or candidate move
[3] URGENT     checks · captures · direct threats · loose pieces
[4] PLAN       restriction · mobility · breaks · routes · prophylaxis
[5] CHOICE     practical candidate · engine optimum · decisive contrast
```

Show at most three priority facts initially. Full maps, candidates, and engine
evidence are expandable. Mate suppresses inferior material recommendations, never
its causal explanation, and does not become the practical choice solely because it
exists.

The board provides complementary `SQUARES` and `PIECES` lenses. Square overlays
separate tactical action value from strategic interest; piece overlays show safe
destinations, latent routes, challenges, and duties. Engine loss belongs to the
move arrow, not automatically to its destination square.

Every inspected move reports:

```text
classification       only move | practical choice | equivalent | marginal preference
compared with         played move or selected alternative
immediate delta       changed board facts
mechanism             compact causal label
threat/prevention     credibility · response cost · persistence
earliest pivot        first meaningful divergence
reply families        distinct opponent responses
continuation burden   widths · bottlenecks · forcing · plan changes
piece/square effects  roles, access, control, routes, and concessions
outcome evidence      engine WDL/eval · SEE · verified line
```

**Line mode** presents a concrete continuation while its decisions remain legible.
**Plan mode** states the invariant idea, triggers, and durable changes when the line
becomes branching or opaque. The tool may say that no instructionally meaningful
best move exists because several moves preserve the same outcome.

### 3.2 Training and review profile

The first usable product includes active recall:

1. Show a position under an optional clock.
2. Ask the user to mark controls, urgent resources, and candidate moves.
3. Reveal verified misses in the fixed review order.
4. Test the idea or next move at important continuation nodes.
5. Save the failure type and decision conditions.

An omission requires a meaningfully better candidate, a verified causal
explanation, and an actionable difference. Findability ranks omissions;
centipawn loss alone does not.

Track whether the user missed the resource, misunderstood it, missed its follow-up,
made an execution error, or chose an adequate practical alternative. Finding a
sound resource and then losing its thread is a first-class training event.

Do not generate `!` or `!!` as product objectives. Preserve imported annotations,
but expose criticality, sacrifice, surprise, threat recognition, and continuation
difficulty as separate facts. A PGN cannot establish whether the move was understood;
quiz responses and later continuations provide that evidence.

Keep review data explicit: saved misses, continuation failures, decision context,
and quiz responses may build a review queue, but the first product does not infer a
multi-game skill model. Trajectory analysis is added only if real use justifies it.

## 4. Engine and application

Users select `Foundation`, `Club`, or `Advanced`, then may override search effort,
candidate breadth, continuation burden, visible explanation layers, and resource
use. The application resolves the preset plus sparse overrides into an immutable
policy for each job. Presets affect effort and presentation, never chess truth or
tactical-verification requirements. Saved analyses retain the resolved policy and
engine/analyzer identity.

Stockfish is a persistent analysis service, not merely a final verifier. Its work
is prioritized and progressive:

1. broad shallow survey of root choices;
2. focused probes for interesting pieces, squares, threats, and principled moves;
3. opponent-reply and user-continuation sampling for practical candidates;
4. deep verification of sacrifices, mate, unstable scores, and adequacy boundaries;
5. background analysis of unresolved explanations and completed-game positions.

A provisional `MultiPV 8–16` search around depth 8–12 maps the choice landscape.
MultiPV is wide only at the root; every later branch requiring width is re-rooted
and analyzed separately. Search all legal moves coarsely where exact choice width
is required; a capped result is reported as `N+`, never as a complete count.

For each legal move, action loss is its engine value below the best analyzed move,
using a consistent perspective and budget. This supports destination and move-arrow
heatmaps, but the value belongs to the resulting position rather than one square.
`SquareInterest` and `PieceProfile` supply the causal attribution. Agreement
strengthens an explanation; disagreement creates a probe for missing tactics or
features. Unsearched moves remain unknown, not bad.

Use WDL expected score for outcome bands and centipawns as supporting evidence.
Search stability across depths indicates engine uncertainty, not human
executability. For positions with at most seven pieces, Syzygy WDL/DTZ replaces
heuristic outcome analysis.

Persist only useful records as versioned UTF-8 JSON, separate from source PGN/FEN.
Engine cache identity includes FEN, Stockfish binary/version, NNUE, options, search
limit, root moves, and analyzer version. Preserve the fifty-move counter for
tablebase use. Stream shallow results, cancel obsolete foreground work, and deepen
cached positions incrementally. Add a database only when measured query or volume
needs justify it.

Ordinary CPython coordinates work through a bounded, cancelable queue and initially
one persistent Stockfish child process. Stockfish uses explicitly budgeted native
threads outside the Python GIL. Keep cheap Python board analysis sequential until
profiling demonstrates a need for process workers; do not assume Python threads
accelerate CPU-bound analysis.

User-facing explanation prose lives in the bundled UTF-8 catalog
`namichess/content/explanations.json`. Analysis emits stable explanation IDs,
typed values, facts, and evidence. The catalog contains text templates only, so
copy can change independently without becoming chess policy or executable code.

PGN import parses one or more games, headers, moves, and relevant variations; FEN
import validates a complete position. Users may select any imported ply. App-owned
games and positions remain PGN/FEN, while settings, derived analysis, and metadata
are separate versioned JSON. Imports are never overwritten implicitly.

### Stack

- **Backend:** Python, python-chess, Stockfish, and Pydantic at validated boundaries.
- **Storage:** parsed PGN/FEN chess content plus separate versioned JSON settings,
  analysis, and metadata; no initial database.
- **Local API:** FastAPI with streamed static and verified updates.
- **Frontend:** TypeScript/HTML with arrows, labels, heatmaps, and before/after overlays.
- **Packaging:** optional thin WebView2 shell after the interaction is proven; no C#
  domain layer.

`chess.svg` is for regression artifacts and exports, not the primary interface.

## 5. Build phases

### Phase 0 — Rules and evidence

- Add repository `AGENTS.md` before implementation.
- Define thresholds, perspectives, unsupported cases, and metric semantics.
- Establish golden positions with expected causal explanations.

### Phase 1 — Position lab

- Load FEN/PGN and select a ply.
- Implement timed quiz/reveal, the piece–square graph, `SquareInterest`,
  `PieceProfile`, move deltas, SEE, latent rays, principles, and bilateral threats.
- Render interactive overlays and deterministic regression artifacts.

### Phase 2 — Practical choice

- Add progressive broad-to-deep Stockfish analysis, action heatmaps, targeted probes,
  outcome bands, candidate contrast, and mate verification.
- Add complexity traversal, bottleneck reporting, and line/plan switching.
- Compare practical-best with engine-best.

### Phase 3 — Personal corpus

- Import recent games; extract omissions and continuation failures.
- Produce an explicit review history and personal quiz queue.
- Use selected presets and overrides to control subsequent analysis.

### Phase 4 — Validated expansion

- Add trajectory analysis and local Syzygy only when validated by real use.

## 6. Reference tests

### Latent rays and causal pivot

`r3r1k1/p1pq1ppp/b1pp4/2b5/2P1n3/1P3N1P/P3NPP1/R1BQ1RK1 b - - 0 1`

```text
Bc5 --blocked by f2--> would hit g1
Ba6 --blocked by c4--> would hit e2
Re8 --blocked by e4--> would hit e2
Qd7 --blocked by d6--> would hit d1
```

After `1...d5 2.cxd5`, Stockfish 16 at depth 30 gives `Nxf2` about +6.1 despite
SEE about −0.5. The causal pivot between recaptures is that Qd1 alone defends e2
and can be deflected. Test sacrifices, candidate contrast, reply families, and the
transition from a wide entry to a forcing tail.

### Immediate mate over material

`r5k1/p4p1p/2p2B1Q/8/8/8/P2r1PPP/5bK1 w - - 0 1`

`Qg7#` outranks `Qxd2`; the material layer never recommends the rook capture over
verified mate, and the mating mechanism remains visible.

### Restriction without overclaiming

`N4k1r/pp1b1ppp/2n1p3/3n4/8/2P1QNP1/PP5P/2KR1B1q w - - 3 18`

Expected: `qh1 — 5 legal exits / 0 tactically surviving exits`. Report the queen
as trapped without claiming it is immediately won.

Additional regressions cover a long low-burden mate, a shorter quiet only-move,
a closed position with equivalent improving moves, useful and irrelevant holes,
piece activation and defensive duties, pinned geometric attackers versus legal
recaptures, counter-threats that supersede captures, harmless development-with-tempo
versus real mating threats, motifs with missing prerequisites, en passant, promotion,
stalemate, zugzwang, and more adequate moves than the MultiPV cap. Heatmap tests
keep whole-move value distinct from destination-square attribution.

## 7. Boundaries and risks

- **No LLM board reasoning:** language models may render verified structured facts.
- **No psychological opponent model:** analyze consequences and response burden.
- **No annotation chasing:** `!` and `!!` may be imported, never optimized or treated
  as evidence that a move was understood.
- **No opening-book authority:** principles and motifs must reduce to current
  piece–square facts and survive tactical verification.
- **No blended score:** safety and adequacy gate; executability ranks; engine value
  breaks close ties.
- **Metric validity:** compare tool improvement with external game or puzzle performance.
- **SEE correctness:** unsupported edge cases remain explicit.
- **Cost:** stream static results immediately and reserve deep search for critical positions.
- **Licensing:** python-chess is GPL-3-or-later and Stockfish is GPL-3; decide
  distribution obligations before packaging. Personal use is unaffected.

DecodeChess is the closest commercial product. The differentiator is
practical-choice ranking by configured continuation burden, explained through a
verified piece–square causal model and coupled with omission and continuation
training.
