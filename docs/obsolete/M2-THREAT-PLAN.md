# M2 complex checks and bounded threats

Historical implementation plan: completed and accepted on 2026-09-06. Current
contracts belong to [ARCHITECTURE](../ARCHITECTURE.md),
[COMMANDLINE](../COMMANDLINE.md), and [FEATURES](../FEATURES.md). The prospective
[M3 plan](../M3-PLAN.md) remains active.

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

## Acceptance record

Implemented as separate corrective, refactor, backend, application, and CLI
commits. GPT-5.6 builders handled implementation; independent agents reviewed
the fixes, structural mechanisms, response verifier, shared selection, and final
presentation. Root coordination retained scope and commit boundaries.

The shared mechanism layer distinguishes actual checkers from the mover,
connects multiple cleared blockers, recognizes single/double and discovered
checks, and groups geometric forks and complementary attacks. Checking-threat
evidence preserves the same target across different replies and captures.
Complete nonempty reply coverage establishes immediate capture availability,
not a forced material gain. Shared selections carry request-scoped references
and response groups; CLI output leads with the selected conclusion and keeps
all retained branches and exchange limits in details.

Adversarial findings were resolved before acceptance: duplicated opened-line
provenance became one shared helper in a separate refactor commit; direct
checker roles gained their movement/castling sources; terminal draws stopped
producing fictional replies; root facts were reused; en passant checker removal
and target capture now share one actual-capture-square calculation. Generic
king-response wording was replaced with counted groups to avoid implying
universality for a subset. Test descriptions distinguish structured pin facts
from facts selected for the compact attention budget.

Verification: **460 passed, 10 skipped** in the ordinary suite; **470 passed**
with the configured Stockfish 18 executable. Focused threat regressions cover
all acceptance cases above, including mirrored examples, a defense escaping an
immediate capture, pinned illegal captures, a loss-making exchange, en passant
and promotion identities, shared targets, deadlines, and cancellation.

A fresh reviewer ran real Stockfish 18 CLI probes on all three supplied examples:
the double-check queen fork retained capture availability after 4/4 replies;
the discovered-check combination after 6/6, with five king replies allowing
`Bxh4` and `Qc4` allowing `Qxc4+`; the single-check rook fork after 6/6. No
material-win claim replaced those bounded conclusions. Final review and diff
checks passed. Stockfish 18 remains the M2 engine; switching to 19 is the first
planned M3 step.
