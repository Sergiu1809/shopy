---
ticket: GH-13
type: task
parent:
covers: []
delivered_in:
title: "P2a: Reindex outbox, worker, chunking and embeddings"
status: in-progress
lane: full
branch: feat/reindex-worker-GH-13
pr: https://github.com/Sergiu1809/shopy/pull/16
design_refs: []
summary: "kb_chunks, reindex_outbox, minimal usage_ledger; outbox rows from admin routes and the seed; async worker chunks and embeds changed sources only"
created: 2026-11-26 21:35
updated: 2026-11-26 21:30
---

# GH-13 — P2a: Reindex outbox, worker, chunking and embeddings

## Goal
Keep a search index of the store's content current, rebuilding only what changed, in a
separate worker (brief §11, §6, §19 P2). Blocks GH-14 (hybrid search) and GH-15 (admin
index status). Ticket: https://github.com/Sergiu1809/shopy/issues/13

## Context brief 🧾
- **Acceptance criteria (approved, GH-13; ticket text + gate A answers 2026-11-26, user: every recommendation accepted):**
  - [ ] **Migration 0002 + models** in `app/models/` (PATTERN-014; drift test green; `tests/test_migrations.py` `TABLES` grows):
    - `kb_chunks`: id, store_id, source_type (`product`/`reviews`/`policy`, text + CHECK), source_id, chunk_index, text, embedding `vector(1536)`, tsv `tsvector` **nullable, left NULL** (GH-14 owns the text search config and the fill; B5), source_version **nullable** (NULL for reviews; N2), content_hash.
    - `reindex_outbox`: id, source_type, source_id, reason (text + CHECK `create`/`update`/`delete`/`full`; N3), enqueued_at, locked_at, attempts, last_error, done_at. **No unique index** on pending rows: duplicates allowed (N4).
    - `usage_ledger`: id, user_id (nullable FK → users, `ON DELETE SET NULL`, indexed), provider (`openai`), operation (CHECK: only `embedding` until P3), units (bigint tokens), estimated_cost_eur `numeric(12,8)`, created_at (indexed, for the daily sum) (N13, B3).
  - [ ] **Outbox hooks** (PATTERN-010) in `backend/app/api/admin.py`: one row in the same transaction exactly when a product is created/deleted or `products.version` bumps (product update; variant create/delete; variant `sku`/`attributes` change). Source `product`. Price/stock-only changes and unchanged PATCHes insert none.
  - [ ] **Product delete** (B6): enqueues one `product` row (`reason=delete`). Whenever a source no longer exists, the worker deletes its chunks (for a product: its `product` and `reviews` chunks) and marks the row done.
  - [ ] **Product chunk** (B1), one chunk, Romanian labels, one field per line: `Nume: …`, `Marcă: …`, `Categorie: <categories.name>`, one `<attr_key>: <value>` line per product attribute (keys as stored), `Descriere: …`, `Variante: <key>: <distinct values, comma-separated>; …` (distinct values per variant attribute key). Never SKU, price, stock or rating. `source_version` = `products.version`.
  - [ ] **Reviews chunks** (B2), source_id = product_id, ordered `created_at`, `id`: each review `[#<id>] <rating>/5 — <title>: <body>`, no author name, no product name (so a product edit never reindexes its reviews). Split only at review boundaries, ≤ 2000 characters per chunk; a single longer review is its own chunk. `source_version` NULL.
  - [ ] **Policy chunks** (B2): one per policy; split at blank lines only when > 2000 characters. `source_version` = `store_policies.version`.
  - [ ] **content_hash** (N1): SHA-256 hex of `EMBEDDING_MODEL + "\n" + chunk text`. The worker reuses an existing embedding of the same source with the same hash (no API call). The worker also sets `products.content_hash` to the product chunk's hash, without touching `version` or `updated_at`.
  - [ ] **Worker** (`backend/worker/`, async, `app.db.create_engine`; N6, N7): claims the oldest due row with `SELECT … FOR UPDATE SKIP LOCKED`, one row per transaction, the transaction held during the embedding call; rebuilds that source only; replaces its chunks atomically; sets done_at. Errors are recorded in a separate transaction. Idle poll every 2 s, drains back to back when busy (constants in code, no new env). Missing tables (api not migrated yet) → log and retry.
  - [ ] **Retries** (N5): 5 attempts; a failed row is due again at `locked_at + 30 s × 2^(attempts−1)`; after the 5th failure it is given up (done_at NULL, last_error kept). A new change inserts a new row.
  - [ ] **Embeddings** (PATTERN-012, D-009; N10): a provider interface; OpenAI implementation (official `openai` SDK, model from `EMBEDDING_MODEL`); a stub for tests and CI. One API call per source (all its chunks). A vector whose length is not 1536 is an error (row retried). No `dimensions` override.
  - [ ] **Cost** (PATTERN-011, D-019; B3, N8, N9): before each call, the global spend of the current UTC day (all providers) is compared with `DAILY_COST_CAP_EUR` (default 1 EUR when unset, Q-013); spend ≥ cap → no call. After the call, one `usage_ledger` row: provider `openai`, operation `embedding`, units = `usage.total_tokens`, `estimated_cost_eur` = tokens × `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS` / 1e6, user_id NULL. Cap reached, price unset, or `OPENAI_API_KEY` unset → no call, the row stays pending, attempts not incremented, last_error says why (e.g. "daily cost cap reached"), re-checked on later polls. A provider error (401 etc.) counts as an attempt.
  - [ ] **Config**: `.env.example` gains `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS=` (no value; the developer sets 0.02 in `.env`), and the comment "names defined with the usage ledger in P3" is updated. `DAILY_COST_CAP_EUR` default 1 documented (Q-013).
  - [ ] **Full reindex** (B4): `enqueue_full_reindex(session)` (every product, every product's reviews, every policy; `reason=full`), plus a single-source enqueue, both usable by GH-15. `seed.load` calls it in its transaction when it inserts the catalog. `make reindex` runs `python -m worker.reindex_all` (enqueues a full reindex), for databases seeded before P2a.
  - [ ] **Dependencies** (N11): `openai` and `pgvector` added to `backend/pyproject.toml`.
  - [ ] **Tests**: test 20 (brief §17): updating a product enqueues exactly that product; the worker reindexes only it; unchanged content skips the embedding call. Worker half of test 22: cap reached → no provider call. CI never calls OpenAI: tests inject the stub, and a guard fails if the OpenAI provider is constructed in a test run (N12).
- **Out of scope:** search, the text search configuration, the tsv fill and the HNSW index (GH-14); admin index routes (GH-15); per-user caps, LLM/STT/TTS costs, the limit message (P3); typed attributes (Q-016); review or policy write routes (none exist; the seed and the full reindex cover them); archive instead of delete (Q-017).
- **Tickets covered:** GH-13 (Fixes)
- **Constraints that apply:**
  - D-004 — one Postgres database; the outbox is the queue; no Redis or broker.
  - D-006 — transactional outbox, SKIP LOCKED worker, hash skip; price and stock never indexed.
  - D-009 — embeddings are OpenAI `text-embedding-3-small`; model name from env.
  - D-010 — no price, stock or totals in chunk text.
  - D-019 — every paid call writes to usage_ledger; global daily cap; at the cap, no paid call.
  - D-021 — code and docs in English; chunk text is Romanian catalog data with Romanian labels (B1).
  - D-024 — bigint identity primary keys.
  - PATTERN-008 — bound parameters; schema only through Alembic; timestamptz; `store_id` on kb_chunks.
  - PATTERN-010 — enqueue in the same transaction; never call the embedding API from a request handler.
  - PATTERN-011 — check the cap before the call; write a ledger row after it; prices from `PRICE_*`.
  - PATTERN-012 — provider interface; stub in tests and CI.
  - PATTERN-013 — keys and prices only in `.env`; names in `.env.example`.
  - PATTERN-014 (candidate) — models, one reviewed revision, text + CHECK, drift test.
  - PATTERN-015 (candidate) — API tests with httpx `AsyncClient` + `ASGITransport`.
  - PATTERN-017 (candidate) — enqueue exactly when the product version moves.
  - Q-013 — daily cap default 1 EUR until answered. Q-016, Q-017 — out of scope.
- **Where the code is:** `backend/app/models/indexing.py`, `usage.py` (new models) · `backend/migrations/versions/0002_indexing_and_usage.py` · `backend/app/indexing/` (`outbox.py` enqueue + full reindex, `chunking.py` pure text rules, `embeddings.py` provider interface + OpenAI) · `backend/app/usage/ledger.py` (cap, prices, ledger row) · `backend/worker/` (`process.py` claim/rebuild/error, `__main__.py` loop, `reindex_all.py`) · `backend/app/api/admin.py` (six hooks) · `backend/seed/seed.py` · `Makefile` (`reindex`) · `.env.example` · `backend/pyproject.toml` + `uv.lock` · `backend/tests/` (`conftest.py` guard + `indexing_db`, `stubs.py`, new `test_*` files; extended sets in `test_migrations.py`, `test_schema.py`) · docs: `ARCHITECTURE.md`, `AGENTS.md` §2–§3, `PATTERNS.md`, `CONTRACTS.md` (External OpenAI evidence), `MANUAL-TESTS.md` (MT-002). Unchanged: `docker-compose.yml`, `docs/API.md`, C-001.
- **Ownership:** integration owner: conductor · one builder (planner confirmed: parts share the models, migration, conftest and lock file; see PLAN.md Sequencing)
- **Verify with:** `cd backend && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run python -m seed.validate_catalog && uv run pytest` (DB tests need Docker) · `python3 docs/agents/tools/ledger-lint.py` · MT-002 (below; manual, developer only)

## Resume here ⏯
Built and reviewed (round 1: pass, nits only); 715 passed. At gate C: the user decides the nits, runs MT-002 (real OpenAI key), re-confirms PATTERN-010/011/012, and says when to mark PR #16 ready. See `log_2026-11-26_2130.md`.

## Summary of work so far
- 2026-11-26 — Product owner coverage report; gate A answered: every recommendation (B1–B6, N1–N14) accepted.
- 2026-11-26 — planner: PLAN.md (size L); gate B approved with A1–A11; D-019, PATTERN-011, PATTERN-017 confirmed.
- 2026-11-26 — tests first: 111 tests, 168 cases, red; A11 additions to test_migrations/test_schema; MT-002 queued (b8a347f).
- 2026-11-26 — builder: 0002, outbox hooks, chunking, provider, ledger, worker, make reindex, docs, PATTERN-018/019 (3884147..e60bcf2); 715 passed; 0 assertions changed; 2 mechanical test fixes (b1f4dde).
- 2026-11-26 — review round 1: pass with 5 nits; images build in Docker; SIGTERM checked live.

## Approach
See `PLAN.md` (planner, 2026-11-26; awaiting gate B). Tests: `TESTS.md` (test author).

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| add | docs/agents/tasks/GH-13/OVERVIEW.md | Context brief from gate A |
| add | docs/agents/tasks/GH-13/PLAN.md | Plan, approved at gate B |
| add | docs/agents/tasks/GH-13/TESTS.md | acceptance points → tests |
| add | backend/tests/test_chunking.py, test_embeddings.py, test_usage_ledger.py, test_indexing_schema.py, test_outbox_hooks.py, test_worker.py, test_reindex_all.py, stubs.py, indexing_data.py | tests first |
| modify | backend/tests/conftest.py, test_seed_load.py, test_migrations.py, test_schema.py | fixtures, guard; A11 additions |
| add | backend/app/models/indexing.py, usage.py; migrations/versions/0002_indexing_and_usage.py | three tables |
| add | backend/app/indexing/ (outbox, chunking, embeddings), backend/app/usage/ledger.py | indexing and cost |
| add/modify | backend/worker/process.py, __main__.py, reindex_all.py | the worker |
| modify | backend/app/api/admin.py, backend/seed/seed.py | outbox hooks |
| modify | backend/pyproject.toml, uv.lock, Makefile, .env.example | deps, `make reindex`, price name |
| modify | AGENTS.md, docs/agents/ARCHITECTURE.md, PATTERNS.md, CONTRACTS.md, MANUAL-TESTS.md | docs, PATTERN-018/019, MT-002 |

## Manual verification 🔧
- **MT-002 (approved at gate A, to be added to `docs/agents/MANUAL-TESTS.md` by the conductor or test author):** `docker compose up --build`, then `make seed` with a real `OPENAI_API_KEY` and `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS=0.02`: kb_chunks fill for the 200 products, their reviews and the 5 policies; usage_ledger rows appear; a second full reindex (`make reindex`) makes no new paid call. Environment: desktop (Windows, Docker Desktop + WSL2). Status: not run. Only the person who runs it reports the result.

## Decisions log 🧭
- **2026-11-26 — B1 Product chunk: Romanian labels, one field per line; variant summary = distinct values per variant attribute key; no SKU, price, stock or rating; category = `categories.name`** — Why: catalog data and queries are Romanian; price/stock read live (D-006). Rejected: English labels; values without labels.
- **2026-11-26 — B2 Review IDs inside the text (`[#<id>] <rating>/5 — <title>: <body>`), no author; split at review boundaries ≤ 2000 chars; policies one chunk, split at blank lines if > 2000** — Why: keeps the brief §7 columns; a review is never cut. Rejected: a `review_ids bigint[]` column.
- **2026-11-26 — B3 `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS`, value 0.02 (user, in `.env`); unset → no call; cost = total_tokens × price / 1e6, `numeric(12,8)`** — Why: a price of 0 would disable the cap; EUR costs are fractions of a cent (PATTERN-001 covers RON). Rejected: a default price in code.
- **2026-11-26 — B4 Seed enqueues a full reindex when it inserts the catalog, plus `make reindex`** — Why: PATTERN-010 for seeded content; existing databases seeded before P2a. Rejected: only one of the two.
- **2026-11-26 — B5 tsv nullable and left NULL in P2a; GH-14 owns the config and the fill** — Why: no throwaway fill; the language config stays in one ticket. Rejected: fill with built-in `romanian`; move the config into P2a.
- **2026-11-26 — B6 Product delete enqueues one row; the worker removes the chunks of a missing source** — Why: one row per change, one deletion path. Rejected: deleting chunks in the route.
- **2026-11-26 — N1–N14 defaults accepted as proposed** (hash input, NULL source_version for reviews, reason values, duplicates allowed, 5 attempts with 30 s exponential backoff, row lock held during the call, async worker polling 2 s, cap/key/price missing leaves rows pending, one call per source and a 1536 check, `openai` + `pgvector` dependencies, CI guard against the real provider, usage_ledger columns, MT-002).

## Open questions / blockers
- [ ] Q-013 — daily cap vs monthly budget (default 1 EUR/day; not blocking).

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/13
- PR: https://github.com/Sergiu1809/shopy/pull/16
