# M2 complex checks and bounded threats

## Scope and sequence

Keep Stockfish 18 throughout M2. Implement the following as independently
reviewable steps, with focused regressions and an independent adversarial review
before acceptance:

1. Generalize opened-line grouping to occupancy changes, including en passant
   clearing two blockers. Retain raw facts and exact causal references.
2. Carry actual checkers and the checked king through immediate and continuation
   evidence. Keep the mover a separate role; GUI consumers must not infer roles
   from a generic collection of involved pieces.
3. Represent complex checks and structural forks as witnessed effects, separate
   from verified consequences. Group related effects without deleting their
   sources or treating geometric attacks as winning captures.
4. Connect checking threats to bounded legal-response and capture-outcome
   evidence. Account for every legal response before claiming a common local
   outcome. Unsupported, terminal, interrupted, or unexamined branches cannot
   establish a forced material result. Reuse the existing local budget and
   legality-aware exchange model; its limits remain explicit.
5. Expose shared effect/response/outcome associations and concise CLI accounts,
   prioritizing established outcomes with supporting mechanisms. Keep detailed
   branches, roles, model limits, and provenance available to future GUI views.
6. Record the reusable architecture and deferred work in an active M3 plan;
   update owning contracts, run the full Stockfish-enabled suite, and archive
   this implementation plan after acceptance.

## Architectural constraints

The M2 slice describes immediate effects and shallow response coverage. It does
not prove a mechanism necessary, explain engine preference, or perform general
bilateral threat search. A continuation example is never universal evidence.
Use concrete immutable data for implemented effects and outcomes, not a generic
graph engine or speculative motif registry. Future M3 analysis may extend
response depth and outcome types without changing the distinction between
observed structure, legal responses, and model-qualified conclusions.

## Acceptance examples

- `8/2k5/8/8/8/2B5/3P3q/K1Q5 w - - 0 1`, `Be5+`: queen c1 and
  bishop e5 check; bishop forks king c7 and queen h2.
- `8/2k5/8/8/7q/2B5/3P4/K1Q5 w - - 0 1`, `Bf6+`: discovered
  queen check plus bishop attack on h4. King responses allow `Bxh4`; `Qc4`
  allows `Qxc4+`. Do not claim every response is a king move or one capture
  sequence proves the result for all responses.
- `8/2k5/8/8/8/2B5/3P3r/K7 w - - 0 1`, `Be5+`: single bishop
  check and king/rook fork, with no discovery.
- Mirror these positions by color. Include escapable forks, pinned attackers,
  loss-making exchanges, counterchecks, terminal draws, node/time limits,
  cancellation, and source-reference integrity.
