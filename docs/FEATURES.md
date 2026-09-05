# NamiChess Features

Status: M1 implementation. Strict PGN/FEN import and interactive navigation are
implemented; static and engine-backed analysis checkpoints remain in progress.

## First milestone

M1 is an interactive CLI position lab. It imports FEN and PGN, navigates games
and variations, accepts composed standard-chess positions with unusual material,
shows shared board facts and move deltas, and compares analyzed candidates with
bounded Stockfish evidence. Text and versioned JSON render the same application
views so a later GUI can add arrows and highlights without duplicating chess
policy. Detailed gates and defaults live in [M1-PLAN.md](M1-PLAN.md).

M1 includes narrow threat reporting for checks, immediate mates, captures, legal
replies, and consequences in analyzed lines. Comprehensive threat assessment,
practical-best ranking, active recall, training, GUI overlays, SEE, persistence,
and export are deferred. Syzygy integration and redistribution are excluded.

## Product aim

NamiChess is a local, rating-agnostic chess-analysis and training tool. It
explains what a position permits, what a move changed, which threats matter, and
which sufficiently strong continuation is easiest to understand and keep
playing. Context and executable decisions matter more than reproducing the top
engine line.

## Position understanding

- Show geometric control, legal access, and tactical ownership separately, with
  the identities of relevant attackers and defenders.
- Identify important squares: contested squares, tactical pivots, holes,
  outposts, entry squares, routes, blockades, and squares that enable breaks or
  further activity.
- Explain pieces through mobility, useful destinations, duties, targets,
  attackers, defenders, pins, overloads, restrictions, and prospective roles.
- Describe what each move changes: gained or lost control, opened or closed
  lines, newly loose or pinned pieces, changed mobility, threats, pawn breaks,
  and king access.
- Assess both sides' threats by soundness, urgency, response cost, persistence,
  preconditions, and adequate responses. Distinguish real threats from harmless
  contact, useful development with tempo, and unsound attempts.
- Derive principles and named motifs from the current board. Opening-book names,
  familiar shapes, and annotation glyphs are not explanations by themselves.

## Practical decisions

- Compare safe, adequate candidates before ranking them for a human. A steadfast
  move with many reasonable continuations may be preferred to a slightly stronger
  line that requires opaque exact play.
- Present engine-best and practical-best separately when they differ, with the
  earliest meaningful contrast and the evidence for it.
- Treat forcing sequences as easier when their decisions are legible, regardless
  of mate distance. Switch from line mode to plans, triggers, and durable routes
  when future branches become opaque.
- Survey candidate choices broadly, then verify critical, unstable, sacrificial,
  or counterintuitive claims more deeply. Shallow/deep agreement is evidence;
  disagreement triggers further checking.
- Show square and move heatmaps without pretending that a whole-position engine
  change belongs to the destination square alone.
- Disclose progressively: status, changed facts, urgent resources, plan, and
  choice first; maps, alternatives, continuations, and engine evidence on demand.

## Analysis settings

- Provide `Foundation`, `Club`, and `Advanced` presets without assigning rating
  ranges or learning a player profile.
- Let users independently tune search effort (`quick`, `normal`, `thorough`),
  candidate breadth (`narrow`, `balanced`, `wide`), continuation burden
  (`steadfast`, `balanced`, `exacting`), explanation layers, and resource use
  (`light`, `balanced`, `maximum`).
- A changed preset becomes `Custom` based on that preset and can be restored to
  its defaults. Ordinary settings use meaningful choices rather than raw engine
  depth, MultiPV, hash, or thread counts.
- Presets change breadth, effort, presentation, and practical ranking—not chess
  truth or the requirement that tactical claims be verified.
- Disabled advanced topics are normally hidden from presentation, not removed
  from foundational computation. If one becomes decisive, explain it plainly.
- Keep user-facing explanation text in a separate editable content file. Analysis
  supplies structured facts and evidence; changing prose does not change chess
  policy or require editing Python code.

## Board appearance

- Use the bundled MPChess SVG set by default.
- Let users import and select a custom SVG piece set locally.
- Require every theme to provide the same twelve white/black piece assets. Built-in
  and custom themes use the same board renderer and differ only in resolved asset
  location.
- Keep custom themes in app-owned user data and allow restoring the bundled
  default without affecting games or analysis.

## Chess files and saved data

- Import and parse one or more games from PGN, including headers, moves, and
  variations needed to navigate positions.
- Import and validate FEN positions, preserving all fields needed to reconstruct
  the position correctly.
- Navigate imported games by ply and analyze any selected position.
- Save app-owned games as PGN and positions as FEN. Keep original imports,
  settings, derived analysis, and user metadata separate.
- Never overwrite an imported source implicitly. Save and export to an explicit
  destination.
- Use versioned local JSON for settings, analysis, and small app-owned metadata.
  SQLite remains deferred until measured data or query needs justify it.

## Training

- Training begins after M1.
- Use active recall: ask for controls, threats, and candidates before revealing
  verified misses.
- Revisit important continuation nodes and distinguish omission, continuation,
  trajectory, commission, and execution errors.
- Preserve imported `!` and `!!` annotations but do not optimize for them. Explain
  criticality, surprise, sacrifice, and continuation difficulty as separate facts.
- Build personal review queues from saved games and explicit responses without an
  inferred multi-game skill model.

## Boundaries

- The runtime is local-only: no remote server, external service, telemetry,
  account, or browser navigation.
- No psychological opponent model, opening-book authority, blended
  safety/executability score, or LLM-generated board facts.
- The initial frontend may be Windows 11-specific, while analysis and application
  behavior remain platform-agnostic.
- SQLite, distributed workers, plugin systems, and generalized protocols remain
  deferred until a demonstrated need exists.

## Success boundary

The first useful release makes the next decision clearer rather than producing
an encyclopedic engine dump. Every displayed chess claim comes from structured
facts and, where tactical, verification. When several moves preserve the same
outcome, the product says so.
