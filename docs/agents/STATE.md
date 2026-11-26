# STATE — Shopy

<!-- graffino-agentic:team:begin v1 -->
> What exists and what is in flight. **An index, not a narrative:** at most 150 lines,
> each table row at most 220 characters (`ledger-lint.py` checks both). Detail lives in the ticket folders and the ledger.
> Updated by every session that starts, pauses or finishes a ticket.
<!-- graffino-agentic:team:end -->

Updated 2026-11-26.

## The product
Shopy: a Romanian voice shopping assistant (iPhone PWA + admin) for one demo store.
P0 done (GH-1); P1a done (GH-3); P1b done (GH-4); P1c done (GH-5); P1d in flight (GH-6). Structure: `docs/agents/ARCHITECTURE.md`.

## In flight
| Ticket | Title | Status | Branch | PR | Folder |
|---|---|---|---|---|---|
| GH-6 | P1d: Admin product CRUD API | full lane; gate A answered (hard delete, nested variant routes; Q-017 for P4); next /plan | feat/admin-products-GH-6 | #12 | docs/agents/tasks/GH-6/ |

## Recently done (last 10)
| Ticket | Title | Done | PR |
|---|---|---|---|
| GH-5 | P1c: Catalog and seed | 2026-11-26 | #11 |
| GH-4 | P1b: Authentication and roles | 2026-11-25 | #10 |
| GH-8 | Design: phone mockups, Assistant home and Settings | 2026-11-19 | #9 |
| GH-3 | P1a: Database models and migrations | 2026-11-18 | #7 |
| GH-1 | P0 Setup: Compose skeleton, CI, .env.example, gitleaks | 2026-11-18 | #2 |

## Knowledge
- Ledger: 24 decisions (1 superseded) · 15 patterns (2 candidates) · 5 contracts · 16 open questions.
- Backfill: none (new repo, seeded from the brief on 2026-11-17).
