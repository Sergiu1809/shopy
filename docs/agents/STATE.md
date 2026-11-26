# STATE — Shopy

<!-- graffino-agentic:team:begin v1 -->
> What exists and what is in flight. **An index, not a narrative:** at most 150 lines,
> each table row at most 220 characters (`ledger-lint.py` checks both). Detail lives in the ticket folders and the ledger.
> Updated by every session that starts, pauses or finishes a ticket.
<!-- graffino-agentic:team:end -->

Updated 2026-11-25.

## The product
Shopy: a Romanian voice shopping assistant (iPhone PWA + admin) for one demo store.
P0 done (GH-1); P1a done (GH-3); P1b done (GH-4); P1c in flight (GH-5); then P1d (GH-6). Structure: `docs/agents/ARCHITECTURE.md`.

## In flight
| Ticket | Title | Status | Branch | PR | Folder |
|---|---|---|---|---|---|
| GH-5 | P1c: Catalog and seed | full lane; built (370 passed); review round 1 pass with findings; fixes then gate C | feat/catalog-seed-GH-5 | #11 | docs/agents/tasks/GH-5/ |

## Recently done (last 10)
| Ticket | Title | Done | PR |
|---|---|---|---|
| GH-4 | P1b: Authentication and roles | 2026-11-25 | #10 |
| GH-8 | Design: phone mockups, Assistant home and Settings | 2026-11-19 | #9 |
| GH-3 | P1a: Database models and migrations | 2026-11-18 | #7 |
| GH-1 | P0 Setup: Compose skeleton, CI, .env.example, gitleaks | 2026-11-18 | #2 |

## Knowledge
- Ledger: 24 decisions (1 superseded) · 15 patterns (2 candidates) · 5 contracts · 14 open questions.
- Backfill: none (new repo, seeded from the brief on 2026-11-17).
