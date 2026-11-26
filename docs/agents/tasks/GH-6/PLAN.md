# Plan — GH-6 P1d: Admin product CRUD API

> Written by /plan (planner agent, 2026-11-26); the gate B calls are recorded below by /start.

## Size
**M.** Nine routes on the existing `/admin` router, one new schemas module, one new
test file (about 45 tests, most of them small), and docs. No migration, no new
dependency, no new abstraction. What makes it M rather than S: the version rules (two
counters, four triggers, "only on real change") and the error paths (409, 422 from a
DB lookup, 404 for a variant under another product).

## Repos · branches
`feat/admin-products-GH-6` (draft PR #12 into `main`)
Tickets covered: GH-6 (Fixes)

## Approach
The routes go **in `backend/app/api/admin.py`**, on the existing `router`. That router
already has `require_admin` at router level (PATTERN-007), so the access matrix in
`tests/test_admin_access.py` picks up every new route without any change. Each route
has the same shape as `register` in `app/api/auth.py`. It takes a Pydantic body
(`extra="forbid"`) and a `Session` dependency, raises `ApiError`, and turns an
`IntegrityError` on a named constraint into a 409. Bodies and responses go into a new
`backend/app/schemas/catalog.py`.

**Shared field types: move, not import, not copy.** `Text`, `Key`, `Sku` and
`AttributeValue` move from `backend/seed/schema.py` to `app/schemas/catalog.py`.
`seed/schema.py` then imports them, the same way it already imports `Email` from
`app/schemas/auth.py`. That keeps one definition, which AC "SKU format as in
`seed/schema.py`" needs, and keeps the import direction the repo already uses: seed
depends on app, never the other way round. The names stay importable from
`seed.schema`, so no test or caller changes. `Slug` stays in the seed, because the app
does not use it.
*Rejected:*
- importing from `seed.schema` in app code: the app would depend on a data tool, and
  importing it loads the whole seed module (file paths, catalog models).
- duplicating the four aliases: two SKU patterns that can drift apart.

**Attribute dicts with a fixed message.** With pydantic's default errors, an invalid
attribute would put the client's key in `field` (`loc` = `attributes.<key>.[key]`),
and C-001 forbids echoing input. So `ProductAttributes = dict[Key, AttributeValue]`
and `VariantAttributes = dict[Key, Text]` each carry a `WrapValidator`. It turns any
inner error into one `PydanticCustomError` with a fixed English message, so `field` is
`attributes`. This follows the fixed-message precedent of `Email` in
`app/schemas/auth.py`. The JSON schema in OpenAPI keeps the inner type. The seed keeps
its own unwrapped `dict[Key, …]`, so the validator's CLI output does not change.

**Versions: lock, diff, increment in SQL.** Every write route first loads the product
row `FOR UPDATE`. A variant route then also loads the variant row `FOR UPDATE` (always
product first, then variant, so the lock order is the same everywhere and deadlocks
cannot happen). The route compares each submitted field with the locked row; only the
fields that differ are written. If at least one differs, the counter is set as a SQL
expression, `obj.version = Product.version + 1` (or `ProductVariant.version + 1`).
The UPDATE then says `version = version + 1` (atomic, Q5), and the row lock makes the
comparison exact: there is no read-compare race. Which counter goes up:
| Change | `products.version` | `product_variants.version` |
|---|---|---|
| any product field (`category_id`, `brand`, `name`, `description`, `attributes`) | +1 | — |
| variant created or deleted | +1 | — |
| variant `sku` or `attributes` | +1 | — |
| variant `price_minor` or `stock` | — | +1 |
| empty `{}` or same values | — | — |

Values are compared with `json.dumps(value, sort_keys=True)` on both sides. Plain
`==` would say `{"a": 1} == {"a": True}` (Python's `True == 1`), and JSONB treats
those as different. The expression attribute is expired after the flush, so the route
calls `await db.refresh(obj)` before building the response (async SQLAlchemy cannot
lazy-load). `products.updated_at` follows from its existing `onupdate=func.now()`.

**403 before body validation.** FastAPI runs the route's dependencies, with the
router-level `require_admin` first, before it validates path, query and body
parameters. A customer therefore gets 403 for a missing body or a well-formed but
invalid one. The one exception is body text that is not JSON: FastAPI parses JSON
before it runs any dependency, so that gets 422 first. This is already the case and is
documented in `test_admin_access.py`; nothing is leaked. The matrix sends no body, as
today. A new test proves a customer with an invalid JSON body still gets 403.

**SKU taken → 409, race-safe.** There is no SELECT before the insert. The insert or
update is flushed; on `IntegrityError` the route rolls back. If
`"uq_product_variants_sku"` is in `str(exc.orig)`, it raises
`ApiError(409, "sku_taken", "This SKU is already in use.")`; otherwise it re-raises.
The unique constraint decides, so two parallel requests cannot both pass. This is the
same mechanism as `email_taken` in `register`.

**Store.** `store_id` = the lowest `stores.id` (`select(Store.id).order_by(Store.id).limit(1)`).
The seed creates exactly one store (brief §7: "one row in v1") and uses the same
"first store" test in `load()`. On POST, the category must exist and belong to that
store; if it does not, or there is no store, the route answers 422
`fields: [{"field": "category_id", …}]`. On PATCH, a changed `category_id` must belong
to the product's own `store_id`. That 422 is raised as
`RequestValidationError([{"type": "value_error", "loc": ("body", "category_id"), "msg": "Unknown category."}])`,
so the existing `validation_error_handler` builds the envelope and `errors.py` does
not change. Reads are not filtered by store (assumption A1).

**Not found.** `ApiError(404, "not_found", "Product not found." | "Variant not found.")`.
A variant is always looked up with `id = :variant_id AND product_id = :product_id`,
so a variant under another product → 404.

**DELETE.** Product: `delete(Product).where(Product.id == id).returning(Product.id)`;
no row → 404. The FKs cascade to variants, images and reviews (`ondelete="CASCADE"`,
already in `0001`). Variant: lock the product, delete the variant (404 if it is not
under this product), bump `products.version`. The last variant may go (gate A Q1).
Both answer `204 No Content`.

**Responses.**
- `VariantOut`: `id, product_id, sku, attributes, price_minor, stock, version`.
- `ProductOut` (list item): `id, store_id, category_id, brand, name, description, attributes, rating_avg, rating_count, version, updated_at`.
  `rating_avg: Decimal | None` serializes as `"4.30"` or `null`. `content_hash` is
  never included.
- `ProductDetailOut`: `ProductOut` plus `variants: list[VariantOut]` (ordered by `id`).
  GET, POST (with `variants: []`) and PATCH of a product all return it.
- `ProductPage`: `{"items": list[ProductOut], "total": int}`.
- `GET …/variants` returns `list[VariantOut]` ordered by `id` (assumption A2).
- Status codes: POST 201, PATCH 200, DELETE 204.

**Bodies** (`extra="forbid"`; integers `StrictInt`, as in the seed):
- `ProductCreate`: `category_id`, `brand`, `name`, `description`, `attributes`, all required.
- `VariantCreate`: `sku`, `attributes`, `price_minor`, `stock`, all required (A3).
- `ProductUpdate` / `VariantUpdate`: the same fields, each optional. An explicit
  `null` is rejected by a `field_validator("*")` with the message "must not be null"
  under that field's name (the columns are NOT NULL).
- `price_minor`, `stock`: `Field(ge=0, le=INT4_MAX)` (`INT4_MAX = 2147483647`).
- `category_id`: `Field(ge=1, le=BIGINT_MAX)`.
- Path IDs: `Path(ge=1, le=BIGINT_MAX)`.
- `limit`: `Query(ge=1, le=100) = 50`; `offset`: `Query(ge=0, le=BIGINT_MAX) = 0`.

An out-of-range number gets 422, never an asyncpg overflow and a 500 (A4).
`BIGINT_MAX = 2**63 - 1` is defined once in `app/schemas/catalog.py`.

## Files
| Action | Path | What |
|---|---|---|
| add | `backend/app/schemas/catalog.py` | `Text`, `Key`, `Sku`, `AttributeValue` (moved), `BIGINT_MAX`, `INT4_MAX`; `ProductAttributes` / `VariantAttributes` (fixed-message wrap); `ProductCreate`, `ProductUpdate`, `VariantCreate`, `VariantUpdate`; `VariantOut`, `ProductOut`, `ProductDetailOut`, `ProductPage` |
| edit | `backend/seed/schema.py` | drop the four alias definitions; `from app.schemas.catalog import AttributeValue, Key, Sku, Text` |
| edit | `backend/app/api/admin.py` | the 9 routes; small private helpers: `_store_id`, `_locked_product`, `_locked_variant`, `_check_category`, `_changes` (json-dump compare), `_sku_taken` (IntegrityError mapping); docstring: "routes arrive with GH-6" → what is here |
| add | `backend/tests/test_admin_products.py` | the tests below (test author, before code) |
| edit | `docs/API.md` | "Built so far" line; error table (404 `not_found` also for an unknown product or variant ID; 409 `sku_taken`; 422 also for an unknown `category_id`); an **Admin · products** section with one request/response example per route, the version table, list paging, delete cascade |
| edit | `docs/agents/CONTRACTS.md` | C-001 Evidence: `admin.py` "(`/admin` router; products and variants, GH-6)". Removes its Confirmed line (ledger rule); re-confirm at gate C |
| edit | `docs/agents/ARCHITECTURE.md` | status note: "the empty `/admin` router" → the P1d product routes |
| edit | `docs/agents/PATTERNS.md` | add a candidate pattern, next free ID at build time (`ledger-lint.py --next PATTERN`; today the one after PATTERN-016) (row versions: lock, diff, `version = version + 1` only on real change) |
| edit | `AGENTS.md` | §3 Layout: "P1d adds the admin product routes (GH-6)" |
| — | `backend/tests/test_admin_access.py` | **unchanged**: the matrix enumerates `app.routes`, so the 9 routes join it on their own |

No migration (models unchanged; the PATTERN-014 drift test stays green). `errors.py`,
`auth/dependencies.py`, `main.py` unchanged. Contract consumer: the web client
`/admin`, not built yet (Q-008), so there are no consumer files to change.

## Acceptance points → tests
All tests are in `backend/tests/test_admin_products.py` unless named otherwise. They
are HTTP tests with PATTERN-015 (`client`, `make_user(role="admin")`, `auth_header`).
A `catalog` fixture inserts a store, two categories, and a second store with a
category of its own, in that order, through `session`, then commits (as `make_user`
does).

| # | Acceptance point | Test kind | Not automated? why |
|---|---|---|---|
| 1 | The 9 routes exist on `/admin`; a variant under another product → 404 (PATCH and DELETE of `…/variants/{variant_id}`) | integration: `test_openapi_lists_every_admin_product_route` (method × path in `/openapi.json`); `test_variant_of_another_product_is_404` (PATCH, DELETE) | — |
| 2 | 401 without a token, 403 for a customer, 403 before body validation | existing parametrized matrix in `test_admin_access.py` (now 9 more pairs × 3 tests); new `test_customer_with_an_invalid_body_gets_403` (POST product, PATCH variant, valid JSON with wrong fields) | — |
| 3 | Writable fields only; `store_id` set by the server; unknown field → 422 | integration: `test_create_product_sets_the_store` (`store_id` = the first store); parametrized `test_read_only_field_is_rejected` (`store_id`, `rating_avg`, `rating_count`, `version`, `content_hash`, `id` on POST and PATCH product; `version`, `product_id` on variant) → 422 `field: "body"` | — |
| 4 | `products.version` +1 on a product change, a variant create, delete, `sku` or `attributes` change; not on price or stock | integration, one test per trigger: `test_product_patch_bumps_product_version`, `test_variant_create_bumps_product_version`, `test_variant_delete_bumps_product_version`, `test_variant_sku_change_bumps_product_not_variant`, `test_variant_attributes_change_bumps_product_not_variant`, `test_price_or_stock_change_leaves_product_version` | — |
| 5 | `product_variants.version` +1 only on price or stock | integration: `test_price_change_bumps_variant_version`, `test_stock_change_bumps_variant_version` (+ the two tests in 4 that assert the variant did not move) | — |
| 6 | Only on real change; empty PATCH accepted; atomic; no If-Match; version in every response | integration: `test_empty_patch_changes_nothing` (product, variant: 200, same version, same `updated_at`); `test_same_values_change_nothing` (same text, same attributes in a different key order, same price); `test_one_becoming_true_is_a_change` (`{"k": 1}` → `{"k": true}`); `test_version_is_incremented_in_sql` (raise `version` to 7 with plain SQL between requests, PATCH → 8); `version` asserted in every success body | Atomicity under real concurrency is not testable with the rolled-back shared session; the reviewer checks the SQL expression and the `FOR UPDATE` |
| 7 | `attributes` replaced whole; key and value shapes; variant text only | integration: `test_attributes_are_replaced_not_merged`; parametrized `test_bad_product_attributes_are_422` (bad key, float, nested object, list of ints, null value) → `field: "attributes"`, key not in `response.text`; parametrized `test_bad_variant_attributes_are_422` (int, bool, list, empty string) | — |
| 8 | `price_minor`, `stock` 0…2147483647, integers, else 422 | integration: parametrized `test_bad_price_or_stock_is_422` (-1, 2147483648, 1.5, `"100"`, `true`, `null` on PATCH) on POST and PATCH variant; `test_price_and_stock_bounds_are_accepted` (0 and 2147483647) | — |
| 9 | SKU format; existing SKU → 409 `sku_taken` | integration: `test_lowercase_sku_is_422`; `test_duplicate_sku_on_create_is_409`; `test_patch_to_another_variants_sku_is_409`; `test_patch_to_its_own_sku_is_a_no_op` | Race safety rests on the unique constraint; the reviewer checks there is no pre-check SELECT |
| 10 | Unknown or foreign `category_id` → 422 on `category_id`; unknown path ID → 404 `not_found` | integration: parametrized `test_unknown_or_foreign_category_is_422` (POST, PATCH; missing ID, other store's category); parametrized `test_unknown_id_is_404` (every route with a path ID, product and variant) | — |
| 11 | Text non-empty after trim, no max | integration: `test_blank_text_is_422` (`"   "` for `brand`, `name`, `description`, variant attribute value); `test_text_is_stored_trimmed`; `test_long_description_is_accepted` (20 000 chars) | — |
| 12 | List: `limit` 1–100, default 50, `offset`, by `id`, `{items,total}`, no variants | integration: `test_list_pages_by_id` (3 products, `limit=2&offset=1`); `test_list_default_limit_is_50` (51 products, cheap bulk insert); parametrized `test_bad_paging_is_422` (`limit=0`, `101`, `offset=-1`); item keys asserted (no `variants`, no `content_hash`) | — |
| 13 | Detail with variants; `rating_avg` string or null; no `content_hash` | integration: `test_detail_includes_variants_in_id_order`; `test_rating_avg_is_a_string_or_null` (row with `rating_avg=4.3` via SQL → `"4.30"`; new product → `null`) | — |
| 14 | POST product creates it without variants | integration: `test_create_product_returns_201_without_variants` (`variants == []`, `version == 1`, `rating_count == 0`) | — |
| 15 | Hard delete; cascade; last variant deletable | integration: `test_delete_product_cascades` (variant, image and review rows inserted with SQL are gone; GET → 404); `test_last_variant_can_be_deleted` | — |
| 16 | One envelope; input never echoed | `assert_error` on every error test; `test_errors_never_echo_input` (a bad SKU, a bad attribute key, an unknown field name: none in `response.text`) | — |
| 17 | The seeded admin edits a seeded product; the change is visible on GET | integration: `test_seeded_admin_edits_a_seeded_product`. Runs `seed.seed.load` into `session` with run-time passwords (as test 25 in `test_seed_load.py`), logs in as the seeded admin through `POST /auth/login`, PATCHes product 1's `name` and variant 1's `price_minor`, then GETs: name, price and both versions are new | — |
| 18 | OpenAPI shows the routes; `docs/API.md` Admin section and codes | point 1's OpenAPI test | `docs/API.md` is checked at gate C (doc review) |

Existing tests that must stay green unchanged: `test_seed_validate.py` and
`test_seed_load.py` (the type move), `test_admin_access.py` (now more cases),
`test_migrations.py` (no drift), and `test_errors.py`.

## Sequencing
**One builder.** All the parts touch `app/schemas/catalog.py` and `app/api/admin.py`,
so parallel workers would collide. Order:
1. The test author writes `test_admin_products.py` (red: 404/405 on the missing
   routes).
2. The builder moves the four types (seed tests stay green), then adds the schemas,
   then the product routes, then the variant routes, then docs and the ledger.

## Manual test plan
None. API only, with no manual-test path (`.github/manual-test-paths`). Every point
is automated, except the doc review at gate C.

## Design (UI only)
Not applicable: no screen.

## Risks
- **A key echoed in a 422** if the wrap validator is left off. Test 16 guards it.
- **MissingGreenlet** when the response reads a version set by expression without
  `refresh`. Any success test catches it.
- **Python `True == 1`** hides a real attribute change. Hence the json-dump compare
  and test 6.
- **The lowest-id store** is right only while there is one store (brief v1). If a
  second store ever exists, `_store_id` is the single place to change.
- **Malformed JSON from a customer** gets 422 before 403. This is FastAPI's order,
  documented, and leaks nothing.
- **Hard delete cannot be undone.** Accepted at gate A. Q-017 makes P4 revisit it
  before any table references a variant.
- **`test_seeded_admin_edits_a_seeded_product` loads the full seed** (Argon2 hashes
  and about 200 products). That adds a few seconds; test 25 already does the same.
- **OpenAPI for PATCH bodies shows the fields as nullable** (`X | None`), although the
  server rejects `null`. A cosmetic mismatch, noted in `docs/API.md`.
- **No outbox rows yet** (PATTERN-010, P2). Until P2, an edit is not reindexed. The
  product version is still correct, so P2's index status will show the product as
  stale.

## Out of scope
Image endpoints (Q-001); the reindex outbox (P2); any admin UI (Q-008); review
endpoints; category CRUD; search or filters on the list; soft delete or archive
(Q-017); the "admin edit invalidates open proposals" event (P4, brief §12.6);
optimistic concurrency (If-Match); per-key attribute types (Q-016).

## Knowledge used
| Entry | What it says | Why it applies here | Call (confirm / wrong / outdated / answered) | Date |
|---|---|---|---|---|
| 10 entries confirmed before, unchanged: D-006, D-010, D-021, D-023, D-024, PATTERN-001, PATTERN-006, PATTERN-007, PATTERN-008, PATTERN-013 | outbox for indexed changes, price/stock never indexed; prices only from the DB; English API, Romanian data; seed written once and validated; bigint IDs; money in bani; Pydantic + one 422 envelope; role dependency at router level; SQLAlchemy bound parameters only, schema only via Alembic; secrets only in env | product version bumps only on indexed changes; `price_minor` int bani; English messages; path IDs bigint (`BIGINT_MAX`); bodies `extra="forbid"`; routes on the admin router; ORM/Core only, no migration; seed passwords generated at test run time | confirm | 2026-11-26 |
| C-001 (confirmed 2026-11-25) | REST, one error envelope, no input echoed, OpenAPI + `docs/API.md` | adds admin routes from brief §14 and two codes inside the envelope; Evidence edited → Confirmed line drops, re-confirm at gate C. Consumer: web `/admin`, not built (Q-008) | confirm | 2026-11-26 |
| PATTERN-015 (candidate, confirmed 2026-11-26) | API tests: httpx AsyncClient + ASGITransport, rolled-back session | every test in `test_admin_products.py` | confirm | 2026-11-26 |
| D-014 | any price or stock change invalidates a proposal | why `product_variants.version` moves on price/stock only (Q4); no proposal code yet | confirm | 2026-11-26 |
| PATTERN-010 | indexed changes insert an outbox row in the same transaction; price/stock enqueue nothing | not applied yet (no outbox table, P2); the version rules line up with it so P2 only adds the insert | confirm | 2026-11-26 |
| PATTERN-014 (candidate) | schema changes: models, one revision, drift test | not applied: no schema change; the drift test must stay green | confirm | 2026-11-26 |
| PATTERN-016 (candidate) | one JSON type per attribute key | not enforced per key (gate A Q7); admin-edited attributes follow it by convention only | confirm | 2026-11-26 |
| Q-016 (deferred) | typed attribute values | out of scope; the seed's value shapes are reused as-is | confirm | 2026-11-26 |
| Q-001 (open) | image source | image endpoints out of scope | confirm | 2026-11-26 |
| Q-008 (open) | design tokens | no admin UI | confirm | 2026-11-26 |
| Q-017 (open) | archive or 409 once P4 references variants | hard delete now; P4 revisits | confirm | 2026-11-26 |

### Considered, not applied
- PATTERN-002 (agent tool parameters): admin REST routes are not agent tools.
- D-005 (hybrid search): no search on the list (gate A Q11).
- C-005 (proposal hash): no proposals yet.

### Assumptions (no entry behind them)
- **A1** Reads (list, detail) are not filtered by store, and PATCH/DELETE find a product by ID alone. There is one store (brief §7). → if the user wants store scoping, `_store_id` filters every query.
- **A2** `GET /admin/products/{id}/variants` returns a plain JSON array ordered by `id`, not paged (a product has a few variants). Alternative: `{"items": [...]}`.
- **A3** `attributes` is required on create for products and variants, as in the seed. `{}` is a valid value.
- **A4** Bounds that the AC did not state are added so that no request reaches a DB overflow (500): path IDs and `category_id` 1…2^63−1, `offset` 0…2^63−1, outside → 422. An ID of 0 or below is a malformed ID (422), not an unknown one (404).
- **A5** Integers are strict (`StrictInt`, as in the seed): `"100"`, `1.0` and `true` are not a price or a stock.
- **A6** Text fields are stored trimmed (the seed's `Text` strips).
- **A7** PATCH of a product returns the detail shape (with variants), so a product has one response shape.
- **A8** Messages: "Product not found.", "Variant not found.", "This SKU is already in use.", "Unknown category.", plus fixed attribute messages. English (D-021); no value is echoed.

### Contract change? No PROPOSAL.
C-001's approved Shape already lists the brief §14 admin routes and defines `code` as
an open machine code inside one fixed envelope. This plan adds routes that C-001
names, and two codes (`sku_taken`; `not_found` for resources, which `errors.py`
already maps for 404) without changing the envelope, its fields, the status
semantics, or any existing code. That is "code that follows the approved entries"
(AGENTS.md → The gate), and GH-4 added `email_taken` the same way, approved at gate B
without a PROPOSAL. The only ledger edit is C-001's Evidence path, a moved/added path.
It still drops the entry's `Confirmed` line, so C-001 is re-confirmed at gate C.

### New candidate (added during build, "do, then report")
- **PATTERN-<next> · Row versions: lock, diff, increment in SQL** (candidate)
  - **Use when:** a write changes a row that has a `version` column.
  - **How:** lock the row (`FOR UPDATE`, parent before child); compare each submitted
    value with the row (JSON-dumped, so `1` ≠ `true`); write only what differs; if
    anything differs, set `version = <Model>.version + 1` as a SQL expression; refresh
    before the response.
  - **Example:** `backend/app/api/admin.py`
  - **Why:** D-014 and P2 index status rely on versions moving exactly when the
    value moves.
  - **Source:** GH-6 plan.

## Gate B
- Decision: approved — 2026-11-26 — the user approved the plan as written, with assumptions A1–A8 ("DA"). Knowledge entries confirmed; `Confirmed: 2026-11-26` set on D-014, PATTERN-010, PATTERN-014, PATTERN-016 (candidates stay candidates). C-001 is re-confirmed at gate C after its Evidence edit.
