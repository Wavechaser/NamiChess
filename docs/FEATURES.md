# NamiChess Features

Status: pre-implementation. This document separates the intended product from
work that is merely planned or deliberately out of scope.

## Product aim

NamiChess is a local chess-analysis and training tool for players around
1200–1400 Elo. It should explain what a position permits, what a move changed,
which threats matter, and which reasonable continuation is easiest to execute.
Engine rank is evidence; it is not the product's answer by itself.

## Active direction

These are the product commitments that govern implementation, not claims that
they are implemented today.

- A platform-agnostic analysis backend, with a thin Windows 11-oriented GUI or
  CLI adapter.
- Completed-game and imported-position analysis only. NamiChess does not
  provide live assistance during a human game.
- A piece–square relationship model that keeps geometric control, legal access,
  and tactical ownership distinct. It can expose square interests, piece
  profiles, move deltas, opened rays, mobility, duties, targets, and enabled
  resources.
- Bilateral threat explanations that distinguish contact from a sound,
  executable consequence, and show urgency, response cost, persistence,
  preconditions, and adequate responses.
- Contrastive candidate explanations: engine-best and practical-best may differ;
  tactically unsound moves are rejected before executability is compared.
- Progressive, bounded Stockfish use: broad shallow choice mapping, focused
  probes, deeper verification of critical or unstable claims, and cancelable
  background work. Unsearched moves remain unknown.
- Progressive disclosure in the interface: status, changed facts, urgent
  resources, plan, and choice first; detailed maps, candidates, and engine
  evidence on demand. Board views include complementary square and piece lenses.
- Training around active recall: identify controls, threats, and candidates,
  review verified misses, revisit important continuation nodes, and record
  whether the failure was omission, continuation, trajectory, commission, or an
  execution error.
- PGN and FEN as interchange formats, with original chess content kept separate
  from derived analysis and user metadata.

## Planned, after the foundation

- Position lab: FEN/PGN loading, ply selection, deterministic overlays, and
  timed quiz/reveal.
- Verified static analysis for SEE, latent rays, enablement paths, principles,
  durable plans, and restriction without overclaiming.
- Practical-choice ranking with adequate-move sets, opponent reply families,
  bottlenecks, forcing coverage, payoff distance, line/plan switching, and
  outcome bands.
- Personal corpus review that extracts omission and continuation events into a
  quiz queue.
- Transparent findability personalization after enough independent examples;
  trajectory analysis only when real use justifies it.
- Local Syzygy support for positions with seven or fewer pieces, when validated
  by the implementation and distribution plan.
- A thin WebView2 shell only after the interaction has proved useful; no C# chess
  policy layer is planned.

## Deliberately deferred or excluded

- SQLite is shelved for now. Small app-owned records should use versioned UTF-8
  JSON; PGN/FEN remain standard files. A database becomes an option only after
  measured volume or query needs justify it.
- No remote or external server access, telemetry, accounts, browser navigation,
  distributed workers, or generalized network protocol.
- No authentication, cryptographic protocol, hostile multi-tenant isolation,
  durable job custody, or elaborate security machinery for this single-user,
  non-safety-critical tool.
- No psychological opponent model, annotation optimization, opening-book
  authority, blended safety/executability score, or LLM-generated board facts.
- No live coaching, speculative framework, or feature expansion beyond the
  current phase.

## Success boundary

The first useful release should make a player's next decision clearer, not
produce an encyclopedic engine dump. Every displayed chess claim must come from
structured facts and, where tactical, verification. When no instructionally
meaningful best move exists, the product should say that several moves preserve
the same outcome.
