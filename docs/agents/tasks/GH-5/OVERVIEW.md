---
ticket: GH-5
type: task
parent:
covers: []
delivered_in:
title: "P1c: Catalog and seed"
status: in-review
lane: full
branch: feat/catalog-seed-GH-5
pr: https://github.com/Sergiu1809/shopy/pull/11
design_refs: []
summary: "Romanian demo catalog (catalog.json, validator in CI), store policies and demo accounts, loaded by make seed"
created: 2026-11-25 00:00
updated: 2026-11-26 17:15
---

# GH-5 — P1c: Catalog and seed

## Goal
A realistic Romanian demo store in the database with one command (brief §8; D-023).
GH-6 (admin CRUD) is blocked by this ticket: its test has the seeded admin edit a
seeded product.
Ticket: https://github.com/Sergiu1809/shopy/issues/5

## Context brief 🧾
- **Acceptance criteria (approved, GH-5; ticket text + gate A answers 2026-11-25, user):**
  - [ ] `backend/seed/catalog.json`, written once by the coding assistant (D-023), committed: about 200 products in Romanian, real brands, realistic prices in RON; variants with their own `price_minor` and `stock`; 3–15 Romanian reviews per product with mixed ratings.
  - [ ] Categories: exactly the five named ones (clothing, laundry and cleaning, cosmetics and personal care, small electronics, home), Romanian names, ASCII slugs. (Q4)
  - [ ] Language: product, variant, review, category and policy texts in Romanian (D-021); keys, slugs and code in English. (Q7)
  - [ ] Store row: name "Shopy", currency RON, in `catalog.json`. (Q1)
  - [ ] The 4 fixtures, flagged with `"fixture"`: `prompt_injection` (a review that tries to make the assistant break its rules or give a discount), `xss` (a review with `<script>` / `<img onerror=…>`), `out_of_stock` (a product whose every variant has stock 0), `missing_attribute` (a clothing product with no `material` in its description or `attributes`). Stored verbatim; never escaped or stripped by the seed (PATTERN-003, PATTERN-009). (Q6)
  - [ ] `store_policies`, one row per kind, Romanian text: shipping 19.99 RON, free from 200.00 RON, delivery estimate "2 to 4 business days" placeholder (Q-002); returns 14 days; 2-year legal warranty; payment by card only; one clothing size guide. The delivery estimate lives only in `store_policies` for now; a config constant comes with P4 pricing. (Q10)
  - [ ] `python -m seed.validate_catalog` (Pydantic schema + fixture checks) passes and runs in CI (a step in the backend job). Limits: 190–210 products; 3–15 reviews per product; at least one variant per product; SKUs unique; `price_minor` a positive integer; `stock` an integer ≥ 0; ratings 1–5; each fixture kind exactly once. (Q5)
  - [ ] `make seed` (new root `Makefile`: `docker compose run --rm api python -m seed.seed`) loads the files deterministically, with no LLM call and no API key (D-023).
  - [ ] Deterministic: fixed insertion order (same IDs on a fresh database, D-024); every review has a fixed `created_at` in the JSON; `rating_avg` and `rating_count` computed at seed time, `rating_avg` rounded to 2 decimals. (Q9)
  - [ ] Re-running is safe: insert only what is missing, never overwrite. If the store row exists, the catalog part is skipped and the seed prints "already seeded"; a user (with their addresses and preferences) is inserted only when their email (case-insensitive) is absent. One transaction. No migration. (Q2)
  - [ ] Demo accounts in `backend/seed/users.json`, fictitious data written by the coding assistant: `admin@example.com` (admin), `customer1@example.com`, `customer2@example.com` (customers); each customer has 2 Romanian addresses (one default); one customer has `user_preferences`. Names, addresses and phone numbers are invented, not real people. (Q3)
  - [ ] Passwords from `SEED_ADMIN_PASSWORD` / `SEED_CUSTOMER_PASSWORD`, hashed with GH-4's `app.auth.passwords.hash_password`. The seed applies the register rule (8–128 characters, one uppercase letter, one digit) and refuses to run with a clear message when a variable is unset or breaks it (so the `change-me` placeholder fails). (Q8)
  - [ ] Seeded accounts can log in through `POST /auth/login` (the email validator rejects `.test` / `.local`; `example.com` passes).
- **Out of scope:** product images (Q-001); Stripe Customer and test cards for the demo customers (P4, Q-015: `stripe_customer_id` stays NULL, no `payment_methods` rows) (Q11); indexing and the outbox (P2); `generate_catalog.py` (superseded by D-023; the brief still names it).
- **Scope overlaps:**
  - GH-6 relies on a working seeded admin login and at least one seeded product.
- **Tickets covered:** GH-5 (Fixes)
- **Constraints that apply:**
  - D-023 — catalog written once by the coding assistant, committed, validated in CI, loaded without an LLM or key.
  - D-024 — bigint identity keys; fixed insertion order gives fixed IDs.
  - D-021 — store data in Romanian; code and docs in English.
  - D-004 — one Postgres database.
  - PATTERN-001 — money as integers in bani, VAT included; shipping 1999, or 0 from a 20000 subtotal.
  - PATTERN-008 — SQLAlchemy only; schema changes only through Alembic (none expected).
  - PATTERN-013 — seed passwords only from `SEED_*` env vars; no secret in the repo.
  - PATTERN-003, PATTERN-009 — the injection and XSS fixtures are stored verbatim for later phases.
  - PATTERN-014 (candidate) — only if a migration turns out to be needed.
  - Q-001 (no images), Q-002 (placeholder delivery estimate), Q-015 (Stripe test cards, P4).
- **Where the code is:**
  - New: `backend/seed/` (`__init__.py`, `schema.py` with the Pydantic models shared by validator and loader, `validate_catalog.py`, `seed.py`, `catalog.json`, `users.json`), root `Makefile`.
  - Reused, unchanged: `backend/app/models/{store,catalog,user}.py`, `backend/app/schemas/auth.py` (`Email`, `Password`), `backend/app/auth/passwords.py` (`hash_password`), `backend/app/db.py` (`create_engine`, `create_sessionmaker`).
  - Tests: `backend/tests/test_seed_validate.py`, `backend/tests/test_seed_load.py` (they reuse `fresh_db_url`, `fetch`, `alembic_config`, `session`, `client` from `backend/tests/conftest.py`).
  - Also changed: `.github/workflows/ci.yml` (validator step), `.env.example` (comment), `AGENTS.md` §2–§3, `docs/agents/ARCHITECTURE.md` (seed row).
- **Ownership:** integration owner: the conductor.
  - The test author writes both test files first.
  - One code builder does everything under `backend/seed/` except the category content: the `catalog.json` skeleton with store and policies, `users.json`, the Makefile, CI and docs.
  - Five content workers in parallel, each in its own worktree on a private branch, each write one fragment `backend/seed/parts/<slug>.json` with 40 products: W1 clothing, W2 laundry-and-cleaning, W3 cosmetics-and-personal-care, W4 small-electronics, W5 home. Fixtures and SKU prefixes are split between them as in PLAN.md Sequencing.
  - The conductor joins the fragments into `catalog.json` and commits only that file.
- **Verify with:**
  - `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest` (Docker for testcontainers)
  - `cd backend && uv run python -m seed.validate_catalog`
  - `python3 docs/agents/tools/ledger-lint.py`
  - When Docker Compose and a real `.env` are available: `docker compose up --build -d api`, then `make seed` twice. The second run prints "already seeded".

## Resume here ⏯
Gate C done: point 26 passed (seed twice, logins 200), PATTERN-016 leftovers deferred as Q-016, PR #11 ready for review. Waiting on the user to merge it; then GH-6. See `log_2026-11-26_1706.md`.

## Summary of work so far
- 2026-11-25 — product owner: coverage report, gate A answered by the user (Q1–Q11); Q-015 recorded for the P4 Stripe test cards.
- 2026-11-25 — planner: `PLAN.md` written.
- 2026-11-26 — gate B: plan approved as written; PATTERN-001, PATTERN-003, PATTERN-015 confirmed.
- 2026-11-26 — tests first (121, red; 0c3d04c); code (abe96c3, 090f502); five content workers; catalog assembled (843555d): 200 products, 744 variants, 1412 reviews; 370 passed.
- 2026-11-26 — review round 1: pass with findings (F1 PR draft/body, F2 journal, F3 author names; nits F4–F8).
- 2026-11-26 — PR back to draft; F3 (2b89fd1) and F4–F7 (2ed6c12, b4694be) fixed; candidate PATTERN-016 (c399ca8).
- 2026-11-26 — review round 2: pass with findings; key naming and leftovers fixed (159620d). Final: 200 products, 744 variants, 1406 reviews; 370 passed.
- 2026-11-26 — gate C: point 26 passed (seed twice; three logins 200); PATTERN-016 leftovers deferred (Q-016); PR #11 marked ready.

## Approach
See `PLAN.md`. In short:
- Shared Pydantic models (`seed/schema.py`) are used by both the CI validator and the loader.
- The loader inserts only what is missing, in file order, in one transaction, and reuses GH-4's `Email`, `Password` and `hash_password`.
- `catalog.json` is one file, assembled from five category fragments written by parallel content workers.

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| create | `docs/agents/tasks/GH-5/OVERVIEW.md` | journal and context brief |
| modify | `docs/agents/OPEN-QUESTIONS.md` | Q-015 (Stripe test cards for demo customers, P4) |
| create | `docs/agents/tasks/GH-5/PLAN.md` | plan for gate B |
| create | `docs/agents/tasks/GH-5/TESTS.md` | acceptance points → tests |
| create | `docs/agents/tasks/GH-5/log_2026-11-26_1409.md` | session log |
| modify | `docs/agents/PATTERNS.md` | Confirmed 2026-11-26 on PATTERN-001, -003, -015; candidate PATTERN-016 |
| modify | `docs/agents/STATE.md` | GH-5 row |
| create | `backend/seed/__init__.py`, `schema.py`, `validate_catalog.py`, `seed.py` | formats, validator, loader |
| create | `backend/seed/catalog.json` | store, five policies, 200 products in five categories |
| create | `backend/seed/users.json` | 1 admin, 2 customers (fictitious) |
| create | `backend/tests/test_seed_validate.py`, `backend/tests/test_seed_load.py` | 121 tests |
| create | `Makefile` | `make seed` |
| modify | `.github/workflows/ci.yml` | catalog validator step in the backend job |
| modify | `.env.example` | password rule comment above `SEED_*` |
| modify | `AGENTS.md` | §2 commands, §3 layout |
| modify | `docs/agents/ARCHITECTURE.md` | seed row, CI line |

## Manual verification 🔧
Point 26 run by the user on 2026-11-26: first `make seed` inserted everything, the second printed "already seeded"; the three seeded accounts log in (200).
No manual-test path changes, so no MT- entry ("Manual test: not needed"). The conductor runs `make seed` twice on local Compose if Docker is available; otherwise the PR's Testing done names it as skipped.

## Decisions log 🧭
- **2026-11-25 — Re-run inserts only what is missing** — Why: admin edits (GH-6) survive a re-run; no product natural key or migration needed. Rejected: overwrite from the file (reverts admin edits, needs a key); wipe and reload (destroys data; later orders reference variants). (gate A Q2)
- **2026-11-25 — Demo emails on example.com** — Why: the login email validator rejects `.test` and `.local`. Rejected: `shopy.test`. (gate A Q3)

## Open questions / blockers
- [ ] Q-015 — Stripe test cards for the demo customers (P4; out of scope here).
- [ ] Q-016 — attribute values kept as text by the schema (deferred to P2).

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/5
- PR: https://github.com/Sergiu1809/shopy/pull/11
