# NamiChess Bugs

Status: M2 verification. Confirmed defects and their resolutions are recorded below.

## Defect ledger

| ID | Status | Area | Summary | Evidence |
|---|---|---|---|---|
| M2-001 | Fixed | Local exploration | Automatic terminal positions with geometric legal moves were expanded beyond game end. | `r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1`, root `b7a8b`: insufficient-material draw incorrectly had five examined replies. Independent review reproduced it; terminal-source/root and assessment regressions now pass. |

M2-001 is fixed by a terminal check at the source and immediately after each root,
before enumerating replies. Output is a terminal root line with zero replies,
or no root work when the source is already terminal. Terminal-source trapping
assessment is unsupported rather than a claim about piece mobility. Regressions
cover mirrored insufficient material, automatic 75-move and fivefold draws,
claimable draws, and checkmate. The full Stockfish gate passed 292 tests.

## What belongs here

Record a reproducible, substantive defect in implemented behavior: a failing
test, a directly observed incorrect result, or a documented regression. Include
the affected area, reproduction or fixture, expected behavior, actual behavior,
and current status.

Do not use this ledger for ideas, unverified suspicions, planned features,
architecture debates, or ordinary setup notes. Track those in the relevant
feature, architecture, or project discussion instead.
