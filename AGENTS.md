# NamiChess Working Rules

## Project Goal

Build a local, rating-agnostic chess-analysis and training tool. NamiChess
explains board relationships, threats, plans, and practical continuations
instead of merely reproducing engine rankings.

The analysis backend is platform- and interface-agnostic. Windows 11-specific
launch, GUI, packaging, and file-picker behavior stays in interface adapters.

## Directory Conventions

- `src/namichess/domain/`: typed chess facts and rules. It may use
  `python-chess` but never imports engines, persistence, web, GUI, or operating-
  system adapters.
- `src/namichess/analysis/`: static analyzers, Stockfish integration, search
  scheduling, and verified explanation evidence. It imports `domain`.
- `src/namichess/application/`: use cases that compose analysis, training, and
  persistence. This is the only layer where independent analysis components
  meet.
- `src/namichess/interfaces/`: CLI, local API, web frontend assets, and optional
  Windows shell. Interfaces render application views and own no chess policy.
- `src/namichess/content/`: bundled, editable explanation text keyed by stable
  identifiers. Content files contain no chess policy or executable expressions.
- `src/namichess/composition.py`: the sole composition root; it may import all
  layers to wire concrete engines, storage, and interfaces.
- `tests/`: pytest tests mirroring package boundaries. Reusable FEN/PGN inputs
  and expected facts live under `tests/fixtures/`.
- `docs/`: active product, architecture, defense, and defect documentation.
- `.tools/`: ignored machine-local tools such as Stockfish; never package or
  commit these binaries.
- User and development data never lives in the source tree.

## Analysis Invariants

- Keep geometric control, legal access, and tactical ownership distinct.
- Counts expand to piece identities; counts alone never establish safety.
- Static analysis proposes facts and causal explanations. Search verifies or
  rejects tactical claims.
- Engine value belongs to the resulting position. Attribute it to a square or
  piece only when a verified causal delta supports that attribution.
- Safety and adequacy gate candidates before practical executability ranks them.
- Mate distance and engine depth are metadata, not measures of human difficulty.
- Analyze consequences of opponent moves without inventing intent.
- Opening principles, motif names, and annotation glyphs are not explanations.

## Persistence Rules

- Do not add SQLite until measured data volume or query needs justify it.
- PGN and FEN remain standard chess interchange. Small app-owned records use
  versioned UTF-8 JSON with explicit typed readers and writers.
- Store user settings separately from games and derived analysis. Presets resolve
  to immutable per-job policies; saved analyses retain the resolved policy.
- Never modify an imported game file in place. Save or export to a distinct,
  user-confirmed destination.
- Keep original chess content separate from derived analysis and user metadata.
- Do not accept arbitrary paths through a browser or API. Native CLI arguments
  and GUI file pickers establish explicit file scope.

## Implementation Rules

- Implement only the current phase. Do not add speculative frameworks,
  extension points, databases, distributed workers, or generalized protocols.
- Make surgical changes. Every changed line must trace to the current task.
- Prefer frozen dataclasses and enums for internal facts. Use Pydantic only at
  external or persistence boundaries where validation is useful.
- Construct infrastructure only in `composition.py`. Domain and analysis code
  receive engines, clocks, and storage collaborators rather than constructing
  them.
- Keep Stockfish behind a narrow adapter. No domain type depends on a process,
  executable path, or UCI representation.
- Background analysis is bounded and cancelable. A newer foreground request may
  supersede obsolete work.
- Keep Python orchestration nonblocking. Stockfish owns its explicitly budgeted
  native threads; use process workers only for measured CPU-heavy Python work.
- Use PowerShell and native Windows paths for project commands. Do not introduce
  Bash, WSL, CMD, or Unix-only workflows without a concrete need.

## Defense Scope

- NamiChess is a single-user, local, non-safety-critical application.
- No remote service, telemetry, account, browser navigation, or external network
  access belongs in the runtime product.
- Defend the narrow local-file boundary and prevent accidental source/destination
  confusion. Bound analysis work enough to keep the UI responsive.
- Do not claim protection from motivated adversaries, same-user hostile code, or
  OS/runtime compromise. Do not let NamiChess amplify access into privilege
  elevation, process execution, remote authority, or broader filesystem reach.
- Do not add authentication, cryptographic protocols, hostile multi-tenant
  isolation, durable job custody, replay machinery, or defense-in-depth without
  a demonstrated product risk.
- Treat incorrect analysis as a chess-quality defect, not a security incident.

## Testing and Verification

- Use pytest.
- Add a focused regression for changed chess behavior, preferably using a named
  FEN/PGN fixture with expected structured facts.
- Mirror-test perspective-sensitive metrics by color or board transformation.
- Test unsupported SEE and engine cases explicitly; do not silently guess.
- Run the narrowest relevant tests while editing, then the ordinary suite before
  a mergeable commit.
- Before completion, review for requirement drift, false chess claims, brittle
  assumptions, accidental file overwrite, and unnecessary complexity.

## Documentation

- `README.md` is the setup guide and documentation index.
- `docs/FEATURES.md` owns current and planned product behavior.
- `docs/ARCHITECTURE.md` owns durable boundaries, data flow, and invariants.
- `docs/DEFENSE.md` owns the deliberately narrow trust and non-goal model.
- `docs/BUGS.md` records confirmed substantive defects, not ideas or tasks.
- `CHANGELOG.md` records completed task-level changes newest-first.
- Update the owning document with any behavior or architectural change.

## Git and Commits

- Do not commit virtual environments, caches, downloaded engines, generated
  analysis, user games, or local settings.
- Stage exact paths; preserve unrelated work.
- Use `<category>(<optional-scope>): <imperative summary>` with `feat`, `fix`,
  `docs`, `test`, `refactor`, `perf`, `build`, or `chore`.
- Keep each commit to one coherent outcome with matching tests and documentation.

## Cleanup

- Remove only artifacts created by the current change.
- Do not reformat, refactor, or delete unrelated material opportunistically.
