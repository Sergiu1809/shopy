# Tests — GH-3

> Written by the test author before any code. Every new test failed first, for the right reason.

## Summary
- Added: 92 tests · 6 unit (`test_db_config.py`, no Docker), 86 integration (real Postgres + pgvector through testcontainers)
- Approach:
  - `tests/conftest.py` starts one session container, `pgvector/pgvector:0.8.7-pg16`, with no init script. There is no try/skip.
  - `migrated_url` sets `DATABASE_URL` and runs `alembic upgrade head` through `backend/alembic.ini`.
  - `session` is an `AsyncSession` in a transaction that is rolled back after each test.
  - `fresh_db_url` creates an empty database for the migration tests.
  - App, SQLAlchemy and Alembic imports in `conftest.py` stay inside the fixtures, so `test_health` still runs without them.
  - Schema tests read `information_schema` and `pg_catalog`. Constraint tests insert rows with raw SQL and bound parameters, and expect the named constraint in the error. The `updated_at` and `version` tests use the ORM (`Store`, `Category`, `Product`).
  - The tests were also run against a throwaway reference implementation in a scratch worktree (not committed): 92 of 92 passed. That run found two test bugs (`"char"` columns come back as bytes), which were fixed before the commit. Mutations were caught: no `onupdate`, a model/migration drift, and a downgrade that drops an extension.
- Existing tests changed: 0 · removed: 0
- Dev dependencies added: `testcontainers>=4.15,<5`, `pytest-asyncio>=1.5,<2`; pytest `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`. No mypy override is needed: testcontainers ships `py.typed`, so A7 is not triggered.

## Acceptance point → tests
Numbers follow PLAN.md "Acceptance points → tests". Files are under `backend/tests/`.

| # | Ticket | Acceptance point | File | Test(s) | Red reason before code |
|---|---|---|---|---|---|
| 1 | GH-3 | Async SQLAlchemy + Alembic in `backend/`, migrations in `backend/migrations/` | test_migrations.py | `test_upgrade_head_creates_all_tables` (also checks `alembic_version` is `0001`, A5) | `app.models` missing (collection); `backend/alembic.ini` missing |
| 2 | GH-3 | `DATABASE_URL` from env | test_db_config.py | `test_database_url_reads_env`, `test_database_url_missing_raises`, `test_create_engine_defaults_to_env_without_connecting`, `test_create_engine_uses_given_url`, `test_sessionmaker_does_not_expire_on_commit` | `app.db` missing |
| 3 | GH-3 | Migration creates `vector` + `unaccent` `IF NOT EXISTS`, without an init script | test_migrations.py | `test_upgrade_creates_extensions`, `test_upgrade_is_safe_when_extensions_exist` | `app.models` / `alembic.ini` missing |
| 4 | GH-3 | The 11 tables, brief §7 columns, no others | test_schema.py | `test_tables_exist`, `test_columns_match_brief[<11 tables>]` | `alembic.ini` missing (fixture `migrated_url`) |
| 5 | GH-3 | Money columns are integer `_minor` (PATTERN-001) | test_schema.py | `test_columns_match_brief[product_variants]`, `test_money_columns_are_integer_minor` | same |
| 6 | GH-3 | Timestamps are `timestamptz` | test_schema.py | `test_timestamps_are_timestamptz` | same |
| 7 | GH-3 | `store_id` only on categories, products, store_policies | test_schema.py | `test_store_id_only_on_catalog_parents` | same |
| 8 | GH-3 | D-024 bigint identity ALWAYS; `user_preferences` keyed by `user_id` | test_schema.py, test_constraints.py | `test_ids_are_bigint_identity_always[<10 tables>]`, `test_user_preferences_pk_is_user_id`, `test_explicit_id_insert_rejected` | same; test_constraints: `app.models` missing |
| 9 | GH-3 | Q2 ON DELETE (CASCADE / RESTRICT) | test_schema.py, test_constraints.py | `test_fk_delete_rules`, `test_delete_user_cascades`, `test_delete_product_cascades`, `test_delete_category_with_products_restricted`, `test_delete_store_with_children_restricted[categories\|products\|store_policies]` | same |
| 10 | GH-3 | Every FK column leads an index | test_schema.py | `test_every_fk_column_leads_an_index` | same |
| 11 | GH-3 | Unique `lower(email)` | test_constraints.py, test_schema.py | `test_email_unique_case_insensitive`, `test_email_index_is_lower_expression` | same |
| 12 | GH-3 | `UNIQUE(sku)` across the table | test_constraints.py | `test_sku_unique_across_products` | same |
| 13 | GH-3 | `UNIQUE(store_id, slug)` | test_constraints.py | `test_category_slug_unique_per_store` | same |
| 14 | GH-3 | `UNIQUE(token_hash)` | test_constraints.py | `test_refresh_token_hash_unique` | same |
| 15 | GH-3 | `UNIQUE(store_id, kind)` | test_constraints.py | `test_policy_kind_unique_per_store` | same |
| 16 | GH-3 | No unique on `stripe_customer_id`, `product_images.position` | test_constraints.py | `test_stripe_customer_id_not_unique`, `test_image_position_not_unique` | same |
| 17 | GH-3 | At most one default address per user (partial unique) | test_constraints.py, test_schema.py | `test_second_default_address_rejected`, `test_many_non_default_addresses_allowed`, `test_default_per_user_independent`, `test_default_address_index_is_partial` | same |
| 18 | GH-3 | `price_minor >= 0`, `stock >= 0` | test_constraints.py | `test_check_rejects[price_minor=-1\|stock=-1]`, `test_check_accepts[price_minor-0\|stock-0]` | same |
| 19 | GH-3 | `reviews.rating` 1..5 | test_constraints.py | `test_check_rejects[rating=0\|rating=6]`, `test_check_accepts[rating-1\|rating-5]` | same |
| 20 | GH-3 | `rating_count >= 0`; `rating_avg` numeric(3,2), 0..5 or NULL | test_constraints.py, test_schema.py | `test_check_rejects[rating_count=-1\|rating_avg=5.01\|rating_avg=-0.01]`, `test_check_accepts[rating_count-0\|rating_avg-None\|rating_avg-value6\|rating_avg-value7]`, `test_rating_avg_keeps_two_decimals`, `test_typed_details` | same |
| 21 | GH-3 | `role` / `kind` text + CHECK, default `customer`, no native ENUM | test_constraints.py, test_schema.py | `test_check_rejects[role=owner\|kind=other]`, `test_check_accepts[role-*\|kind-*]` (all 5 kinds), `test_user_role_defaults_to_customer`, `test_no_native_enum_types` | same |
| 22 | GH-3 | Q6 text strings, `currency char(3)` default `RON`, nullability list, `'{}'` defaults | test_schema.py, test_constraints.py | `test_columns_match_brief[*]`, `test_typed_details`, `test_only_listed_columns_are_nullable`, `test_server_defaults` | same |
| 23 | GH-3 | Q7 `version` default 1, no trigger; `updated_at` server default + ORM on update | test_constraints.py, test_schema.py | `test_product_updated_at_changes_on_orm_update`, `test_version_not_auto_incremented`, `test_no_triggers` | same |
| 24 | GH-3 | Q8 `content_hash` and `rating_avg` nullable, NULL on insert | test_schema.py, test_constraints.py | `test_only_listed_columns_are_nullable`, `test_server_defaults` | same |
| 25 | GH-3 | `upgrade head` and `downgrade base` work; extensions kept (Q10) | test_migrations.py | `test_round_trip` | `app.models` / `alembic.ini` missing |
| 26 | GH-3 | Q11 drift: models match the migration | test_migrations.py | `test_models_match_migration` (no exclusions so far) | same |
| 27 | GH-3 | Q11 naming convention | test_schema.py | `test_constraint_names_follow_convention`; the constraint tests also match exact names (`uq_users_email_lower`, `fk_products_category_id_categories`, `ck_reviews_rating_range`, …) | `alembic.ini` missing |
| 28 | GH-3 | Test image pinned to the Compose image | test_db_config.py | `test_test_image_matches_compose` | `app.db` missing (module import). Its own assertion already holds: it guards the pin and has no product behaviour to wait for. |
| 32 | GH-3 | ruff, ruff format, mypy strict, pytest pass | all | the whole suite | see "Run state" |

### Run state at hand-off (no product code yet)
- `uv run pytest`: the run is interrupted by 4 collection errors (`ModuleNotFoundError: sqlalchemy` / `alembic`, the runtime dependencies the builder adds). With `--continue-on-collection-errors`, `test_health` passes.
- With the planned runtime dependencies added for the run only (`uv run --with sqlalchemy[asyncio] --with alembic --with asyncpg`), the container starts and:
  - all 35 `test_schema` tests ERROR with `backend/alembic.ini is missing`;
  - `test_db_config`, `test_constraints` and `test_migrations` fail at collection with `No module named 'app.db'` / `'app.models'`;
  - `test_health` passes.
- `ruff check`: one I001 now. Ruff treats the missing `app.db`/`app.models` as third-party. With the modules present it passes (checked with empty placeholder files, then removed). `ruff format --check`: clean.
- `mypy` strict: only `import-not-found` errors (sqlalchemy, alembic, `app.*`). Against the reference implementation, mypy strict on `tests/` reports no issues.

## Not automated
| Acceptance point | Why | Covered by |
|---|---|---|
| 1 (part) `alembic heads` shows `0001` | CLI check | builder: `uv run alembic heads` |
| 29 DB tests fail loudly without Docker | a deliberately broken environment, not a committed test | builder: `DOCKER_HOST=unix:///nonexistent uv run pytest` must show ERROR, not SKIPPED (the test author pre-checked the harness: 35 ERROR, 0 skipped, health passes) |
| 30 CI runs the DB tests | needs a push | conductor/reviewer: CI `backend` job log at gate C |
| 31 api container migrates on start, then uvicorn; restart is idempotent | Compose is not in CI | builder: `docker compose up -d --build db api`, logs show `Running upgrade  -> 0001` before uvicorn, `curl /health`, `\dt` lists 11 tables + `alembic_version`, `docker compose restart api` shows no new upgrade |
| 33 GH-1 carry-overs | doc edits | reviewer (diff) and `ledger-lint.py` |
| 34 stale docs (Q-001 → D-023, AGENTS.md §2) | doc edits | reviewer (`grep -n D-022 docs/agents/OPEN-QUESTIONS.md` finds nothing) |
| 17 (part) "exactly one" default once a user has addresses | app logic, P4 | out of scope |

Manual test: none needed. No path in `.github/manual-test-paths` is touched.

## Changes after a logic change
| Date | Test | What changed | Why (trigger) |
|---|---|---|---|

## Reproductions for in-delivery fixes
| Date | Defect | Test | Red reason before the fix |
|---|---|---|---|

## Mechanical fixes by the builder
| Date | Test | Fix | Checked by reviewer |
|---|---|---|---|
