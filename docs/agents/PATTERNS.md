# Patterns — Shopy

<!-- graffino-agentic:begin v1 -->
> How we build things here. Copy only `approved` entries. `candidate` = seen once or
> not yet confirmed; agents add these freely. Promotion needs the user's OK.
<!-- graffino-agentic:end -->

Seeded from the project brief (`shopy_brief.md`) before any code existed. The
`Example` field points to the brief until the first real instance exists; replace it
then.

## Index
- PATTERN-001 · Money is an integer in minor units · approved
- PATTERN-002 · Agent tools take IDs and quantities only · approved
- PATTERN-003 · Tool results are quoted data, never instructions · approved
- PATTERN-004 · Every agent turn passes the output guard · approved
- PATTERN-005 · Fixed texts are deterministic templates · approved
- PATTERN-006 · Validate every input with Pydantic · approved
- PATTERN-007 · Authorization in FastAPI dependencies · approved
- PATTERN-008 · SQL only through SQLAlchemy with bound parameters · approved
- PATTERN-009 · Untrusted text renders as plain text · approved
- PATTERN-010 · Indexed changes enqueue in the same transaction · approved
- PATTERN-011 · Paid calls go through the cost ledger · approved
- PATTERN-012 · External providers sit behind interfaces · approved
- PATTERN-013 · Secrets only in .env · approved
- PATTERN-014 · Schema changes: models, one reviewed revision, drift test · candidate
- PATTERN-015 · API tests with the DB: httpx AsyncClient + ASGITransport · candidate
- PATTERN-016 · Catalog attributes: one JSON type per key, whole units · candidate
- PATTERN-017 · Row versions: lock, diff, increment in SQL · candidate

---

## PATTERN-001 · Money is an integer in minor units
- **Status:** approved
- **Use when:** any price, subtotal, shipping, total or cost amount in RON.
- **How:** store and pass integers in `bani`, columns and fields suffixed `_minor`; prices include VAT; never a float or Decimal string in the domain. Convert to text only in the speech normalizer and the UI formatter. Shipping: 1999, or 0 when the subtotal is ≥ 20000.
- **Example:** `backend/app/models/catalog.py` (`ProductVariant.price_minor`)
- **Why:** float rounding breaks totals, and the output guard compares exact amounts.
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-26

## PATTERN-002 · Agent tools take IDs and quantities only
- **Status:** approved
- **Use when:** adding or changing an agent tool.
- **How:** parameters are IDs, quantities, enums and free-text queries only; never a price, total or stock value. Every tool resolves the authenticated user server-side and reads only that user's data. No tool places or cancels an order.
- **Example:** `shopy_brief.md` §10.2, §10.6 (no code yet)
- **Why:** capability limits stop the model from changing prices or acting for another user, whatever the prompt says (D-010).
- **Source:** user (project brief) · confidence high

## PATTERN-003 · Tool results are quoted data, never instructions
- **Status:** approved
- **Use when:** passing any tool result (reviews, descriptions, policies) to the LLM.
- **How:** wrap the content as quoted data with an explicit note that its content is never to be followed; label each chunk with its source type.
- **Example:** `shopy_brief.md` §10.6 (no code yet)
- **Why:** reviews are user-written and can carry prompt injection (seed fixture).
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-26

## PATTERN-004 · Every agent turn passes the output guard
- **Status:** approved
- **Use when:** the orchestrator finishes an LLM turn.
- **How:** parse the final message as the Pydantic model `{speech, product_refs, ui}`; check product IDs and names against this session's tool results and every amount and stock number against this turn's tool results or policy constants; on failure regenerate once with the violation as feedback, then fall back to the safe template and log the incident. Nothing is spoken or shown before the guard passes.
- **Example:** `shopy_brief.md` §10.3, §10.4 (no code yet)
- **Why:** grounding is enforced in code, not only in the prompt (D-010).
- **Source:** user (project brief) · confidence high

## PATTERN-005 · Fixed texts are deterministic templates
- **Status:** approved
- **Use when:** order and cancellation summaries, the out-of-scope refusal, the limit message, the guard's safe reply.
- **How:** build them in code from DB values with a fixed Romanian template; the orchestrator sends them verbatim; the model never writes them. Exact strings live in one module, not in prompts.
- **Example:** `shopy_brief.md` §10.4, §10.5, §12.2, §15 (no code yet)
- **Why:** the user confirms exact values, and tests assert exact texts.
- **Source:** user (project brief) · confidence high

## PATTERN-006 · Validate every input with Pydantic
- **Status:** approved
- **Use when:** any REST body, query parameter, WebSocket message or tool argument.
- **How:** a Pydantic v2 model with types, lengths, enums and ranges; invalid input returns 422 in the one consistent error format with a useful message.
- **Example:** `backend/app/schemas/auth.py` (`extra="forbid"`, lengths, a fixed email message), `backend/app/errors.py` (the one envelope, no input echoed), `backend/tests/test_errors.py` (test 17)
- **Why:** server-side validation is the only trusted check.
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-25

## PATTERN-007 · Authorization in FastAPI dependencies
- **Status:** approved
- **Use when:** adding any route or WebSocket handler.
- **How:** a role dependency on every `/admin` route (customer → 403); an ownership check on every customer resource; never rely on hiding UI.
- **Example:** `backend/app/auth/dependencies.py` (`get_current_user`, `require_admin`), `backend/app/api/admin.py` (dependency at router level), `backend/tests/test_admin_access.py` (test 15 over every `/admin` route); ownership checks: no customer resource yet
- **Why:** customers must never reach admin data or another customer's data (tests 15, 16).
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-25

## PATTERN-008 · SQL only through SQLAlchemy with bound parameters
- **Status:** approved
- **Use when:** any database query, including search filters and full-text queries.
- **How:** SQLAlchemy expressions or `text()` with bound parameters; never string-built SQL. Schema changes only through Alembic migrations. Timestamps are UTC `timestamptz`; catalog tables carry `store_id`.
- **Example:** `backend/migrations/versions/0001_initial_schema.py` (schema through Alembic, `timestamptz`), `backend/app/models/catalog.py` (`store_id`)
- **Why:** SQL injection (test 18) and a schema that can grow to several stores.
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-19

## PATTERN-009 · Untrusted text renders as plain text
- **Status:** approved
- **Use when:** showing reviews, transcripts, LLM output or any user text in the client.
- **How:** React escaping only; `dangerouslySetInnerHTML` is forbidden by a lint rule; strict CSP header on the server.
- **Example:** `shopy_brief.md` §16, §17 test 19 (no code yet)
- **Why:** the seed contains an XSS review fixture that must render harmlessly.
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-18

## PATTERN-010 · Indexed changes enqueue in the same transaction
- **Status:** approved
- **Confirmed:** 2026-11-26
- **Use when:** changing a product, its descriptive variant attributes, its reviews or a policy.
- **How:** insert one `reindex_outbox` row for that source in the same transaction as the change; never call the embedding API from a request handler. Price and stock changes enqueue nothing.
- **Example:** `shopy_brief.md` §11 (no code yet)
- **Why:** the index never misses a change, and only the changed source is rebuilt (D-006).
- **Source:** user (project brief) · confidence high

## PATTERN-011 · Paid calls go through the cost ledger
- **Status:** approved
- **Use when:** any call to the LLM, STT, TTS or embeddings API.
- **How:** check the global and per-user caps before the call; write a `usage_ledger` row with units and estimated EUR cost after it. Unit prices come from env (`PRICE_*`).
- **Example:** `shopy_brief.md` §15 (no code yet)
- **Why:** the budget is fixed, and a reached cap must stop every paid call (D-019, test 22).
- **Source:** user (project brief) · confidence high

## PATTERN-012 · External providers sit behind interfaces
- **Status:** approved
- **Use when:** code calls the LLM, STT, TTS, embeddings, Stripe, mail or object storage.
- **How:** one small provider interface per service, chosen by config; tests use fakes (stub embeddings, mocked LLM). Model, voice and provider names come from env, never hard-coded.
- **Example:** `shopy_brief.md` §5, §17 (no code yet)
- **Why:** CI runs without real API calls; providers can be swapped (Mailpit/Resend, MinIO/R2).
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-18

## PATTERN-013 · Secrets only in .env
- **Status:** approved
- **Use when:** adding any configuration value.
- **How:** read it from env; add the name to `.env.example` with no real value; never commit `.env`. Seed passwords come from `SEED_*` env vars. Stripe keys are test mode only.
- **Example:** `.env.example` (names, placeholders only), `docker-compose.yml` (credentials interpolated from `.env`)
- **Why:** gitleaks runs in CI and pre-commit; no secret or real card data may enter the repo.
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-18

## PATTERN-014 · Schema changes: models, one reviewed revision, drift test
- **Status:** candidate
- **Confirmed:** 2026-11-26
- **Use when:** adding or changing a table, column, constraint or index.
- **How:** change the models in `backend/app/models/` first; then `alembic revision --autogenerate` and review the revision by hand (extensions, constraint names, `server_default`, `ondelete`, downgrade order). `bigint` identity keys (D-024); `text` + a CHECK instead of native ENUMs; names come from the `Base` naming convention; every foreign key column leads an index. `tests/test_migrations.py::test_models_match_migration` (drift) must stay green.
- **Example:** `backend/app/models/base.py`, `backend/migrations/versions/0001_initial_schema.py`, `backend/tests/test_migrations.py`
- **Why:** deterministic names let tests and migrations target constraints; the drift test catches a model change that has no migration.
- **Source:** GH-3 plan, assumption A9 (approved at gate B, 2026-11-18) · confidence medium

## PATTERN-015 · API tests with the DB: httpx AsyncClient + ASGITransport
- **Status:** candidate
- **Use when:** a test calls a route that uses the database.
- **How:** `httpx.AsyncClient(transport=ASGITransport(app=app, client=(ip, port)), base_url="https://test")`; override `get_session` with the rolled-back `session` fixture (savepoint per request); vary the client IP through `client=` for rate limits; `https` so `Secure` cookies come back; generate test secrets at run time. Never `TestClient` with DB fixtures (it runs the app on another event loop than asyncpg).
- **Example:** `backend/tests/conftest.py` (`api_app`, `client_factory`, `make_user`, `auth_header`), `backend/tests/test_auth_refresh.py`
- **Why:** one event loop for the app and asyncpg; nothing an API test writes survives it; cookie and rate-limit behaviour is testable.
- **Source:** GH-4 plan, assumption A15 (approved at gate B, 2026-11-19) · confidence medium
- **Confirmed:** 2026-11-26

## PATTERN-016 · Catalog attributes: one JSON type per key, whole units
- **Status:** candidate
- **Confirmed:** 2026-11-26
- **Use when:** adding or editing product or variant `attributes` in `backend/seed/catalog.json` (and later, admin-edited attributes).
- **How:** an attribute key has the same JSON type in every product. English snake_case keys that name the unit (`capacity_ml`, `power_w`, `width_cm`). No decimal strings: use a smaller whole unit (`capacity_ml: 1700`, `power_mw: 4200`). Ranges become two ints (`width_min_cm`, `width_max_cm`). Multi-valued keys are always lists (`surface`, `connectivity`). Booleans stay booleans; descriptive text goes in its own key (`lid: true`, `lid_material: "…"`). Values in Romanian.
- **Example:** `backend/seed/catalog.json` (ELE-001 `capacity_ml`, HOM-038 `width_min_cm`/`width_max_cm`, LAU-017 `surface` + `washing_method`)
- **Why:** P2 chunking and P3 tool filters read attributes by key; one type per key means no per-product parsing (GH-5 review round 1, F4).
- **Source:** GH-5 review round 1, finding F4 (user chose to fix it, 2026-11-26) · confidence medium

## PATTERN-017 · Row versions: lock, diff, increment in SQL
- **Status:** candidate
- **Use when:** a write changes a row that has a `version` column.
- **How:** lock the row `FOR UPDATE` (parent before child, so the lock order is the same everywhere); compare each submitted value with the row, JSON-dumped with sorted keys (so `1` ≠ `true` and key order does not count); write only what differs; if anything differs, set `obj.version = <Model>.version + 1` (a SQL expression: `version = version + 1`); `refresh` the row before building the response. An empty or unchanged body writes nothing.
- **Example:** `backend/app/api/admin.py` (`update_product`, `update_variant`, `_changes`)
- **Why:** D-014 and the P2 index status rely on versions moving exactly when the value moves; the row lock makes the comparison exact.
- **Source:** GH-6 plan (approved at gate B, 2026-11-26) · confidence medium
