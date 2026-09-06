# M2 ablation study

Study date: 2026-09-06. Baseline: `985d14e`. This is a measured review of
completed M2, not an implementation plan or a change to current contracts.
Production code and tests were left unchanged. Two independent implementation
investigators used process-local substitutions; a separate reviewer challenged
the recommendations.

The five recommended reductions have since been implemented. See the
[completed follow-up and acceptance record](obsolete/M2-EXPLANATION-PLAN.md).
The measurements below describe the study baseline, not the resulting code.

## Findings and recommended order

M2 has several worthwhile consolidation opportunities. The evidence favors
removing repeated work and narrowing internal plumbing. It does not justify
removing its local analysis features.

| Priority | Change | Evidence | Constraint |
| --- | --- | --- | --- |
| 1 | Pass the existing explanation catalog through board and preview rendering | 100 board/preview renders loaded and validated the catalog 600/700 times; explicit reuse reduced both to zero with identical text | Preserve standalone rendering with at most one fallback load per render; no global cache |
| 2 | Compute focused local assessments once per request | Five candidate probes produced six identical assessment computations; reuse preserved the final result exactly | Keep public position/evidence validation and request ownership |
| 3 | Reuse endpoint facts within each session view or preview | 17 positions required 49 fact computations; per-view reuse required 33 and preserved results | Keep the public delta API independently validated; no persistent cache needed |
| 4 | Combine the two PGN preparation walks | One full-source masking pass instead of two; 16 adversarial cases and the ordinary suite retained behavior | Retain original spelling, source alignment, ordering, and strict validation |
| 5 | Small, directly evidenced cleanup | Duplicate exposure rendering and an unused assessment argument | Avoid a general rendering framework or unrelated refactors |

### Rendering and request assembly

In [cli.py](../namichess/interfaces/cli.py), board rendering does not receive the
composition-owned catalog. Preview rendering accepts one but does not forward it
to its move-delta renderer. The fallback loads and validates the JSON catalog
for each text lookup, including headings for empty relationship groups.

For 100 warm local renders, catalog reuse reduced board time from about 69 ms
to 1.1 ms and preview time from 76 ms to 2.0 ms. These are small rendering
microbenchmarks: the absolute saving is below 1 ms per render, not an equivalent
improvement in overall analysis latency. Passing the dependency consistently
is also simpler than hidden repeated filesystem reads.

In [analysis.py](../namichess/application/analysis.py), each successful engine
probe partial and the final result rebuild assessments from the same immutable
focused local result. A five-root request computed them six times. Once-per-
request reuse reduced measured assessment work from 6.149 ms to 0.980 ms, with
an exactly equal final `AnalysisResult`. Whole-request time fell from 145.45 ms
to 140.31 ms in one run; that timing is directional, not a stable benchmark.
Compute the fields once after local exploration and reuse the value; a memoization
framework is unnecessary. An implementation must also preserve assessment
presence in intermediate `RUNNING` partials; those are externally observable,
and final-result equality alone does not verify the whole update sequence.

Some early engine-failure returns retain local evidence but omit typed
assessments. This deserves an explicit consistency decision if assembly changes.
Existing tests do not establish that omission as a bug, so it should not be
silently included in a behavior-preserving cleanup.

### Static continuity assembly

[Session views](../namichess/application/session.py) and
[previews](../namichess/application/preview.py) compute current facts, then
[move_delta](../namichess/analysis/static.py) computes both endpoint facts again.
A 16-ply Ruy Lopez traversal, including the starting position, produced these
results:

| Variant | Fact computations | Preview median | Session-view median |
| --- | ---: | ---: | ---: |
| Current | 49 | 60.51 ms | 54.38 ms |
| Reuse within each view | 33 | 46.14 ms | 41.30 ms |
| Cache across views | 17 | 34.43 ms | 28.34 ms |

Per-view reuse preserved exact preview dataclasses and session results; medians
use seven runs recorded in command output. The retained `results.json` contains
only the final representative run, not those seven timing samples. Its roughly
24% improvement needs only an internal delta assembly
path that can reuse facts already computed for that endpoint. The public API
must continue to validate independently supplied contexts. The 17-call variant
requires state across navigation, eviction, and cache lifetime decisions. It is
an experimental upper bound, not the recommended simplification.

### PGN preparation

[imports.py](../namichess/application/imports.py) masks comments/headers and
walks move tokens separately for lexer-compatible spelling and original-token
tracking. A single preparation function could return both projected text and
original moves. Keep per-game strict validation separate.

The combined variant preserved all 16 acceptance, rejection, game, and error
signatures. The ordinary suite passed both normally and with the substitution:
**303 passed, 10 skipped** in each case. For 300 games containing 1,500 plies and
16,198 characters, seven alternating runs gave medians of 243.75 ms versus
239.64 ms. Ranges overlapped substantially; there is no reliable speed claim.
The benefit is one owner for the same preparatory scan.

Two destructive controls show why further deletion would change the product:

- Removing original-token tracking changed canonical `Bxc4` into pawn `bxc4`
  in a position where both exist, and accepted ambiguous `bXC4`. Three other
  outcome differences were diagnostic differences, not additional chess defects.
- Removing strict validation accepted six invalid inputs: false check, false
  mate, a missing result, garbage movetext, an unclosed comment, and overspecified
  PGN coordinate notation.

The collision fixture was `7k/8/8/8/2n5/1P1B4/8/K7 w - - 0 1`.
Case-insensitive shorthand remains a legal-move resolution feature, not repair
of malformed PGN. Combined preparation must preserve variations, multiple-game
ordering, and original source offsets/lengths.

## Feature ablations

Fourteen real local-exploration cases covered immediate mate, deeper cooperative
mate observations, sacrifices, quiet material exposure, beneficial captures,
captures of another piece, shared defensive duties, and counterchecks. Relevant
cases were mirrored by color. The clock was frozen to disable deadlines and
each case had a 10,000-node limit. Times below sum five-run per-case medians;
they measure this curated corpus, not playing strength or normal timed budgets.

| Variant | Total nodes | Aggregate time | Evidence lost |
| --- | ---: | ---: | --- |
| Depth 4, root and reply SEE | 1,661 | 2,065.8 ms | Baseline |
| Depth 2, both SEE paths | 659 (-60.3%) | 1,170.8 ms (-43.3%) | Both deeper mate observations; continuations also shorten |
| No root SEE | 1,651 (-0.6%) | 2,060.2 ms (-0.3%) | Root capture/sacrifice exchange values and evidence |
| No reply SEE | 1,605 (-3.4%) | 1,867.3 ms (-9.6%) | Several quiet-move and reply material-exposure witnesses |
| Neither SEE path | 1,595 (-4.0%) | 1,839.9 ms (-10.9%) | Both classes of material evidence |

At depth 2 the two deeper mate cases changed from `observed_failure` to
`no_refutation_found`. Those lost lines were observations, not proofs of forced
mate. Immediate-mate, coverage, overload, and material assessment outputs were
otherwise unchanged in this sample, apart from the expected shorter lines.

Keep depth 4 and both exchange paths. A shallower explicit survey mode could be
considered if measured interactive latency warrants it, after a broader corpus;
it is not a transparent simplification. The exchange paths answer different
questions even when a top-level assessment label stays unchanged.

One attempted local move-ordering optimization also failed the ablation test:
memoizing move classifications reduced calls from 22,081 to 11,141 and preserved
exact exploration results, but increased aggregate median time from 2,114.6 ms
to 2,524.8 ms (19.4%). Fewer calls alone did not offset Python bookkeeping.

## Data and code that look redundant

The [shared serializer](../namichess/interfaces/serialization.py) exports every
dataclass field. A field with no named internal reader is still part of schema
version 2; deleting it is not automatically a private cleanup.

| Candidate | Observation | Judgment |
| --- | --- | --- |
| `SessionView.pieces` | Duplicates `facts.pieces`; 5,807 bytes in a 79,532-byte compact JSON snapshot (7.30%) | Consider at an explicit schema migration; source consumers can use facts |
| `board_rows` | 195 bytes in the same snapshot (0.25%) | Keep convenient display data; negligible payoff |
| `MoveDelta.before_pieces` / `after_pieces` | 11,627 of 21,292 bytes for starting-position `e4`; 1,843 of 5,989 bytes for a sparse ray fixture | Keep: they resolve piece references and historical/current types, including promotions |
| `AnalysisResult.assessment_pieces` | 202 of 148,392 bytes in a quiet-exposure result (0.14%) | Keep standalone result rendering self-contained |
| `LocalLine.branch_scope`, `LocalRootEvidence.first_reply` | No named runtime consumers found | Removal needs a serialized-contract decision |
| `material_exposed_exits` | Deduplicated projection of material exposures, no named runtime reader | Same schema caveat |

Removing delta placement arrays left referenced piece identities without their
placement registry. Meaningful payload reduction here would require an explicit
registry/schema redesign, not deleting seemingly duplicate fields. That is not
justified by this study alone.

Smaller direct-inspection candidates:

- Remove the unused `placements` argument from `_witnessed_duty_conflicts` in
  [assessments.py](../namichess/analysis/assessments.py); it is immediately deleted.
- Extract the repeated CLI material-exposure text block into a small helper.
- Consider one analysis-owned material-value policy for the repeated 1/3/3/5/9
  tables in evidence, exchange, and assessments. This is a consistency benefit,
  not a measured speed or major line-count reduction. Do not merge the algorithms
  or introduce a generic mixed-type lookup framework.

Retain independent assessor input guards, distinct geometric/legal/tactical
facts, and the distinction between a local line's exit classification and its
search termination reason.

## Interpretation and verification limits

The repeated-work findings share an upstream cause: already-computed immutable
values are not consistently carried through application and rendering assembly.
Small explicit value reuse addresses this without adding caches, services, or
new public abstractions. PGN spelling and original-token preparation similarly
belong to one preparatory operation, while strict validation has a separate job.

These experiments used Python 3.13.14 on the local Windows development machine.
Local-analysis producers were real; engine responses in assembly/payload studies
were deterministic substitutes. Stockfish integration was not rerun for this
study. Equality checks support the specified fixtures and substitutions; they
do not prove arbitrary future implementations equivalent. Each actual refactor
still needs focused regressions and the ordinary suite.

Process-local experiment scripts and raw JSON were retained as temporary local
study artifacts, outside the repository, under `%TEMP%`:

- `namichess-ablation-parser-5d2346714e8144ecb714360cc4b7d3a4`
  (`parser_study.py`, `parser_results.json`; baseline/combined full-suite runs).
- `467b2c55-08ff-49c4-aecf-6c45b9697e13`
  (`study.py`, `results.json`; static facts, catalog, payload).
- `namichess-ablation-18b5f07d-1f39-4459-9967-60fa657c3243`
  (`scripts/`, `results/`; local search, move ordering, request assembly).

Temporary artifacts are not a durable benchmark suite and may be removed by
normal temporary-file cleanup. This document records the workloads, controls,
results, and limits needed to interpret the recommendations.
