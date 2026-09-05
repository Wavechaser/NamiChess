# NamiChess Defense

Status: pre-implementation. The defense model is intentionally small and must not
be used to justify architecture unrelated to the product's actual risks.

## Scope

NamiChess is a single-user, local, non-safety-critical application. It has no
runtime remote server, external service, telemetry, account, or browser
navigation. A process-local or loopback presentation bridge must not become
remotely reachable.

The narrow untrusted surface is local PGN, FEN, settings, explanation content,
custom SVG themes, and saved-analysis bytes. The main risks are malformed input,
accidental file damage, source/output confusion, and turning a presentation or
parser boundary into broader filesystem or process authority.

High Stockfish CPU use is expected while analysis is active. Work budgets,
cancellation, and foreground priority protect responsiveness; they are not a
security boundary. Incorrect or falsified analysis is a chess-quality defect,
not a safety or security incident.

## Minimal controls

- Parse chess files and JSON as data. Explanation templates contain no executable
  expressions or code-loading behavior.
- Treat custom SVGs as images, not inline application markup. Require the fixed
  piece-theme contract and block scripts and external resource loading.
- Keep imported PGN/FEN, app-owned games, settings, metadata, and derived analysis
  distinct. Never overwrite an imported source implicitly.
- Accept paths only from explicit native CLI arguments or GUI file pickers. A
  browser or local API receives opaque app identifiers, not arbitrary paths.
- Keep any presentation bridge loopback-only, narrowly scoped, and unable to
  launch processes or expand file authority.
- Keep Stockfish behind one narrow adapter. Validate its configured executable;
  do not select or download engines from parsed chess content.
- Use versioned typed readers, bounded input sizes, atomic settings/metadata
  replacement, and actionable errors for malformed files.
- Bound and cancel analysis so normal engine work remains visible and controllable.

## Threat boundary

NamiChess does not protect against motivated adversaries, same-user hostile code,
or compromise of the administrator, operating system, Python runtime, or engine
binary. It does not attempt to hide chess data from an actor with meaningful
machine access.

It must nevertheless avoid amplifying its own authority. Parsed content and local
interfaces must not provide privilege elevation, arbitrary process execution,
remotely reachable authority, broader filesystem access, or convenient mingling
and destruction of unrelated files.

## Explicit non-goals

Do not add authentication, cryptographic protocols, hostile multi-tenant
isolation, durable job custody, replay machinery, elaborate bridge protocols, or
general defense-in-depth without a demonstrated product risk. Do not add remote
access or a security framework in anticipation of hypothetical future features.
