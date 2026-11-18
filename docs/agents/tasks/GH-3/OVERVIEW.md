---
ticket: GH-3
type: task
parent:
covers: []
delivered_in:
title: "P1a: Database models and migrations"
status: in-progress
lane: full
branch: feat/db-models-GH-3
pr: https://github.com/Sergiu1809/shopy/pull/7
design_refs: []
summary: "Async SQLAlchemy models and the first Alembic migration for the P1 tables, tested on real Postgres"
created: 2026-11-18 15:48
updated: 2026-11-18 15:48
---

# GH-3 — P1a: Database models and migrations

## Goal
Give the backend its database layer: async SQLAlchemy models and Alembic migrations
for the tables P1 uses (brief §7, §19 P1). GH-4, GH-5 and GH-6 are blocked by it.
Ticket: https://github.com/Sergiu1809/shopy/issues/3

## Context brief 🧾
- **Acceptance criteria (approved, GH-3):**
  - [ ] Async SQLAlchemy 2 + Alembic set up in `backend/` (migrations in `backend/migrations/`, brief §6); `DATABASE_URL` from env.
  - [ ] The first migration creates the `vector` and `unaccent` extensions (`IF NOT EXISTS`; also needed where there is no init script, e.g. Neon), then the tables `stores`, `users`, `refresh_tokens`, `addresses`, `user_preferences`, `categories`, `products`, `product_variants`, `product_images`, `reviews` and `store_policies`, with the brief §7 columns. No other columns.
  - [ ] Money columns are integers suffixed `_minor` (PATTERN-001); timestamps are `timestamptz` UTC; `store_id` is on `categories`, `products` and `store_policies` (see gate A below).
  - [ ] `addresses`: at most one default per user, as a partial unique index on `user_id WHERE is_default`. "Exactly one" once a user has addresses is app logic (P4).
  - [ ] `alembic upgrade head` and `alembic downgrade base` both work.
  - [ ] The api container runs `alembic upgrade head` on start, then uvicorn (Q9).
  - [ ] Tests run against real Postgres + pgvector through testcontainers, and CI runs them.
  - [ ] Carried over from GH-1:
    - `docs/agents/MANUAL-TESTS.md`: an MT-001 History row (passed, 2026-11-18, developer).
    - `docs/agents/STATE.md`: GH-1 moved from "In flight" to "Recently done" (PR #2 merged, issue closed); Knowledge counts updated (D-022 superseded, D-023 approved).
    - `docs/agents/tasks/GH-1/OVERVIEW.md`: `status: done`.
    - The D-023 working-tree changes (supersedes D-022) committed on this branch.
  - [ ] Stale docs fixed in this PR (Conflict 4):
    - In Q-001 (`docs/agents/OPEN-QUESTIONS.md`), cite D-023 instead of D-022.
    - In AGENTS.md §2, replace the "Planned in P0 — not run" wording with the real commands, since P0 is merged.
- **Out of scope:**
  - Tables of later phases: `kb_chunks`, `reindex_outbox`, `conversations`, `messages`, `carts`, `cart_items`, `order_proposals`, `proposal_items`, `orders`, `order_items`, `order_confirmations`, `webauthn_challenges`, `payment_methods`, `passkey_credentials`, `usage_ledger`.
  - The romanian + unaccent text search configuration (P2).
  - Auth, seed and endpoints.
  - A product natural key, which GH-5 adds by migration if it needs one.
  - A rate-limit table (GH-4).
  - Soft delete (GH-6 decides).
- **Gate A answers (2026-11-18, user), which the builder must follow:**
  - **Q1 Primary keys:**
    - `bigint` identity (`GENERATED ... AS IDENTITY`) on every table, now and in later phases.
    - `user_preferences` uses `user_id` as its primary key.
    - Recorded as D-024 (approved 2026-11-18).
  - **Q2 ON DELETE:**
    - CASCADE from `users` to `refresh_tokens`, `addresses` and `user_preferences`.
    - CASCADE from `products` to `product_variants`, `product_images` and `reviews`.
    - RESTRICT from `categories` to `products`, and from `stores` to every table that references it.
    - Every foreign key column is indexed.
    - No soft-delete column.
  - **Q3 Uniqueness:**
    - A unique index on `lower(email)` (GH-4 lowercases on input); no `citext`.
    - `UNIQUE(sku)` across the whole table.
    - `UNIQUE(store_id, slug)` on `categories`.
    - `UNIQUE(token_hash)` on `refresh_tokens`.
    - `UNIQUE(store_id, kind)` on `store_policies`.
    - `stripe_customer_id`: no unique constraint.
    - `product_images.position`: not unique.
  - **Q4 CHECK constraints:**
    - `price_minor >= 0` and `stock >= 0`.
    - `reviews.rating` is an integer between 1 and 5.
    - `rating_count >= 0`.
    - `rating_avg` is `numeric(3,2)`, between 0 and 5, or NULL when there are no reviews.
  - **Q5 Enums:**
    - `users.role` and `store_policies.kind` are `text` with a CHECK, not native ENUM types.
    - `role` is in (`customer`, `admin`), default `customer`.
    - `kind` is in (`shipping`, `returns`, `warranty`, `payment`, `size_guide`).
  - **Q6 Types and nullability:**
    - String columns are `text`; length limits live in Pydantic (PATTERN-006). `stores.currency` is `char(3)` with default `RON`.
    - Every column is NOT NULL except `addresses.label`, `users.stripe_customer_id`, `refresh_tokens.revoked_at`, `products.rating_avg`, `products.content_hash` and `product_images.alt_text`.
    - `jsonb` and array columns are NOT NULL with an empty default (`'{}'`).
  - **Q7 `version`:**
    - `integer NOT NULL DEFAULT 1` on `products`, `product_variants` and `store_policies`.
    - App code increments it (GH-6); no trigger and no SQLAlchemy `version_id_col`.
    - `products.updated_at` uses `server_default now()`, and the ORM sets it on update.
    - `users.created_at` and `reviews.created_at` use `server_default now()`.
  - **Q8 Columns filled later:**
    - `products.content_hash` is created now and stays NULL until P2.
    - `rating_avg` and `rating_count` are created now; GH-5 computes them at seed time; no trigger.
  - **Q9 Migrations on start:** the api container runs `alembic upgrade head` and then uvicorn. The worker keeps its own command. Production migration is P7 (Q-011).
  - **Q10 Downgrade:** `downgrade base` drops the tables and keeps the extensions.
  - **Q11 Tests:**
    - testcontainers, with the image pinned to `pgvector/pgvector:0.8.7-pg16` (the same image as Compose).
    - A round-trip test: upgrade, downgrade base, upgrade.
    - A drift test: the models match the migration (Alembic compare).
    - A SQLAlchemy `MetaData` naming convention for deterministic constraint names.
    - DB tests fail loudly without Docker; they never skip silently.
  - **Conflict 1, `store_id`:** follow the brief §7 columns. `store_id` is only on `categories`, `products` and `store_policies`; `stores` is their parent. `product_variants`, `product_images` and `reviews` reach their store through `product_id`.
  - **Conflict 2, CI database:** testcontainers. The brief §17 "Postgres+pgvector service" wording is outdated; `ci.yml` gets no service container.
  - **Conflict 3:** brief §8 and §19 name `generate_catalog.py`; D-023 wins. This is GH-5's concern.
- **Tickets covered:** GH-3 (Fixes)
- **Constraints that apply:**
  - D-003: Python 3.12, FastAPI, Pydantic v2, async SQLAlchemy 2, Alembic.
  - D-004: one Postgres 16 with pgvector and unaccent; no Redis or broker.
  - D-006: `content_hash` and `version` exist so P2 can reindex one source at a time; price and stock are never indexed.
  - D-010: prices and stock come only from the DB (`product_variants`).
  - D-023: the seed `catalog.json` is written once and loaded deterministically (GH-5 relies on this schema).
  - PATTERN-001: money is an integer in bani, columns suffixed `_minor`.
  - PATTERN-006: lengths and ranges are also validated in Pydantic at the API (GH-4, GH-6).
  - PATTERN-008: SQLAlchemy with bound parameters; schema changes only through Alembic; `timestamptz` UTC.
  - PATTERN-012: CI makes no provider calls; testcontainers is not a provider.
  - PATTERN-013: `DATABASE_URL` comes from env; no credentials in files.
- **Where the code is:**
  - Existing: `backend/app/main.py`, `backend/tests/test_health.py`, `backend/pyproject.toml` + `uv.lock`, `backend/Dockerfile`, `docker-compose.yml` (`api`), `docker/db/init/01-extensions.sql` (copied into migration `0001`), `.github/workflows/ci.yml` (unchanged steps), `.env.example` (`DATABASE_URL` already `postgresql+asyncpg://`).
  - New: `backend/app/db.py`, `backend/app/models/{__init__,base,store,user,catalog}.py`, `backend/alembic.ini`, `backend/migrations/{env.py,script.py.mako,versions/0001_initial_schema.py}`, `backend/tests/{conftest,test_db_config,test_schema,test_constraints,test_migrations}.py`.
  - Docs: `AGENTS.md`, `ARCHITECTURE.md`, `PATTERNS.md`, `OPEN-QUESTIONS.md`, `MANUAL-TESTS.md`, `STATE.md`, `tasks/GH-1/OVERVIEW.md`.
  - Full table: `PLAN.md`.
- **Ownership:**
  - Integration owner: the conductor.
  - One builder for every part.
  - A **test author** goes first. They add the `testcontainers` and `pytest-asyncio` dev dependencies and `backend/tests/*`, and the tests stay red until the models, `app/db.py` and `alembic.ini` exist.
  - No parallel workers.
- **Verify with** (from `backend/` unless noted):
  - `uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest` (needs Docker; starts `pgvector/pgvector:0.8.7-pg16` through testcontainers)
  - `DOCKER_HOST=unix:///nonexistent uv run pytest` must show DB tests as ERROR, never SKIPPED
  - `uv run alembic heads` shows `0001`
  - From the repo root: `docker compose up -d --build db api`, `docker compose logs api` (shows `Running upgrade  -> 0001` before uvicorn), `curl -fsS localhost:8000/health`, `docker compose exec db psql -U shopy -d shopy -c '\dt'` (11 tables + `alembic_version`), `docker compose restart api` (no new upgrade)
  - `python3 docs/agents/tools/ledger-lint.py`
  - CI `backend` job green after the push (with the user's go).

## Resume here ⏯
Gate A passed on 2026-11-18. `PLAN.md` is written; next is **gate B** (approve the plan, the Knowledge used and Assumptions A1–A10).
Nothing is built yet. Branch `feat/db-models-GH-3` is local and not pushed. D-023, D-024 and the gate A journal are committed (`75d25d4`). Not committed yet: `PLAN.md` and the planner's edits to this file.

## Summary of work so far
- 2026-11-18 — Product owner coverage report; gate A answered (Q1–Q11, store_id, testcontainers); no new tickets and no Q- entries.

## Approach
See `PLAN.md` (planner, 2026-11-18; awaiting gate B). It covers:
- async SQLAlchemy models in `app/models/` with a naming convention
- one hand-reviewed Alembic revision `0001` (extensions + 11 tables)
- testcontainers tests for exact schema, constraints and delete rules, plus a round-trip and a drift test
- Compose `api` running `alembic upgrade head` before uvicorn.

`TESTS.md` comes from the test author.

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| create | `docs/agents/tasks/GH-3/OVERVIEW.md` | journal and context brief |

## Manual verification 🔧
- No MT- entry is needed: no path in `.github/manual-test-paths` is touched. The PR says "Manual test: not needed".
- Docker is reachable from WSL, so the builder checks migration on start with Compose itself (PLAN #31).
- Optional for the developer: on the Windows desktop, run `docker compose up --build`; `docker compose logs api` should show `Running upgrade  -> 0001`.
- MT-001 (GH-1) moves to History as a carry-over.

## Decisions log 🧭
- **2026-11-18 — bigint identity primary keys everywhere** — Why: short IDs the LLM copies reliably, cheap in tokens, easy to seed deterministically; enumeration is covered by ownership checks (PATTERN-007). Rejected: UUID everywhere, and a UUID/bigint mix. (D-024, approved 2026-11-18.)
- **2026-11-18 — `store_id` follows the brief §7 columns** — Why: a copied `store_id` on child tables could drift from the product's. Rejected: `store_id` on variants, images and reviews.
- **2026-11-18 — testcontainers in CI, no service container** — Why: the ticket, brief §5 and AGENTS.md agree; the brief §17 wording is outdated. Rejected: a GitHub Actions Postgres service.

## Open questions / blockers
- [x] none: everything was answered at gate A on 2026-11-18.

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/3
- PR:
