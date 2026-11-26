# Plan — GH-13 P2a: Reindex outbox, worker, chunking and embeddings

> Written by /plan (planner agent, 2026-11-26); the gate B calls are recorded below by /start.

## Size
**L.** Three new tables in one revision (`0002`), two new packages (`app/indexing/`,
`app/usage/`), a real worker replacing the idle placeholder (claim, rebuild, retry,
cost gate, separate transactions), hooks in six admin routes, the seed, `make
reindex`, two dependencies, and about 60 tests, most of which need committed
transactions (not the rolled-back `session`). No UI, no new REST route, no contract
change. What makes it L rather than M: the transaction design of the worker (row lock
held across a paid call, the ledger and the error each in their own transaction) and
the number of exact text rules (B1, B2) that need golden tests.

## Repos · branches
`feat/reindex-worker-GH-13` (draft PR #16 into `main`)
Tickets covered: GH-13 (Fixes)

## Approach

### Module layout (brief §6; ARCHITECTURE "Parts")
| Module | Holds | Used by |
|---|---|---|
| `app/models/indexing.py` | `KbChunk`, `ReindexOutbox` | all below |
| `app/models/usage.py` | `UsageLedger` | `app/usage/` |
| `app/indexing/outbox.py` | `enqueue(session, source_type, source_id, reason)`, `enqueue_full_reindex(session) -> int`; the `SOURCE_TYPES` / `REASONS` tuples the CHECKs use | `app/api/admin.py`, `seed/seed.py`, `worker/reindex_all.py`, GH-15 |
| `app/indexing/chunking.py` | pure text: `product_text(...)`, `review_chunks(...)`, `policy_chunks(...)`, `content_hash(model, text)`, `MAX_CHUNK_CHARS = 2000` | worker; no DB, no I/O |
| `app/indexing/embeddings.py` | `EmbeddingProvider` (Protocol), `EmbeddingResult`, `EMBEDDING_DIM = 1536`, `OpenAIEmbeddingProvider`, `check_vectors(...)` | worker; GH-14 (query embedding) |
| `app/usage/ledger.py` | `daily_cap_eur(env)`, `unit_price_eur(env, name)`, `spent_today_eur(session)`, `estimate_cost_eur(units, price_per_1m)`, `record(session, ...)`; `ConfigError` | worker; P3 (LLM/STT/TTS) |
| `worker/process.py` | `IndexingConfig.from_env(env)`, `process_next(sessionmaker, provider, config) -> Outcome`, the claim query, the per-source rebuild, the error transaction | `worker/__main__.py`, tests |
| `worker/__main__.py` | the async loop, signals, provider construction from env | Compose `worker` |
| `worker/reindex_all.py` | `python -m worker.reindex_all`: `enqueue_full_reindex` in one transaction, prints the count | `make reindex` |

`app/indexing/` holds what GH-14 and GH-15 reuse (enqueue, chunk text rules,
provider); the transaction-heavy row processing stays in `worker/` because only the
worker process runs it.

### Schema (migration `0002`, PATTERN-014)
Models first, then `alembic revision --autogenerate -m "indexing and usage ledger"`
renamed to `0002_indexing_and_usage.py` (`revision = "0002"`, `down_revision =
"0001"`), reviewed by hand. Downgrade drops the three tables and keeps the extensions
(as 0001, Q10).
- **`kb_chunks`**: `id` bigint identity; `store_id` FK → `stores` `RESTRICT`, own
  index `ix_kb_chunks_store_id` (every FK leads an index); `source_type` text +
  `ck_kb_chunks_source_type` (`product`/`reviews`/`policy`); `source_id` bigint (no
  FK: the three source tables differ, and chunks of a deleted source must survive until
  the worker removes them, B6); `chunk_index` integer; `text` text; `embedding`
  `pgvector.sqlalchemy.Vector(1536)` NOT NULL; `tsv` `TSVECTOR` NULL (B5);
  `source_version` integer NULL (N2); `content_hash` text NOT NULL.
  `UniqueConstraint("source_type", "source_id", "chunk_index")` → `uq_kb_chunks_source_type`
  (assumption A1).
- **`reindex_outbox`**: `id`; `source_type` text + CHECK (same three values);
  `source_id` bigint (no FK, B6); `reason` text + CHECK (`create`/`update`/`delete`/`full`);
  `enqueued_at` timestamptz `now()`; `locked_at` timestamptz NULL; `attempts` integer
  default 0; `last_error` text NULL; `done_at` timestamptz NULL. No unique index (N4),
  no other index (see Risks).
- **`usage_ledger`**: `id`; `user_id` FK → `users` `SET NULL`, NULL, indexed;
  `provider` text (no CHECK, as the criterion lists none; assumption A2); `operation`
  text + `ck_usage_ledger_operation` (`embedding`); `units` bigint; `estimated_cost_eur`
  `numeric(12,8)`; `created_at` timestamptz `now()`, indexed.
- `app/models/__init__.py` exports the three models (Alembic and the drift test see them).
- The `vector` extension already exists from 0001.

### Outbox hooks (PATTERN-010, PATTERN-017)
`enqueue()` is `session.add(ReindexOutbox(...))`: it joins the caller's transaction
and is discarded by its rollback. In `app/api/admin.py`, exactly where
`products.version` moves today:
| Route | Where | reason |
|---|---|---|
| `create_product` | after `flush()` (needs `product.id`), before `commit()` | `create` |
| `update_product` | inside `if changes:` | `update` |
| `delete_product` | after the `DELETE … RETURNING` found a row | `delete` |
| `create_variant` | next to `product.version = …`, before `_flush_sku` | `update` |
| `update_variant` | inside `if changes.keys() & DESCRIPTIVE_VARIANT_FIELDS` | `update` |
| `delete_variant` | after the variant was found, next to the version bump | `update` |
All `source_type="product"`. A 409 on SKU rolls the session back, so the row goes
with it. Price/stock-only and unchanged PATCHes reach no `enqueue`. The module
docstring gains one line: "every `products.version` bump enqueues the product (P2)".

### Full reindex and the seed (B4)
`enqueue_full_reindex(session)` runs three `INSERT … SELECT` statements (SQLAlchemy
`insert(ReindexOutbox).from_select(...)`): `('product', id)` and `('reviews', id)`
for every product, `('policy', id)` for every policy, all `reason='full'`; returns the
number of rows. `enqueue(...)` is the single-source enqueue for GH-15.
`seed.load` calls `enqueue_full_reindex(session)` at the end of `_insert_catalog`
(same transaction; a rerun with the store present inserts no catalog and enqueues
nothing). `worker/reindex_all.py` opens `create_engine()`, runs it in `session.begin()`,
prints `Reindex: enqueued N sources.` Makefile: `reindex: docker compose run --rm api
python -m worker.reindex_all` (same image and `.env` as `make seed`; `.PHONY` updated).

### Chunk text (B1, B2; pure functions, golden tests)
- **Product** (one chunk): lines joined by `\n`, in this order: `Nume: <name>`,
  `Marcă: <brand>`, `Categorie: <categories.name>`, one `<key>: <value>` per product
  attribute in sorted key order, `Descriere: <description>`, `Variante: <k1>: <v1>, <v2>;
  <k2>: …`. Variant keys sorted; values distinct in variant `id` order. No `Variante`
  line when no variant has an attribute. Value rendering (assumption A3): text as is,
  int as decimal, bool `da`/`nu`, list items joined by `, `. Never SKU, price, stock,
  rating. `source_version = products.version`.
- **Reviews** (`source_id` = product id): reviews ordered `created_at, id`; each
  `[#<id>] <rating>/5 — <title>: <body>`; packed greedily into chunks joined by `\n`
  while the chunk stays ≤ 2000 characters; a single review > 2000 is its own chunk;
  no reviews → no chunks. `source_version` NULL.
- **Policy**: text `<title>\n\n<body>` (assumption A4); ≤ 2000 → one chunk; else split
  at blank lines (`\n\n`), paragraphs packed greedily ≤ 2000, a longer paragraph alone.
  `source_version = store_policies.version`.
- `content_hash = sha256((model + "\n" + text).encode()).hexdigest()` (N1).

### Provider (PATTERN-012, D-009, N10, N12)
```python
@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    total_tokens: int

class EmbeddingProvider(Protocol):
    provider: str          # ledger value, "openai"
    model: str
    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...
```
`OpenAIEmbeddingProvider(api_key, model, client=None)`: builds
`openai.AsyncOpenAI(api_key=..., timeout=OPENAI_TIMEOUT_SECONDS)` only when no
client is passed; `embed` calls `client.embeddings.create(model=model, input=list(texts))`
(no `dimensions`), returns vectors in `data[i].index` order and `usage.total_tokens`.
Any `openai.APIError` is re-raised as `EmbeddingError("openai <ExceptionClass>
(<status>)")`, never with the SDK message (it can quote a masked key), so the worker
needs no `openai` import. It does not check sizes: the worker writes the ledger row first (the call was paid),
then `check_vectors(result, n)` raises `EmbeddingError` when the count differs or any
length ≠ 1536.
**Stub** in `backend/tests/stubs.py` (`StubEmbeddingProvider`): deterministic 1536-float
vectors from the text's SHA-256, records every call's texts, configurable
`total_tokens`, optional `dim`, `fail_with` and a `gate: asyncio.Event` to hold a call
open. Tests pass it to `process_next` directly; nothing chooses it by env.
**Guard** (in `tests/conftest.py`, autouse): `monkeypatch` replaces
`app.indexing.embeddings.AsyncOpenAI` with a function that calls `pytest.fail("real
OpenAI client constructed in a test")`, and `OPENAI_API_KEY` is removed from
`os.environ` at import. `OpenAIEmbeddingProvider`'s request shape is tested with an
injected fake client (assumption A5: the guard sits on the real client, which is what
N12 protects against). A test proves the guard fires.

### Cost gate and ledger (PATTERN-011, D-019, B3, N8, N9)
Only when a source needs at least one new embedding, in this order, each failure
leaving the row pending with `last_error` set and `attempts` unchanged ("blocked"):
`EMBEDDING_MODEL` unset → "EMBEDDING_MODEL is not set" (it is also the hash input, so
it is checked before chunking; assumption A6); `OPENAI_API_KEY` unset → "OPENAI_API_KEY
is not set"; `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS` unset/empty →
"PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS is not set", not a number or ≤ 0 → "… is
invalid"; `DAILY_COST_CAP_EUR` unset/empty → 1 EUR, not a number or < 0 → "… is
invalid" (fail closed; assumption A7); `spent_today_eur ≥ cap` → "daily cost cap
reached". Values are named, never echoed.
`spent_today_eur`: `SELECT coalesce(sum(estimated_cost_eur), 0) FROM usage_ledger
WHERE created_at >= date_trunc('day', now(), 'UTC')` (all providers, `Decimal`).
After a successful call: `record(...)` in **its own session and transaction,
committed at once** (provider `openai`, operation `embedding`, units =
`total_tokens`, cost = `Decimal(tokens) * price / 1_000_000` quantized to 8 places,
user_id NULL), so a paid call is recorded even if the row's transaction later fails.
Env is read per row through `IndexingConfig.from_env(os.environ)` (cheap; satisfies
"re-checked on later polls"); tests build `IndexingConfig` directly.

### Worker: one row (N5, N6, N7)
`process_next(sessionmaker, provider, config)`:
1. **Claim** in transaction T1:
   `select(ReindexOutbox).where(done_at IS NULL, attempts < 5, or_(attempts == 0,
   locked_at + interval '30 seconds' * power(2, attempts - 1) <= now()))
   .order_by(enqueued_at, id).limit(1).with_for_update(skip_locked=True)`.
   No row → `Outcome.IDLE`. Set `locked_at = now()`.
2. **Load the source** in T1 (plain reads, no extra locks): product + category name +
   variants; or the product's reviews; or the policy. Missing source → delete its
   chunks (product: `product` and `reviews` chunks; reviews: `reviews` chunks; policy:
   its chunks), `done_at = now()`, commit → `DONE`.
3. **Build** the chunk texts and hashes. Read the existing chunks of this source
   (`content_hash → embedding`); every new chunk whose hash exists reuses that vector.
4. **Texts still needing a vector** → none: no call. Otherwise the cost gate above;
   blocked → set `last_error`, commit T1 → `BLOCKED`. Else **one** `provider.embed(...)`
   with all of them, **while T1 and its row lock stay open**; ledger row in its own
   transaction; `check_vectors`.
5. **Replace atomically** in T1: `DELETE` this source's chunks, `INSERT` the new ones
   (`store_id` from the product/policy, `tsv` NULL); for a product source,
   `update(Product).where(id).values(content_hash=<product chunk hash>,
   updated_at=Product.updated_at)` (the explicit `updated_at` stops its `onupdate`;
   `version` untouched); `done_at = now()`; commit → `DONE`.
6. **Any exception** in 2–5: roll back T1 (chunks untouched, lock released), then in a
   new transaction T2: `UPDATE reindex_outbox SET attempts = attempts + 1, locked_at =
   now(), last_error = <text> WHERE id = :id AND done_at IS NULL` → `FAILED`.
   `last_error` is the `EmbeddingError`/`ConfigError` message, otherwise
   `<ExceptionClass>: <message>`; cut to 500 characters (assumption A8). The 5th failure leaves `attempts = 5`: given up.
Success keeps a previous `last_error` (history; GH-15 shows it for pending and
given-up rows).

### Worker: loop
`worker/__main__.py`: `asyncio.run(run(...))`; `create_engine()` +
`create_sessionmaker`; SIGTERM/SIGINT set an `asyncio.Event` (via
`loop.add_signal_handler`); the provider is built once if `OPENAI_API_KEY` and
`EMBEDDING_MODEL` are set, else `None` (blocked rows say why). Loop: `DONE`/`FAILED` →
next row at once (drain); `IDLE`/`BLOCKED` → wait `IDLE_SECONDS = 2` or the stop
event. A `DBAPIError` or `OSError` from `process_next` (tables missing before the api
migrated, db restarting) → log one English line ("reindex_outbox missing; waiting for
migrations" for an undefined table) and wait 2 s (assumption A9). The current row
finishes before the worker stops. Constants live in `worker/process.py`:
`MAX_ATTEMPTS = 5`, `BACKOFF_BASE_SECONDS = 30`, `IDLE_SECONDS = 2`; and
`OPENAI_TIMEOUT_SECONDS = 60` in `embeddings.py` (SDK retries left at its default).

### Dependencies (N11; repo convention `>=<major.minor today>,<next major>`, `0.x` → `<next minor>`)
`uv add "openai>=3.19,<4" "pgvector>=0.4,<0.5"` (the builder raises the lower bound
to the newest release `uv` resolves on the day and says so; the local uv cache shows
openai 3.19). `uv.lock` is committed; CI runs `uv sync --frozen`. `pgvector` pulls
`numpy`. If `pgvector` ships no type information, `[[tool.mypy.overrides]] module =
["pgvector.*"] ignore_missing_imports = true` (named in the PR).

### Config (PATTERN-013, Q-013)
`.env.example`, cost block becomes:
```
# Cost control
# DAILY_COST_CAP_EUR: global cap per UTC day, all providers; 1 when unset. Open: Q-013
DAILY_COST_CAP_EUR=
# Not decided yet
USER_DAILY_MESSAGE_CAP=
# PRICE_*: unit prices in EUR, never defaulted in code: unset means no paid call.
# Embeddings (P2): EUR per 1M tokens; set it in .env (developer: 0.02)
PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS=
# LLM, STT and TTS prices: names added in P3
```
No other variable. `OPENAI_API_KEY=change-me` stays as it is (see Risks).

### Rejected
- Calling the embedding API in the admin route or a background task of the api:
  PATTERN-010 forbids it.
- A `SELECT … FOR UPDATE` claim, commit, then embed outside a transaction (shorter
  lock): N6 chose holding the lock; it also keeps "claimed" and "done" atomic.
- Ledger row in T1: a later failure would roll back a paid call's record (D-019).
- Recording errors with a savepoint inside T1: N7 asks for a separate transaction.
- Stub embeddings chosen by an env variable: adds config nobody asked for; tests
  inject the stub.
- Partial index on pending outbox rows: no concrete need at demo scale (suggestion).

## Files
| Action | Path | What |
|---|---|---|
| edit | `backend/pyproject.toml`, `backend/uv.lock` | `openai`, `pgvector` (pins above); mypy override for `pgvector.*` only if needed |
| add | `backend/app/models/indexing.py` | `KbChunk`, `ReindexOutbox` |
| add | `backend/app/models/usage.py` | `UsageLedger` |
| edit | `backend/app/models/__init__.py` | export the three |
| add | `backend/migrations/versions/0002_indexing_and_usage.py` | the three tables, constraints, indexes; downgrade |
| add | `backend/app/indexing/__init__.py`, `outbox.py`, `chunking.py`, `embeddings.py` | as above |
| add | `backend/app/usage/__init__.py`, `ledger.py` | as above |
| edit | `backend/app/api/admin.py` | six `enqueue` calls; docstring line |
| edit | `backend/seed/seed.py` | `enqueue_full_reindex` at the end of `_insert_catalog`; module docstring line |
| edit | `backend/worker/__main__.py` | the async loop (replaces the idle placeholder) |
| add | `backend/worker/process.py` | `IndexingConfig`, `Outcome`, `process_next`, claim, rebuild, error transaction |
| add | `backend/worker/reindex_all.py` | `make reindex` entry point |
| edit | `Makefile` | `reindex` target |
| edit | `.env.example` | cost block above |
| edit | `backend/tests/conftest.py` | autouse OpenAI client guard; pop `OPENAI_API_KEY`; `indexing_db` fixture (committed DB per test, below) |
| add | `backend/tests/stubs.py` | `StubEmbeddingProvider` |
| edit | `backend/tests/test_migrations.py` | `TABLES` += 3; head `"0001"` → `"0002"` |
| edit | `backend/tests/test_schema.py` | `TABLES`, `EXPECTED`, `NULLABLE`, `FK_DELETE_RULES` (+ `kb_chunks.store_id` RESTRICT, `usage_ledger.user_id` SET NULL `"n"`), the `store_id` table set (+ `kb_chunks`) |
| add | `backend/tests/test_indexing_schema.py` | CHECKs, vector size, numeric(12,8), indexes |
| add | `backend/tests/test_outbox_hooks.py` | API tests (PATTERN-015) |
| add | `backend/tests/test_chunking.py` | pure golden tests |
| add | `backend/tests/test_embeddings.py` | provider request shape (fake client), `check_vectors`, guard |
| add | `backend/tests/test_usage_ledger.py` | cap parsing, price parsing, cost math, UTC-day sum |
| add | `backend/tests/test_worker.py` | `process_next` and the loop on a committed DB |
| add | `backend/tests/test_reindex_all.py` | `enqueue_full_reindex`, `worker.reindex_all.main` |
| edit | `backend/tests/test_seed_load.py` | add: first run enqueues a full reindex; rerun enqueues nothing (no existing assertion changes) |
| edit | `docs/agents/ARCHITECTURE.md` | status note (P2a), Parts (indexing, usage, worker real), State (kb_chunks without HNSW yet; usage_ledger written by the worker), Configuration (`PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS`, cap default 1) |
| edit | `AGENTS.md` | §2 `make reindex`; §3 "P2a adds the index outbox, worker, chunking and embeddings (GH-13)", `app/indexing/`, `app/usage/` |
| edit | `docs/agents/PATTERNS.md` | `Example` of PATTERN-010 (`admin.py`, `app/indexing/outbox.py`), PATTERN-011 (`app/usage/ledger.py`, `worker/process.py`), PATTERN-012 (`app/indexing/embeddings.py`, `tests/stubs.py`, guard in `conftest.py`); this removes the Confirmed lines of 010 and 012 (re-confirm at gate C). New candidates (next free IDs at build time): "Worker row: claim with SKIP LOCKED, paid-call ledger and error each in their own transaction"; "Tests guard against real provider clients" |
| edit | `docs/agents/CONTRACTS.md` | External · OpenAI: Evidence → `app/indexing/embeddings.py` |
| edit | `docs/agents/MANUAL-TESTS.md` | MT-002 in Queue (test author, approved at gate A) |
| — | `docker-compose.yml`, `docs/API.md`, `app/main.py`, C-001 | unchanged: the worker command stays `python -m worker`; no REST change |

## Acceptance points → tests
**Committed-DB fixture.** The worker opens several transactions and connections, so
its tests cannot use the rolled-back `session`. `indexing_db` (conftest): a
session-scoped template database migrated once through Alembic (sync fixture, as
`fresh_db_url`), then per test `CREATE DATABASE t_<uuid> TEMPLATE <template>`, dropped
after; async tests build their own engine and sessionmaker from the URL. Rows are
inserted with small helpers (store, category, product, variants, reviews, policy).

| # | Acceptance point | Test kind | Not automated? why |
|---|---|---|---|
| 1 | 0002 creates `kb_chunks`, `reindex_outbox`, `usage_ledger` with the listed columns, types, nullability, defaults; head is `0002`; round trip; no drift | schema: `test_migrations.py` (extended sets), `test_schema.py` (extended `EXPECTED`, `NULLABLE`, FK rules, `store_id` set, naming), `test_models_match_migration` | — |
| 2 | CHECKs: `source_type` ×2, `reason`, `operation`; `embedding` is `vector(1536)` (a 1535-length insert fails); `estimated_cost_eur` numeric(12,8); `created_at` and `user_id` indexed; no unique on pending outbox rows (two identical rows insert) | DB: `test_indexing_schema.py` (parametrized rejects/accepts) | — |
| 3 | Outbox row in the same transaction exactly when `products.version` moves: create, update, variant create/delete, variant `sku`/`attributes` → one `product` row with the right reason | API (PATTERN-015): `test_outbox_hooks.py` one test per route | — |
| 4 | Price-only, stock-only, empty and same-value PATCHes → no row; a 409 SKU → no row | API: `test_outbox_hooks.py` | — |
| 5 | Product delete → one row `reason=delete`; worker deletes that product's `product` and `reviews` chunks, marks done, makes no call | API + worker: `test_delete_enqueues_one_row`; `test_worker.py::test_missing_product_removes_its_chunks` (also missing policy) | — |
| 6 | Product chunk text exactly per B1 (order, labels, sorted keys, value rendering, `Variante` line, omitted when empty; no SKU/price/stock/rating) | unit golden: `test_chunking.py` | — |
| 7 | Reviews chunks per B2: format, order `created_at, id`, packing ≤ 2000, a long review alone, no author or product name, none without reviews | unit golden: `test_chunking.py` | — |
| 8 | Policy chunks: one ≤ 2000; split at blank lines when longer | unit: `test_chunking.py` | — |
| 9 | `content_hash` = SHA-256 of `model + "\n" + text`; `source_version` per type (product version, NULL, policy version) | unit + worker: `test_content_hash_formula`; `test_worker.py::test_chunks_store_version_and_hash` | — |
| 10 | **Test 20:** updating a product enqueues exactly that product; the worker reindexes only it (the other product's chunk rows keep their ids); unchanged content skips the call (stub records no call; chunks rewritten with the same vectors) | API part: `test_outbox_hooks.py::test_update_enqueues_exactly_that_product`; worker part: `test_worker.py::test_only_the_changed_product_is_reindexed`, `::test_unchanged_content_makes_no_call` | — |
| 11 | `products.content_hash` set to the product chunk hash; `version` and `updated_at` unchanged | worker: `test_product_hash_set_without_touching_version` | — |
| 12 | Claim: oldest due row first; `SKIP LOCKED`; lock held during the embedding call (a second connection's claim gets nothing, `FOR UPDATE NOWAIT` on the row fails, while the stub's `gate` is closed); one row per call of `process_next` | worker: `test_claims_oldest_due_row`, `test_lock_is_held_during_the_call` | — |
| 13 | Chunks replaced atomically: a failure after the call leaves the old chunks unchanged | worker: `test_failure_keeps_old_chunks` (stub returns 1535-length vectors) | — |
| 14 | Errors recorded in a separate transaction: `attempts + 1`, `locked_at` set, `last_error` names the class and status, no SDK message text | worker: `test_provider_error_counts_an_attempt` (stub `fail_with` an `EmbeddingError`); unit: `test_embeddings.py::test_sdk_error_becomes_embedding_error` (fake client raises an `openai.AuthenticationError` built offline; message has class and 401, not the SDK text) | — |
| 15 | Backoff: due again at `locked_at + 30 s × 2^(attempts−1)`; after the 5th failure given up (`done_at` NULL, `last_error` kept, never claimed); a new change inserts a new row that is processed | worker: `test_backoff_due_times` (move `locked_at` with SQL; parametrized attempts 1–4), `test_gives_up_after_five`, `test_new_row_after_give_up` | — |
| 16 | One call per source with all chunks needing vectors; a vector ≠ 1536 or a count mismatch is an error (retried); the request has no `dimensions` | worker + unit: `test_one_call_per_source` (reviews source with 2 chunks), `test_wrong_dimension_is_retried`; `test_embeddings.py::test_request_shape` (fake client) | — |
| 17 | **Test 22 (worker half):** spend ≥ cap → no provider call; row pending, attempts unchanged, `last_error` "daily cost cap reached"; processed on a later poll once allowed | worker: `test_cap_reached_makes_no_call` (ledger rows summing to the cap, and one from yesterday UTC that does not count) | — |
| 18 | Ledger row after the call: provider, operation, units = `total_tokens`, cost = tokens × price / 1e6 (8 places), user NULL; kept even when the row then fails | worker + unit: `test_ledger_row_after_call`, `test_ledger_row_survives_a_later_failure`; `test_usage_ledger.py::test_cost_math` | — |
| 19 | Price unset/invalid, key unset, model unset → no call, row pending, attempts unchanged, `last_error` names the variable (no value) | worker: parametrized `test_missing_config_blocks_without_an_attempt` | — |
| 20 | `DAILY_COST_CAP_EUR` unset or empty → 1 EUR; invalid → blocked; spend sums every provider for the current UTC day | unit + DB: `test_usage_ledger.py` | — |
| 21 | Missing tables → logged, retried, no crash; idle wait 2 s; drains back to back; stops on the event | worker: `test_missing_tables_are_retried` (`process_next` on a fresh unmigrated DB inside `run` with a fake sleep), `test_loop_drains_then_idles` | — |
| 22 | `enqueue_full_reindex`: every product ×2 + every policy, `reason=full`; returns the count; single-source `enqueue` | DB: `test_reindex_all.py` | — |
| 23 | Seed first run enqueues the full reindex in its transaction; rerun enqueues nothing | DB (sync, as the seed tests): `test_seed_load.py` new tests | — |
| 24 | `make reindex` enqueues a full reindex | `test_reindex_all.py::test_main_enqueues` (calls `worker.reindex_all.main`) | the `make`/Compose wiring itself: MT-002 |
| 25 | CI never calls OpenAI: constructing the real client in a test fails | unit: `test_embeddings.py::test_real_client_is_guarded` | — |
| 26 | `.env.example` lists the price name without a value; cap comment | reviewed at gate C | doc review |
| 27 | Real embeddings fill the index for 200 products, their reviews, 5 policies; ledger rows; a second full reindex makes no paid call | — | **MT-002** (desktop, real key; only the developer runs it) |

Existing tests that stay green unchanged: `test_admin_products.py`,
`test_admin_access.py`, `test_seed_load.py` (existing tests), `test_constraints.py`,
`test_errors.py`. The extended expectation sets in `test_migrations.py` and
`test_schema.py` only add the new tables; no existing expectation is removed or
weakened (gate B call below).

## Sequencing
**One builder.** The parts are not disjoint: the models, migration and schema tests
are what every other part imports; the worker ties chunking, provider, ledger and
outbox together; and `conftest.py`, `app/models/__init__.py`, `pyproject.toml` and
`uv.lock` are shared. Parallel workers would collide on those files and their
integration would be the riskiest step. Chunking is pure and could run alone, but it
is about a tenth of the work. Order:
1. Test author: all tests above red (imports fail or assertions fail); MT-002 entry.
2. Builder: dependencies → models + 0002 (schema tests green) → `outbox.py` + admin
   hooks + seed → `chunking.py` → `embeddings.py` + `usage/ledger.py` →
   `worker/process.py` → loop + `reindex_all.py` + Makefile + `.env.example` → docs and
   ledger (`ledger-lint.py --fix`).

## Manual test plan
**MT-002** (approved at gate A; the test author adds it to `docs/agents/MANUAL-TESTS.md`
Queue, status 🔴): on the desktop, set a real `OPENAI_API_KEY` and
`PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS=0.02` in `.env`; `docker compose down -v`
(fresh db) and `docker compose up --build`; `make seed`; watch `docker compose logs
worker` until idle; check `SELECT source_type, count(DISTINCT source_id) FROM kb_chunks
GROUP BY 1` → product 200, reviews ≤ 200 (products with reviews), policy 5; `SELECT
count(*), sum(units), sum(estimated_cost_eur) FROM usage_ledger` → rows, cost well
under 1 EUR; `SELECT count(*) FROM reindex_outbox WHERE done_at IS NULL` → 0; then
`make reindex`, wait, and the `usage_ledger` count is unchanged. Only the developer
reports the result.

## Design (UI only)
Not applicable: no screen.

## Risks
- **pgvector with asyncpg and Alembic.** The `Vector` bind may need asyncpg's codec
  (`pgvector.asyncpg.register_vector` on connect), and the drift test may report the
  vector column if reflection loses the dimension. Fallback: register the codec in
  `create_engine` only if needed; a named, justified exclusion in
  `test_models_match_migration` (its comment allows one). The builder reports which.
- **The lock across a paid call** holds a transaction for up to the 60 s timeout; an
  admin write to the same product only waits on the final `UPDATE products …`, which
  runs after the call. A crash mid-call leaves the row due again without an attempt
  counted; a call that crashes the process every time would repeat (unlikely; noted).
- **Inconsistent reads.** The worker reads product, variants and category without
  locks; an admin commit between two reads can give a mixed chunk. That commit also
  enqueued a row, so the next row fixes it.
- **Blocked rows** are oldest-first: while the cap is reached, rows behind a blocked
  row that would need no call (a delete) wait too. The cap resets at UTC midnight;
  acceptable at demo scale.
- **`OPENAI_API_KEY=change-me`** in `.env.example` counts as set: with a price set and
  the placeholder key, each row fails with 401 and is given up after 5 attempts (no
  cost). `make reindex` recovers. Treating `change-me` as unset would be a new rule
  (suggestion only).
- **The outbox only grows** (done rows stay); ~405 rows per full reindex. A partial
  index or cleanup is a later suggestion.
- **Seed duration** grows a little (three `INSERT … SELECT`); no test depends on it.
- Hard to reverse: nothing; 0002 downgrades cleanly.

## Out of scope
Search, the text search config, the `tsv` fill and the HNSW index (GH-14); admin index
routes and status (GH-15); per-user caps, LLM/STT/TTS costs, the limit message (P3);
typed attributes (Q-016); review and policy write routes (none exist); archive instead
of delete (Q-017); outbox cleanup; a second worker process.

## Knowledge used
Confirmed before, unchanged (11): D-004, D-006, D-009, D-010, D-021, D-023, D-024,
PATTERN-008, PATTERN-010, PATTERN-012, PATTERN-013 — each obeyed as written (single
DB, outbox + SKIP LOCKED + hash skip, OpenAI embeddings with the model from env, no
price/stock in chunks, English code with Romanian catalog text, deterministic seed,
bigint identity keys, bound SQL through Alembic with `store_id` on `kb_chunks`,
enqueue in the same transaction, provider interface with a test stub, keys and prices
only in `.env`).

| Entry | What it says | Why it applies here | Call (confirm / wrong / outdated / answered) | Date |
|---|---|---|---|---|
| D-019 | Every paid call writes to `usage_ledger`; global cap 1 EUR/day; at a cap no paid call | the cap check before each embedding call and the ledger row after it; the limit message is P3 (no user here) | confirm | 2026-11-26 |
| PATTERN-011 | Check caps before the call; ledger row after; prices from `PRICE_*` | `app/usage/ledger.py` and step 4 of the worker; per-user caps do not apply (no user, P3) | confirm | 2026-11-26 |
| PATTERN-014 (candidate, confirmed 2026-11-26) | models, one reviewed revision, text + CHECK, FK leads an index, drift test | 0002 and the three models | confirm | 2026-11-26 |
| PATTERN-015 (candidate, confirmed 2026-11-26) | API tests with `AsyncClient` + `ASGITransport`, rolled-back session | the outbox hook tests; the worker tests use a committed DB instead (they need several transactions) | confirm | 2026-11-26 |
| PATTERN-016 (candidate, confirmed 2026-11-26) | one JSON type per attribute key; str, int, bool, lists | product chunk value rendering (A3) | confirm | 2026-11-26 |
| PATTERN-017 (candidate) | lock, diff, `version = version + 1` only on real change | the hooks sit exactly at these bumps (criterion) | confirm | 2026-11-26 |
| C-001 (confirmed 2026-11-26) | REST shapes and errors | relied on, unchanged: the hooks change no response; consumers: none to change | confirm | 2026-11-26 |
| External · OpenAI | `text-embedding-3-small`, 1536 dimensions | the 1536 check; Evidence moves to `embeddings.py` | confirm | 2026-11-26 |
| Q-013 | daily cap vs monthly budget, open | default 1 EUR when unset, as the criterion says | still open | 2026-11-26 |
| Q-016 | typed attributes, deferred | values rendered as stored; no typing | still deferred | 2026-11-26 |
| Q-017 | delete vs archive, open | hard delete stays; the worker removes a missing source's chunks | still open | 2026-11-26 |

### Considered, not applied
- PATTERN-001 — money in bani is RON; ledger costs are EUR fractions in `numeric(12,8)` (B3).
- D-005 — hybrid search is GH-14; nothing here searches.
- PATTERN-003 — quoting chunks as data happens when search results reach the LLM (P3); chunk text carries no instructions of its own.
- PATTERN-006 — no new REST or WebSocket input; env values are parsed by small functions with fixed messages.
- PATTERN-007 — no new route; the six routes keep the router-level admin dependency.
- PATTERN-012 "chosen by config" — the one real provider is built from env; the stub is injected by tests, not selected by env (rejected above).

### Assumptions (no entry behind them; each needs the user's call at gate B)
- **A1** `kb_chunks` unique on `(source_type, source_id, chunk_index)`: the worker reads and replaces chunks by source on every row; it also proves one chunk set per source.
- **A2** `usage_ledger.provider` has no CHECK (the criterion gives one only for `operation`); P3 adds `anthropic`/`azure` without a migration of that column.
- **A3** Attribute values in the product chunk: text as is, int as decimal, bool `da`/`nu`, list joined by `, `; attribute and variant keys sorted; variant values in variant `id` order. Lines joined by `\n`.
- **A4** Policy chunk text is `<title>\n\n<body>`. Review chunks are reviews joined by `\n`.
- **A5** The N12 guard fails when the real `AsyncOpenAI` client is built in a test (not our provider class), so the provider's request shape is tested with a fake client.
- **A6** `EMBEDDING_MODEL` unset blocks rows like a missing key (it is the hash input).
- **A7** Invalid `DAILY_COST_CAP_EUR` or price (not a number, price ≤ 0, cap < 0) blocks calls with a message naming the variable (fail closed).
- **A8** `last_error`: `openai <ExceptionClass> (<status>)` for provider errors (mapped in the provider), our message otherwise, max 500 characters; a later success keeps it.
- **A9** The loop logs and retries any DB connection or missing-table error every 2 s (not only missing tables), so a db restart does not stop the worker.
- **A10** `OPENAI_TIMEOUT_SECONDS = 60`, SDK retries at default.
- **A11** The test author extends the exhaustive sets in `test_migrations.py` and `test_schema.py` (tables, columns, nullable, FK rules, `store_id` tables) and the head revision `"0001"` → `"0002"`. Nothing existing is removed or weakened; this needs your explicit OK because AGENTS.md forbids changing existing assertions to make code pass.

No PROPOSAL: no approved decision, pattern or contract changes. Updating the
`Example` of PATTERN-010/011/012 is an evidence update (their Confirmed lines go;
re-confirm at gate C).

## Gate B
- Decision: approved — 2026-11-26 — the user approved the plan with A1–A11 ("ai departe", in reply to "approve the plan with A1–A11, including updating the two existing tests in A11?"). A11: the test author may extend the full-table lists in `test_migrations.py` and `test_schema.py` and the head revision "0001" → "0002"; nothing removed or weakened. Confirmed 2026-11-26 set on D-019, PATTERN-011, PATTERN-017 (candidate stays candidate).
