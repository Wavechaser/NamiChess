# M1 Combined Invariant Review

**Historical status:** Accepted and retired on 2026-09-06
**Implementation commit:** `ae23b4f`
**Active owners:** CLI/API behavior is in `../COMMANDLINE.md`; durable invariants
are in `../ARCHITECTURE.md`; current/planned behavior is in `../FEATURES.md`.

**Scope:** M1-01 through M1-06 after implementation and checkpoint verification

The user added this combined review as a final milestone acceptance gate after
the individual checkpoint implementations were verified. The audit asks whether
the assembled system preserves its contracts across boundaries and sequences,
especially where locally correct components can fail in combination. It does not
expand M1 product scope.

## Ownership table

| ID | Concern | Authority | Consumer boundary | Invariant under review | Direct evidence |
|---|---|---|---|---|---|
| INPUT-1 | FEN/PGN validity | `domain.validation`, `application.imports` | `Session.load_*` | Invalid or noncanonical input cannot partly replace a valid session. | `test_rejects_incomplete_or_normalized_fen`; `test_rejects_noncanonical_san_in_mainline_and_variations`; `test_failed_load_preserves_current_session` |
| IDENT-1 | Piece and square identity | `domain.models`, `domain.position` | Static facts and evidence | Identity follows legal history, castling, and promotion; current coordinates are separate from origin identity. | `test_piece_identity_survives_promotion_and_castling`; `test_unusual_material_keeps_every_identity_distinct` |
| STATIC-1 | Static chess facts | `analysis.static` | `SessionView.facts`, inspection, JSON | Geometric attack, actual-turn legal access, pins, check, and move changes remain distinct typed facts. | `test_geometric_attacks_include_pinned_piece_but_legal_access_uses_actual_turn`; `test_shared_view_exposes_position_facts_and_previous_move_delta` |
| OWN-1 | Engine ownership | `analysis.engine.StockfishAdapter` | `AnalysisController` | Exactly one adapter owns each child; cancel/finish/close settle protocol work, request quit or terminate, and wait a bounded time for return code. | engine handshake, timeout, failure, and overlap tests; final process check |
| STATE-1 | Request lifecycle | `application.analysis.AnalysisController` | Shared `AnalysisResult` | Request mutation is owner-scoped; one running/one pending; close is absorbing and shared. | supersession, cancel/replacement, and close-race tests |
| EVID-1 | Search and evidence | `application.analysis.AnalysisController` | Shared `AnalysisResult` | One deadline, bounded candidate union, atomic score/PV evidence, explicit coverage, stable identity independent of rank. | candidate, deadline, score, and legal-replay tests |
| VIEW-1 | Session revision | `application.session.Session` | CLI and future GUI | Every changed position advances revision; only a matching-revision result enters the shared view. | `test_analysis_view_filters_results_from_another_revision`; stale-progress test |
| COMP-1 | Comparison legality | `Session.resolve_moves`, `Session.request_analysis` | `compare` | Two distinct legal SAN/UCI moves resolve without moving the selected node. | comparison tests |
| PROSE-1 | Explanation meaning | Typed `Explanation`/`Evidence` plus content JSON | Text renderer and JSON | Templates contain prose only; typed references and evidence carry meaning. | catalog and alternative-line tests |
| UI-1 | Presentation | `interfaces.cli`, `interfaces.explanations` | stdout/stderr and JSON | CLI formats shared facts without selecting candidates/recomputing chess; text and JSON share a result. | text/JSON/detail/prompt tests |
| ROOT-1 | Construction/local authority | `composition.py`, `interfaces.files` | Native process | Composition alone constructs infrastructure; local paths never become runtime network authority. | native missing-engine, packaging, and file-preservation checks |

## State-transition table

### Application controller and session

| From | Event | Required next state | Retained/discarded state | Evidence |
|---|---|---|---|---|
| No session | Successful `fen`/`load` | Selected revision 1; analysis submitted | Validated immutable document retained | CLI transcript and import tests |
| Loaded revision N | Failed `fen`/`load` | Remain on revision N | Existing document, node, facts, and result remain; failed input discarded | `test_failed_load_preserves_current_session`; `test_invalid_large_counter_keeps_session_and_cli_running` |
| Selected revision N | Navigation/trial move changes node | Revision N+1; prior request superseded; new request submitted | Imported tree retained; trial child is in memory | `test_navigation_variations_and_trial_move_reuse`; native rapid navigation |
| Idle/completed/failed | `analyze` | Running new request on current revision | Static view retained; latest analysis replaced | `test_failure_requires_an_explicit_retry_and_completed_cancel_is_noop` |
| Running request A | Submit request B | A canceled and settled; B runs after settlement | At most B pending; A cannot publish late progress/result | `test_rapid_supersession_cancels_running_search_and_rejects_late_progress`; real rapid supersession |
| Running request | `cancel` | Canceled after engine settlement | Completed probe evidence may remain; no unbounded cancel task | `test_cancel_between_probes_preserves_completed_probe_evidence`; `test_awaited_cancel_cannot_cancel_the_next_position_request` |
| Any controller state | first `close` | Closing, then closed | Closing is absorbing; one shared close task owns cleanup | `test_close_is_absorbing_idempotent_and_shared_while_cleanup_runs` |
| Closing/closed | submit | Rejected; state unchanged | No request or engine operation begins | same absorbing-close regression |
| Closing | concurrent `close` | Same shared close completion | Cleanup runs once and every caller observes completion | same absorbing-close regression |
| Preparing | Supersede/cancel/close | Startup/configuration settled or owned child terminated | No orphan child or later search from canceled prepare | `test_supersession_during_prepare_cancels_before_search_and_close_waits`; `test_canceling_prepare_terminates_a_child_stalled_in_configuration` |
| Searching | Deadline | Completed with interrupted coverage or failed bounded settlement | No probe starts after deadline | `test_outer_deadline_cancels_a_stalled_individual_search` |
| Searching | Stream/protocol failure | Failed; static navigation usable | Broken owned engine discarded; explicit retry may restart | `test_stream_crash_reports_failure_and_next_request_restarts_engine`; native missing-engine recovery |
| Any loaded position over 32 pieces | Automatic/explicit analysis | Unsupported without engine prepare | Static facts, inspection, and JSON remain available | `test_over_32_piece_snapshot_keeps_static_facts_and_explains_unsupported_analysis` |
| Running CLI | Redirected EOF | Await latest result, print final text, close engine, return 0 | No prompt or owned process retained | `test_redirected_input_waits_for_latest_analysis_and_closes`; native redirected run |
| Running CLI | `quit` | Cancel promptly, close engine, return 0 | No full-search wait or child retained | native quit/process cleanup checks |

### Engine adapter

| From | Event | Required next state | Ownership/settlement invariant | Evidence |
|---|---|---|---|---|
| Unstarted | `prepare` | Starting/opening | One outer five-second deadline begins; no child is yet assumed owned. | startup timeout tests |
| Starting/opening | opener returns transport/protocol | Configuring | Transport ownership transfers immediately to adapter. | `test_configuration_failure_reaps_owned_child` |
| Configuring | ready succeeds | Ready | Remaining startup deadline is used; opener plus configure never receive two full budgets. | `test_startup_timeout_is_one_aggregate_deadline_and_reaps_configured_child` |
| Starting/configuring | cancel/timeout/failure | Unstarted/failed | Owned transport is terminated and a bounded wait observes its return code. | startup cancellation/failure and cleanup regressions |
| Ready | `analyze` | Handshaking | One active request task owns the command; overlaps reject before a second command. | `test_overlap_is_rejected_before_a_second_engine_command_starts` |
| Handshaking | cancel/finish | Stopping then Ready/failed | Protocol-owned ready future is shielded; request task is joined, never detached. | ready-handshake cancel/finish tests |
| Handshaking | handshake succeeds | Searching | Active analysis handle is installed before streamed evidence is accepted. | fake and real adapter tests |
| Searching | progress | Searching | Score, bound, PV, depth, nodes, and elapsed metadata come from one atomic engine snapshot. | bound/metadata regressions |
| Searching | finish | Stopping then Ready/completed | Stop drains final evidence; budget exhaustion does not discard a completed final snapshot. | finish-retains-evidence tests |
| Searching/stopping | stop timeout | Failed/unstarted | Timeout is failure even if lower protocol reports cancellation; owned child is terminated with bounded return-code wait. | `test_finish_stop_timeout_is_failed_even_when_analysis_settles_as_canceled` |
| Ready/failed | adapter `close` requested by controller | Unstarted/detached | Adapter tears down and detaches its owned transport; the owning controller enforces the absorbing user lifecycle. | adapter close/process tests plus absorbing controller-close regression |

## Defect-to-invariant-to-test map

The stable IDs in the ownership table are authoritative. Older descriptive
phrases in the mapping below resolve as follows: identity/current placement →
IDENT-1; geometry/legal access → STATIC-1; engine settlement/owned child →
OWN-1; cancellation/replacement/revision → STATE-1 or VIEW-1; evidence legality,
scope, ranking, or coverage → EVID-1; explanation meaning → PROSE-1; rendering,
input, and feedback → UI-1; construction/paths → ROOT-1.

| Discovered integration defect | Violated invariant | Resolution | Regression or verification |
|---|---|---|---|
| An over-32-piece position could reach an unsafe engine probe. | OWN-1, EVID-1 | Application and adapter reject before engine launch while preserving static facts. | `test_over_capacity_position_is_unsupported_without_launching_engine`; consumer over-32 snapshot test |
| Equal time allocation at the deadline discarded final evidence returned during stop. | EVID-1 | Finish/drain retains a valid final snapshot produced at budget settlement. | `test_finish_during_analysis_ready_handshake_stops_and_returns_evidence`; controller deadline regressions |
| Finish during the ready handshake could leave a detached task. | OWN-1 | Shield and join the request task through handshake settlement. | `test_finish_during_analysis_ready_handshake_stops_and_returns_evidence` |
| Stop timeout was reported canceled although settlement failed. | OWN-1 | Stop timeout maps to failed and tears down the owned child. | `test_finish_stop_timeout_is_failed_even_when_analysis_settles_as_canceled` |
| Reused python-chess info dictionaries retained stale bound flags. | EVID-1 | Parse score, bound, and PV from each atomic info snapshot; a later exact score clears an earlier bound. | `test_later_exact_score_clears_an_earlier_bound_snapshot` |
| Metadata-only updates could attach new depth/nodes/time to an older score. | EVID-1 | Publish scored evidence only from a snapshot that contains the score/PV pair. | `test_metadata_only_updates_do_not_relabel_or_create_scored_evidence` |
| Survey evidence lacked SAN and probe evidence lacked elapsed time. | EVID-1, UI-1 | Evidence carries parallel UCI/SAN lines and elapsed metadata; details renders elapsed or absent. | survey-SAN application tests; `test_details_render_recapture_promotion_and_material_change` |
| En-passant capture square, promotion material sign, and recapture detection were wrong or implicit. | IDENT-1, EVID-1 | Legal deltas provide actual capture square/current types; material stays White-perspective; recapture compares prior destination. | `test_line_material_is_white_perspective_for_en_passant_and_promotion`; static en-passant/promotion tests |
| A candidate allowing immediate opponent mate retained a contradictory exact rank. | EVID-1 | Enumerated legal mate replies make the candidate provisional and remove certified rank. | `test_static_opponent_mate_refutes_a_contradictory_exact_top_score` |
| Current static evidence IDs were not request/revision/position scoped. | EVID-1, VIEW-1 | Every evidence/explanation ID uses the request/revision/position scope. | `test_current_check_references_the_replayed_checker_identity_and_scoped_evidence`; mate-alternative scoped-ID test |
| Inspection labeled moved/promoted pieces by origin square/original type. | Presentation must resolve identity to current placement. | Renderer maps `PieceId` through current `PositionFacts.pieces`. | `test_cli_inspect_uses_current_square_for_a_moved_pinned_piece`; `test_cli_inspect_uses_current_promoted_piece_type` |
| Pinned geometric attacker could be mistaken for legal access. | Geometry and legality remain separate. | Inspection labels and filters independent typed collections and displays the relevant pin. | `test_cli_inspect_distinguishes_geometric_attack_from_legal_access` |
| `cancel` used an unbounded fire-and-forget task that could cancel the next request. | Cancellation settles before replacement. | Async command runner awaits controller cancellation. | `test_awaited_cancel_cannot_cancel_the_next_position_request` |
| CLI assembled stale filtering itself. | Application owns shared correctness for all interfaces. | `Session.analysis_view(controller)` and `request_analysis()` assemble the revision-safe shared view. | `test_analysis_view_filters_results_from_another_revision` |
| Async output could overwrite partially typed input. | Progress must preserve input usability and remain bounded. | Reporter uses prompt-toolkit terminal handoff at 250 ms intervals. | `test_progress_output_preserves_partially_typed_interactive_command`; native typed-buffer run |
| Candidate rows joined every explanation and became an engine dump. | Summary is concise; details owns expansion. | Each row chooses one priority explanation. | `test_text_and_json_share_current_analysis_candidate` |
| Global facts from different candidate roots looked contradictory. | Candidate-local claims retain their root context. | Candidate-associated facts are prefixed with root SAN. | `test_text_and_json_share_current_analysis_candidate`; native candidate rendering review |
| Current mate-in-one prose omitted the actual moves. | A displayed claim exposes its typed supporting references. | Renderer lists first SAN move from each typed alternative line. | `test_current_facts_include_mate_moves_checker_coordinates_and_failure_recovery` |
| Current-check prose omitted checker coordinates. | Structured references remain visible/reconstructable. | Renderer appends `Explanation.squares`; JSON retains piece/square IDs. | same focused current-facts regression; `test_current_check_references_the_replayed_checker_identity_and_scoped_evidence` |
| Details omitted recapture, promotion, and material changes. | Every promised line consequence is available in text and JSON. | Details renders typed consequence fields and current source/target/capture squares. | `test_details_render_recapture_promotion_and_material_change` |
| Survey/final disagreement lacked directly comparable typed scores. | Disagreement names both evidence states without prose inference. | Survey and probe evidence carry and render independent scores/bounds. | `test_survey_probe_sign_disagreement_preserves_both_typed_scores`; detail rendering regression |
| Mate alternatives were flattened into one impossible sequence. | Each alternative is a distinct legal root-to-leaf line. | Evidence carries parallel UCI and SAN alternative-line tuples. | `test_mate_alternatives_are_distinct_legal_lines_and_scoped_per_request` |
| Synthetic PV positions could collide across candidate roots. | Every evidence reference is request/revision/position scoped. | Synthetic node paths include request and root identity. | `test_principal_variations_on_different_roots_have_distinct_synthetic_positions` |
| Engine cancellation during UCI `readyok` raised `InvalidStateError`. | Cancel/finish must not cancel protocol-owned futures and must settle before reuse. | Adapter shields protocol handshake and controller finishes/cancels in order. | `test_cancel_during_analysis_ready_handshake_does_not_cancel_protocol_future`; `test_real_rapid_supersession_has_no_asyncio_protocol_errors_and_recovers`; native rapid navigation |
| Redirected Windows cp1252 stdout crashed on Unicode arrows/minus. | Native stdin/stdout/stderr follow one documented UTF-8 contract. | Composition reconfigures only native standard streams to UTF-8. | `test_native_process_reconfigures_cp1252_standard_streams_to_utf8`; native redirected five-candidate run |
| Missing engine failure exposed only a raw OS error. | Failure feedback guides recovery while preserving static work. | Failed summary explains same-path retry or restart with corrected `--engine`. | `test_current_facts_include_mate_moves_checker_coordinates_and_failure_recovery`; native missing-engine run |
| JSON legal moves and move delta had UCI but no SAN. | A GUI reconstructs presentation without replaying chess. | `LegalMove` and `MoveDelta` carry both UCI and SAN. | shared-view/JSON tests and static SAN assertions |
| Coverage could imply selected probes covered all legal moves. | Coverage distinguishes legal universe, selected union, and completed probes. | Added `total_legal`; text labels surveyed, selected, and probed separately. | controller coverage tests; native five-root/five-probe output |
| README implied save/export already existed. | Documentation separates implemented behavior from roadmap. | Persistence text marks save/export/settings records as future work. | documentation review |

## Adversarial end-to-end sequences

| Sequence | Assertions | Current evidence |
|---|---|---|
| Valid PGN → navigate rapidly → trial move → back → compare | No protocol-state exception; revisions advance; stale request cannot replace current; imported source unchanged. | Automated real rapid-supersession test and native Windows run passed. |
| Begin analysis → type partial `board` → receive progress/final output → finish command | Typed buffer survives; progress is stderr and at most 4 Hz; result is stdout. | Focused prompt-toolkit regression and native typed-buffer run passed. |
| Begin analysis → cancel → immediately load a new position | Cancel settles first; new request reaches completion and is not canceled by prior work. | Focused awaited-cancel regression passed. |
| Missing engine → inspect/navigate → restore same path and `analyze` | Failure is actionable; static work remains; explicit retry may start engine without restart loop. | Missing-engine native behavior verified; engine restart after failure covered by doubles. Same-process physical-file restoration is not recorded as a separate native sequence. |
| Fifteen-queen composed position and mirror → inspect → analyze | Every identity remains distinct; static inspection works; engine produces legal bounded candidates. | Static unusual-material test, guarded Stockfish mirrors, and native fifteen-queen run passed. |
| More than 32 occupied squares → inspect → `json` → EOF | Engine never prepares; unsupported reason and complete static facts remain; process closes cleanly. | Focused consumer test and native over-32 run passed. |
| Candidate allowing mate despite favorable engine score | Direct legal mate refutes certified rank; mate alternatives remain separate and visible. | `test_static_opponent_mate_refutes_a_contradictory_exact_top_score` and alternative-line tests passed. |
| Pinned recapture, en passant, and promotion lines | Claims come only from legal replay; capture square, recapture, promotion, and White material delta are explicit. | Counterexample fixtures, perspective parameterization, and CLI detail regression passed. |
| Survey/final sign disagreement and bound-only probe | Both scores and bounds remain visible; bound-only candidate is provisional/unranked but addressable. | Dedicated controller tests and native exact/provisional output passed. |
| cp1252 parent environment → UTF-8 redirected commands → Unicode result | No `UnicodeEncodeError`; exit 0; arrow/minus output decodes as UTF-8. | Actual subprocess regression and native redirected run passed. |
| Package wheel → inspect contents → install → run entry point | Catalog/assets/licenses included; engine/tests excluded; entry point works. | Final rebuilt wheel passed isolated extraction, import, and CLI-quit verification. |

## Audit findings and closure evidence

The fresh read-only audit identified five lifecycle findings. Their narrow fixes
were independently re-reviewed with no remaining major lifecycle/interface finding:

| Finding | Required invariant | Closure evidence |
|---|---|---|
| Concurrent cancel/replacement can stamp the new latest result canceled. | Cancellation mutates only the request that owned the cancel operation. | `test_cancel_targets_captured_request_without_canceling_or_waiting_for_replacement`; joined real lifecycle sequence |
| `close()` is not absorbing/shared across callers. | Close rejects later submission and concurrent close callers await one cleanup. | `test_close_is_absorbing_idempotent_and_shared_while_cleanup_runs` |
| Opener and configuration each receive a five-second timeout. | One five-second startup deadline covers both phases. | `test_startup_timeout_is_one_aggregate_deadline_and_reaps_configured_child` |
| Configuration failure can terminate transport without awaiting process reap. | Ownership transfers immediately after open; every failure path terminates and reaps the child. | `test_configuration_failure_reaps_owned_child` |
| Immediate close after submit can clear pending work while leaving `latest` in `RUNNING`. | Close request-scopes cancellation and stamps the same latest running request canceled only after settlement. | `test_close_immediately_after_submit_cancels_unstarted_request_without_engine_work`; `test_close_settles_active_request_to_a_nonrunning_state` |

The audit also found that evidence elapsed time was serialized but absent from
human details. The renderer now displays elapsed seconds or `absent`; the focused
presentation regression and post-fix full suite pass.

The accepted repair kept one narrow ownership model instead of adding another
lifecycle layer. The controller owns request identity, replacement, absorbing
close, and the shared close task. The adapter owns only its current transport and
protocol operation, transfers transport ownership immediately after open, and
settles/detaches it when directed. The session owns revision-safe consumer views.

Final acceptance evidence: the full suite with real Stockfish enabled passed 155
tests in 24.94 seconds, including the joined CLI workflow and all invariant
regressions. The final wheel
SHA-256 is
`caf44c3ca108ca3f8ce357bb30a341009b97ca5f475608a9ad59c0c803f2959c`.
Temporary isolated extraction/import/CLI-quit verification found the catalog,
twelve SVG pieces, project/art licenses and notices, no engines or tests, and no
remaining Stockfish process. The fresh read-only audit reported no remaining
major finding. The user-added combined invariant gate is complete.
