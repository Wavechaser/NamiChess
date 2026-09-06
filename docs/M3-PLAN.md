# M3 direction and implementation gates

Status: planning only. M2 continues to use Stockfish 18. This document records
the intended extension of M2 evidence, not a commitment to implement every item
in one milestone.

## First step: Stockfish 19

Switch the development engine to Stockfish 19 first in M3. Verify its official
release, executable provenance, license, UCI options, and compatibility with the
existing adapter. Run the complete integration suite and compare representative
analysis behavior before updating setup documentation. Do not change engine
versions during the remaining M2 work or encode version-specific chess policy.

## Reusable foundation

Keep three distinctions throughout the shared output:

1. Effects describe witnessed board changes and explicit piece roles: mover,
   checker, checked king, attacking piece, target, and cleared blockers.
2. Responses describe actual legal choices and the effects they address. A
   response may address more than one effect; a motif name does not constrain
   which defenses are legal.
3. Outcomes state what the retained evidence establishes, with model, coverage,
   unresolved branches, and source identities. Capturability, local material
   gain, mate, and a game-theoretic win are different conclusions.

The M2 slice supplies immediate mechanisms and bounded checking-response capture
witnesses. A queen captured on different squares by different friendly pieces
remains the same target identity. Complete coverage of immediate replies can
establish that a capture is available after every reply; it does not establish
that every capture is profitable or that longer counterplay fails. Existing
target-square exchange evidence keeps its own unsupported cases and does not
silently become a full-position search.

Use these concrete records as the integration boundary. Do not introduce a
generic threat graph executor, plugin motif registry, or speculative outcome
hierarchy before an implemented analysis requires it.

## Candidate M3 work, in dependency order

- Extend legal response coverage beyond checking roots: moving or defending the
  target, removing the attacker, interposition, countercheck, stronger threats,
  and deliberately accepting a loss. Retain overlap between response roles.
- Verify outcomes across longer branches, including checking captures and
  off-square counterplay that the target-square exchange model cannot answer.
  Track universal defensive coverage separately from an existential attacking
  continuation. Partial search must never inherit a completed proof label.
- Explain complementary effects by grouping response branches with the same
  outcome. Preserve representative lines and complete coverage records instead
  of selecting one engine line as a universal explanation.
- Compare mechanisms through legal candidate alternatives. Show when an
  alternative leaves a specific defense available; do not infer that a mechanism
  is globally necessary from one failed alternative. Separate observed
  contribution, demonstrated contrast, and a proved necessity claim.
- Expand bilateral analysis only under explicit per-job budgets. Reuse stable
  piece identities and position-scoped references through captures, promotions,
  transpositions, and previews. Do not invent opponent intent.
- Let CLI and GUI share grouped evidence and selection. CLI chooses concise
  prose; GUI highlights explicit roles and reveals branch choices. Neither
  adapter reconstructs chess policy from explanation text.

## Acceptance gates

Each implemented slice needs named legal fixtures and color mirrors, independent
adversarial review, and bounded/cancelable execution. Include defenses that
invalidate the attractive motif explanation, terminal outcomes, unsupported
exchange positions, incomplete budgets, and sibling-branch reference checks.
Measure latency and coverage before widening search or introducing caches.
Update FEATURES, ARCHITECTURE, and COMMANDLINE as behavior becomes implemented;
keep this plan prospective until its work is accepted.
