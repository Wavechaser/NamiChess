# M2 consolidation and explanation follow-up

Implement the measured reductions before changing explanation behavior. Keep
each reduction and each user-visible improvement independently reviewable.
No analysis capability or existing serialized field is removed.

## Commit sequence and acceptance

1. Thread the existing explanation catalog through renderers. Verify injected
   text and at most one fallback load per standalone render.
2. Reuse focused assessments within one request. Verify partial and final values
   and unchanged cancellation/failure behavior.
3. Reuse endpoint facts within one session view/preview. Preserve independently
   validated delta entry points; verify equality and computation counts.
4. Combine PGN preparation scans. Preserve original token spelling, structural
   validation, source alignment, variations, and ambiguity rejection.
5. Remove the unused assessment argument and duplicate exposure formatting.
   Preserve rendered output and assessment results.
6. Add shared structured consequence grouping, selection, and source references.
   Retain raw facts and distinguish geometry from legally verified tactics.
   Document the additive shared schema revision before interface adoption.
7. Render short connected move accounts. Merge descriptions of the same event;
   retain detailed raw relationships through `changes`.
8. Automatically surface a bounded attention selection after navigation/moves,
   including imports without a previous move. Never infer a winning capture from
   geometric attack or missing protection.
9. Describe candidate-root structural differences before continuation evidence.
   Include meaningful unchanged relationships when alternatives change them.
   Do not attribute engine preferences to unverified structural observations.
10. Collapse repeated progress lines into truthful completion counts/depths.
    Preserve cancellation, failure, interruption, and partially typed commands.
11. Remove repeated score-perspective parentheses from compact output. Keep the
    documented White-positive numerical convention and mirror-test signs.

## Boundaries

- Analysis owns derived chess consequences; application combines independent
  structural and tactical evidence and produces shared selections.
- Shared output carries identities, position-scoped squares, and evidence
  associations needed for future GUI highlights. CLI owns prose and length.
- Selection may prioritize actionable observed changes, but priority is not a
  tactical safety verdict. No new search or unbounded automatic probing.
- Quiet moves receive structural explanations. Captures, castling, en passant,
  promotions, moving subjects, pinned geometric defenders, and color mirrors
  must not create misleading causal wording.
- Existing raw delta and line evidence remain available for inspection.

## Verification and review

Builders run focused regressions. Run the ordinary suite before each mergeable
checkpoint; independently review changes for false chess claims, stale/cross-
candidate references, output flooding, unnecessary machinery, and scope drift.
Run the real Stockfish integration workflow before final acceptance. If repeated
defects share an upstream cause, repair that cause in a separate coherent commit.
Completed work updates the owning architecture, feature, and CLI documents;
archive this plan only after acceptance.
