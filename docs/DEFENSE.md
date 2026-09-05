# NamiChess Defense

Status: pre-implementation. This document deliberately keeps the defense model
small and proportional to the product.

## Scope and trust model

NamiChess is a single-user, local, non-safety-critical chess analysis tool. Its
backend is platform-agnostic; Windows 11 GUI, CLI, and file-picker adapters are
the explicit local boundary. Runtime remote access is not a product feature:
no remote server, telemetry, account, browser navigation, or external network
service. A process-local or loopback presentation adapter does not change that
boundary and must not become remotely reachable.

The meaningful consequence to defend against is accidental local-file damage or
mingling, especially confusing an imported/saved game with a derived analysis or
metadata file. Stockfish consuming CPU is a visible nuisance, not a safety
incident. Incorrect analysis is a chess-quality defect, not a security event.

## Minimal controls

- Keep PGN/FEN source content separate from derived analysis and user metadata.
- Never modify an imported game in place; save or export to a distinct,
  user-confirmed destination.
- Use explicit native CLI paths or GUI file pickers. Do not accept arbitrary
  paths through a browser or API.
- Use versioned UTF-8 JSON for small app-owned records; keep SQLite deferred
  until measured volume or query needs justify it.
- Bound and cancel analysis work so stale requests cannot run indefinitely or
  make the interface appear hung.
- Keep Stockfish behind a narrow adapter and treat its executable/configuration
  as local development or installation state, not user chess data.

## Explicit non-goals

Do not add authentication, cryptographic protocols, hostile multi-tenant
isolation, durable job custody, replay machinery, elaborate bridge protocols,
or general defense-in-depth without a demonstrated product risk. Do not add
remote access merely to support a future architecture. A user who already has
access to the machine is outside this threat model.
