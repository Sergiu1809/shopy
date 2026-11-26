# Plan — GH-5 P1c: Catalog and seed

> Written by /plan (planner agent, 2026-11-25); the gate B calls are recorded below by /start.

## Size
**L**, driven by content, not code. The code is M: three small modules (`schema.py`,
`validate_catalog.py`, `seed.py`), two test files, a Makefile and a CI step. The
content is about 200 Romanian products and roughly 1,400–1,800 reviews. That is
about 0.5–0.8 MB of JSON, more than one agent can write in one context.

## Repos · branches
`feat/catalog-seed-GH-5` (draft PR #11 into `main`)
Tickets covered: GH-5 (Fixes)

## Approach
One set of Pydantic v2 models, `backend/seed/schema.py`, is the only definition of
`catalog.json` and `users.json`. Both `python -m seed.validate_catalog` (run in CI) and
`python -m seed.seed` (run by `make seed`) parse the files through these models, so the
validator and the loader can never disagree about the format (PATTERN-006).

The loader reuses GH-4's code. Passwords are checked with `Password` and emails with
`Email` from `app/schemas/auth.py`, so a seeded email is one `POST /auth/login`
accepts. Hashing uses `hash_password` from `app/auth/passwords.py`. The engine and
sessionmaker come from `app/db.py`. All writes go through the ORM models, in file
order, inside one transaction. It inserts only what is missing (gate A Q2): if a store
row exists, the catalog part is skipped; a user is skipped when the email exists,
compared case-insensitively. No migration and no new dependency.

`catalog.json` stays one file, the name AC 1 and D-023 use. Its content is written in
five category fragments by parallel content workers. The conductor joins them into
`catalog.json` with a one-off command (see Sequencing). The only reason for
fragments is size: no single agent can write about 0.7 MB.

*Rejected:*
- One committed JSON per category (`seed/catalog/<slug>.json`). Diffs are no easier
  to review (each file is still ~150 KB, which GitHub does not render), and it
  departs from the file named in AC 1 and D-023.
- A Python generator with text templates. Its output would read like generated text,
  which brief §8 rules out ("no lorem ipsum"), and it brings back a generator that
  D-023 removed.
- Bulk Core `executemany`. ORM inserts in file order give the fixed IDs (D-024) with
  less code, and 2,000 rows is small.

### File formats (shared by validator and loader)
Every model uses `extra="forbid"`. Strings are non-empty and stripped
(`min_length=1`). Integers are `StrictInt`, so `19.99`, `"1999"` and `true` are
rejected.

**`catalog.json`**
```json
{
  "store":    {"name": "Shopy", "currency": "RON"},
  "policies": [{"kind": "shipping|returns|warranty|payment|size_guide", "title": "…", "body": "…"}],
  "categories": [
    {"slug": "clothing", "name": "Îmbrăcăminte", "products": [
      {"brand": "Adidas", "name": "…", "description": "…",
       "attributes": {"material": "100% bumbac", "fit": "regular"},
       "fixture": "missing_attribute",
       "variants": [{"sku": "CLO-001-M", "attributes": {"size": "M", "color": "negru"},
                     "price_minor": 14999, "stock": 12}],
       "reviews":  [{"author_display_name": "Andreea M.", "rating": 4, "title": "…",
                     "body": "…", "created_at": "2025-03-14T10:22:00Z",
                     "fixture": "prompt_injection"}]}
    ]}
  ]
}
```
`fixture` is optional on products and reviews. In the example it marks where the
field goes; only the fixture products and reviews carry it.

- `StoreIn`: `name: Literal["Shopy"]`, `currency: Literal["RON"]` (Q1).
- `PolicyIn`: `kind` is a Literal of the five kinds in the `store_policies` CHECK; title and body are text.
- `CategoryIn`: `slug` matches `^[a-z0-9]+(-[a-z0-9]+)*$`; `name` (Romanian).
- `ProductIn`:
  - `brand`, `name`, `description`.
  - `attributes: dict[Key, str | int | bool | list[str]]`, where `Key` matches `^[a-z][a-z0-9_]*$`: English keys, Romanian values (Q7).
  - `variants`: at least 1.
  - `reviews`: 3 to 15.
  - `fixture: Literal["out_of_stock", "missing_attribute"] | None`.
- `VariantIn`:
  - `sku` matches `^[A-Z0-9]+(-[A-Z0-9]+)*$`.
  - `attributes: dict[Key, str]`.
  - `price_minor`: StrictInt > 0.
  - `stock`: StrictInt ≥ 0.
- `ReviewIn`:
  - `author_display_name`, `title`, `body`.
  - `rating`: StrictInt, 1 to 5.
  - `created_at`: `AwareDatetime` with UTC offset 0.
  - `fixture: Literal["prompt_injection", "xss"] | None`.
- `CatalogFile` (a `model_validator`, which reports every problem it finds):
  - the category slugs are exactly `clothing`, `laundry-and-cleaning`, `cosmetics-and-personal-care`, `small-electronics`, `home`, each once (Q4);
  - 190 to 210 products in total (Q5);
  - SKUs unique across the file;
  - each policy kind exactly once;
  - each of the four fixture kinds exactly once (Q5, Q6);
  - `out_of_stock`: every variant has stock 0;
  - `missing_attribute`: the product is in `clothing`; its attributes and its variants' attributes have no `material` key; its description does not contain "material" (case-insensitive) (Q6);
  - `xss`: the review body contains `<script` and `onerror=`. Nothing can check `prompt_injection` mechanically; review checks its text.

**`users.json`**
```json
{"users": [
  {"email": "admin@example.com", "role": "admin", "addresses": [], "preferences": null},
  {"email": "customer1@example.com", "role": "customer",
   "addresses": [{"label": "Acasă", "full_name": "…", "phone": "0700 000 001",
                  "street": "…", "city": "Cluj-Napoca", "county": "Cluj",
                  "postal_code": "400001", "is_default": true}, {…}],
   "preferences": {"sizes": {"clothing": "M"}, "preferred_brands": ["Nike", "Nivea"]}}
]}
```
- `UserIn`:
  - `email`: GH-4's `Email` type (lowercased, and `.test`/`.local` rejected as at login).
  - `role: Literal["admin", "customer"]`.
  - `addresses: list[AddressIn]`. If there are any, exactly one has `is_default`, which the partial unique index also requires.
  - `preferences: PreferencesIn | None`.
- `AddressIn`: the columns of `addresses`, with `postal_code` matching `^\d{6}$`.
- `PreferencesIn`: `sizes: dict[str, str]`, `preferred_brands: list[str]`.
- `UsersFile`: emails are unique.
- Passwords are not in the file. The role picks the variable: `admin` uses
  `SEED_ADMIN_PASSWORD`, `customer` uses `SEED_CUSTOMER_PASSWORD`.

### Fixed data (determinism, Q9)
- Insertion order is file order: categories, products, then each product's variants and reviews, then policies, then users, each with its addresses and preferences. On a fresh database, product *n* in file order gets ID *n* (D-024).
- Every review has a fixed `created_at` in the JSON, UTC, written as `YYYY-MM-DDTHH:MM:SSZ`, between 2024-01-01 and 2026-10-31.
- `rating_count` is the number of reviews. `rating_avg` is `Decimal(sum) / count`, quantized to `0.01` with `ROUND_HALF_UP`. A pure function, `rating_summary(ratings)`, computes both.
- JSON is written with 2-space indent, `ensure_ascii=False` (diacritics stay readable) and a trailing newline.

### Loader (`seed/seed.py`)
- `seed_passwords(env) -> dict[role, str]` runs first, before any DB connection.
  - An unset variable, or one that fails `TypeAdapter(Password)`, raises `SeedError`. The message names the variable and the rule, "8–128 characters, at least one uppercase letter and one digit", and never prints the value.
  - The `change-me` placeholder fails this rule (Q8).
- `async load(session, catalog, users, passwords) -> SeedReport`.
  - It only adds and flushes; it never commits, so tests can run it inside the rolled-back test session.
  - Catalog: `select(Store.id).limit(1)`. If a row exists, the catalog is skipped. Otherwise it inserts the store, categories, products (with the rating summary), variants, reviews and policies.
  - Users: for each user in order, `select(User.id).where(func.lower(User.email) == email)`. If absent, it inserts the user (`hash_password(passwords[role])`, `stripe_customer_id` NULL), then the addresses in order, then the preferences. If present, the user is skipped with their addresses and preferences untouched.
- `main() -> int`, called as `sys.exit(main())` under `__main__`:
  - checks the passwords, then parses both files;
  - runs `create_engine()` and `async with sessionmaker() as s, s.begin(): load(...)`, so everything is one transaction;
  - prints a summary to stdout, for example `Catalog: inserted 1 store, 5 categories, 200 products, … reviews, 5 policies.` or `Catalog: already seeded, skipped.`, then one line per user (`inserted` / `exists, skipped`);
  - on `SeedError` or a validation error it prints a message to stderr and returns 1, otherwise 0. Any other exception rolls back and propagates.
- `make seed`: a new root `Makefile` with `.PHONY: seed` and `seed: docker compose run --rm api python -m seed.seed` (the command the AC gives). The api image already copies `backend/`, and `env_file: .env` passes `SEED_*`.

### Validator (`seed/validate_catalog.py`)
- `validate_files(catalog_path, users_path) -> list[str]` returns readable errors. Each is the location and message from `ValidationError.errors(include_input=False)`, so no large inputs are echoed.
- `main()` checks `seed/catalog.json` and `seed/users.json` next to the module. It prints `OK: <n> products, <n> variants, <n> reviews, <n> users` and exits 0, or prints the errors and exits 1.
- CI: add `- run: uv run python -m seed.validate_catalog` to the backend job, after `mypy` and before `pytest`.

## Files
| Action | Path | What |
|---|---|---|
| create | `backend/seed/__init__.py` | package marker (docstring only) |
| create | `backend/seed/schema.py` | the Pydantic models above; `load_catalog(path)`, `load_users(path)` |
| create | `backend/seed/validate_catalog.py` | `validate_files`, `main`, `__main__` |
| create | `backend/seed/seed.py` | `SeedError`, `seed_passwords`, `rating_summary`, `load`, `SeedReport`, `main` |
| create | `backend/seed/users.json` | 1 admin and 2 customers on `example.com`, each customer with 2 Romanian addresses (one default); `customer1` has preferences (Q3) |
| create | `backend/seed/catalog.json` | store, 5 policies, 5 categories, ~200 products (assembled from the content workers' fragments) |
| create | `backend/tests/test_seed_validate.py` | validator unit tests (no DB) and checks on the real files |
| create | `backend/tests/test_seed_load.py` | loader tests: pure functions, the password refusal, `main()` on fresh databases, login of seeded accounts |
| create | `Makefile` | `seed` target |
| modify | `.github/workflows/ci.yml` | validator step in the backend job |
| modify | `.env.example` | comment above `SEED_*`: the password rule; `change-me` fails on purpose (no value added) |
| modify | `AGENTS.md` | §2: `make seed` and `uv run python -m seed.validate_catalog` replace "Planned: make seed (P1)"; §3: what `seed/` holds |
| modify | `docs/agents/ARCHITECTURE.md` | seed row: add `users.json` and `schema.py` |
| modify | `docs/agents/tasks/GH-5/*`, `docs/agents/STATE.md` | journal (conductor only) |

No file of another ticket is touched. GH-6 consumes the seeded admin and products but
changes no file here.

## Acceptance points → tests
`V` = `backend/tests/test_seed_validate.py` (unit, no DB). `L` =
`backend/tests/test_seed_load.py` (testcontainers DB unless noted). The test author
builds a minimal valid catalog in code (190 small products), so each bad case mutates
one thing. No large fixture files.

| # | Acceptance point | Test kind | Not automated? why |
|---|---|---|---|
| 1 | Real `catalog.json` and `users.json` pass the validator; `main()` exits 0 and prints `OK` | V · unit (+ CI step) | — |
| 2 | 190 to 210 products: 189 and 211 rejected, 190 and 210 accepted | V · unit | — |
| 3 | A product with 0 variants rejected; 2 or 16 reviews rejected, 3 and 15 accepted | V · unit | — |
| 4 | Duplicate SKU across two products rejected | V · unit | — |
| 5 | `price_minor` of 0, -1, `19.99`, `"1999"` or `true` rejected; `stock` -1 rejected; rating 0 or 6 rejected | V · unit | — |
| 6 | Category set: a missing, an extra or a duplicate slug rejected; a non-ASCII slug rejected | V · unit | — |
| 7 | Fixtures: a missing kind and a duplicated kind are each rejected; `out_of_stock` with one stocked variant rejected; `missing_attribute` with `material` in attributes, in variant attributes or in the description, or outside `clothing`, rejected; `xss` without markup rejected | V · unit | `prompt_injection` content: review only |
| 8 | Policies: a missing or duplicated kind rejected; an unknown field (`extra="forbid"`) rejected; a naive or non-UTC review `created_at` rejected | V · unit | — |
| 9 | Store is `Shopy` / `RON`; a store with another name or currency is rejected | V · unit | — |
| 10 | Users file: a `.test` email, an unknown role, two default addresses, or a duplicate email is rejected; the real file has 1 admin and 2 customers, each customer has 2 addresses with one default, and exactly one customer has preferences | V · unit | fictitious names and addresses: review |
| 11 | The real catalog's content: every rating 1–5 occurs; the shipping policy body mentions `19,99` and `200`, and returns mentions `14`; the delivery estimate is in the shipping policy | V · unit | Romanian quality, real brands, realistic prices: review (sampled) |
| 12 | `validate_files` on a broken file returns messages with a location, without echoing the input; `main()` exits 1 | V · unit (tmp_path) | — |
| 13 | `rating_summary([5,4,4]) == (Decimal("4.33"), 3)`; a sum of 37 over 8 reviews gives `4.63` (half-up, not banker's rounding) | L · unit | — |
| 14 | Password refusal: unset, `change-me`, 7 characters, no digit, no uppercase, 129 characters, each for both variables. `main()` returns 1 and stderr names the variable but never contains the value. This holds with `DATABASE_URL` unset, which proves the check runs before any connection | L · unit | — |
| 15 | First run on a fresh migrated DB (`main()`): row counts equal the files (1 store, 5 categories, N products, variants, reviews, 5 policies, 3 users, 4 addresses, 1 preference row); stdout reports them | L · DB | — |
| 16 | Deterministic IDs: product IDs are 1..N in file order (names by ID equal file order); variant SKUs by ID equal file order; review `created_at` values equal the file | L · DB | — |
| 17 | `rating_avg` / `rating_count` per product equal `rating_summary` of its file ratings | L · DB | — |
| 18 | Fixture texts stored verbatim: the xss and injection review bodies equal the file strings byte for byte (still contain `<script>`); every variant of the out-of-stock product has stock 0 | L · DB | rendering harmlessly: P3/P6 (PATTERN-009) |
| 19 | Users: lowercase emails, roles as in the file, `stripe_customer_id` NULL, no plaintext; `verify_password(env password, hash)` is true | L · DB | — |
| 20 | Rerun: the second `main()` prints `already seeded`, every table count and `max(id)` is unchanged, and it exits 0 | L · DB | — |
| 21 | An admin edit survives a rerun: change product 1's name and a variant's `price_minor` by SQL, rerun, the values are unchanged | L · DB | — |
| 22 | Missing user reinserted: delete `customer2` (cascade), rerun; `customer2` and their addresses come back, other users' IDs are unchanged, the catalog is skipped | L · DB | — |
| 23 | Case-insensitive match: a pre-existing `Admin@Example.com` row means the admin is skipped (no IntegrityError) and the customers are inserted | L · DB | — |
| 24 | One transaction: a failure while inserting the second user (monkeypatched user-insert helper raising) leaves 0 stores, 0 products and 0 users | L · DB | — |
| 25 | Seeded accounts log in: `load()` into the rolled-back `session`, then `POST /auth/login` with the env passwords returns 200 and a token body for all three; `GET /me` shows role `admin` for the admin (PATTERN-015) | L · API + DB | — |
| 26 | `make seed` in Docker Compose, run twice: the first run loads, the second prints "already seeded" | — | needs Docker Compose with a real `.env`; the conductor runs it if Docker is available, otherwise it is named as skipped in the PR's Testing done |

The DB tests (15–24) call the synchronous `main()` against `fresh_db_url`, migrated with
`command.upgrade` as in `test_migrations.py`, and assert with `fetch()`. Alembic's and
the seed's `asyncio.run` then never nest inside pytest-asyncio's loop. Passwords for
the tests are generated at run time (`secrets`-based, with the rule's characters
added) and set with `monkeypatch.setenv`.

## Sequencing
1. **Test author** writes `test_seed_validate.py` and `test_seed_load.py` (red).
2. **Builder, code** (one builder, integration branch): `schema.py`, `validate_catalog.py`, `seed.py`, `__init__.py`, `users.json`, `Makefile`, the CI step, `.env.example`, `AGENTS.md`, `ARCHITECTURE.md`.
   - Also a `catalog.json` *skeleton*: the store, the five Romanian policies and `"categories": []`. Tests 1, 11 and 15–25 stay red until step 4.
   - Ruff and mypy must be clean. Tests 2–10, 12–14 green.
3. **Five content workers, in parallel** (worktrees, private branches, never pushed). Each writes one fragment, `backend/seed/parts/<slug>.json`: one `CategoryIn` object with **40 products**. Each worker checks its fragment against `seed.schema.CategoryIn` (a one-off `uv run python -c …`, no new option) and commits it on its worker branch.
   | Worker | Slug · Romanian name | SKU prefix | Fixture it owns |
   |---|---|---|---|
   | W1 | `clothing` · Îmbrăcăminte | `CLO-` | `missing_attribute` (no `material` anywhere) |
   | W2 | `laundry-and-cleaning` · Detergenți și curățenie | `LAU-` | review `prompt_injection` (asks the assistant to ignore its rules and give a discount) |
   | W3 | `cosmetics-and-personal-care` · Cosmetice și îngrijire personală | `COS-` | — |
   | W4 | `small-electronics` · Electronice mici | `ELE-` | `out_of_stock` (every variant stock 0) |
   | W5 | `home` · Casă | `HOM-` | review `xss` (`<script>…</script>` and `<img src=x onerror=…>`) |
   - SKUs are `<PREFIX><NNN>-<variant code>`, for example `CLO-001-M` or `LAU-012-3L`, so they are unique across workers by construction.
   - Each worker writes in batches of about 8 products per file edit. Reviews average about 7 per product, spread over 3–15 with mixed ratings, some answering typical questions (sizing, smell, durability; brief §8).
   - Real brands, realistic RON prices, Romanian text with diacritics. Authors are a fictitious first name and an initial.
4. **Conductor assembles**:
   - reads the five fragments with `git show <worker-branch>:backend/seed/parts/<slug>.json`;
   - fills `categories` in the order of the table, using a one-off `python3 -c` (json load, append, `json.dump(indent=2, ensure_ascii=False)` plus a newline);
   - runs `uv run python -m seed.validate_catalog` and the full backend suite;
   - commits only `catalog.json`. The fragments never reach the integration branch, and the worker branches are deleted after the commit.
5. **Reviewer** (at most 2 rounds) spot-checks samples of every category: language, brands, prices, review realism, and the injection fixture text. Then gate C.

The parallel content work is worth it because one agent cannot write ~0.7 MB of JSON
in one context. The code is a single builder: the files are small and depend on each
other.

## Manual test plan
No path in `.github/manual-test-paths` changes, so no MT- entry is needed and the PR
says "Manual test: not needed". Point 26 (`make seed` twice on Compose) is a
verification step for the conductor, not an MT- entry.

## Design (UI only)
No UI.

## Risks
- **Content size and quality.** Fragments can drift in tone or wording, repeat review texts, or get prices wrong. Fallback: the reviewer samples each category, and the validator catches structure. A bad category is rewritten by one worker without touching the code.
- **Real-looking personal data.** Invented phone numbers could belong to a real person. Mitigation: `0700 000 00x`-style numbers, `example.com` emails, invented street numbers. Authors are first name plus initial only.
- **Fixed IDs depend on SQLAlchemy keeping add order within one mapper.** Test 16 would catch a change. Fallback: flush after each product, then add its variants and reviews and flush again; the plan does this anyway.
- **`make seed` uses the image as last built.** After changes to `backend/`, `docker compose up --build` (or `build api`) must run first. The api service also has to have migrated the DB (`docker compose up` runs `alembic upgrade head`). Without that, the seed fails with a missing-table error. This is documented in AGENTS.md §2, and the Makefile is not changed (the AC gives its exact command).
- **Two seeds at once** could both see "no store" and both insert. This is not handled: it is a one-developer CLI and nobody asked for a lock. Noted as a suggestion.
- **Seeding the real catalog in tests** costs a few seconds per DB test. About 9 runs fit easily in the 10-minute CI timeout.
- **Hard to reverse:** nothing. No migration; the catalog is data.

## Out of scope
- Product images (Q-001).
- Stripe Customers and test cards for the demo customers (Q-015, P4): `stripe_customer_id` stays NULL and there are no `payment_methods` rows.
- Indexing and the outbox (P2). The reindex worker will need an initial full index of the seeded catalog; that is P2's call.
- `generate_catalog.py` (superseded by D-023).
- A delivery-estimate config constant (P4 pricing, Q10).
- An advisory lock against concurrent seeds (suggestion only).
- A `make validate-catalog` target (not asked for).

## Knowledge used
| Entry | What it says | Why it applies here | Call (confirm / wrong / outdated / answered) | Date |
|---|---|---|---|---|
| 12 entries confirmed before, unchanged | D-004, D-006, D-010, D-021, D-023, D-024, PATTERN-006, PATTERN-008, PATTERN-009, PATTERN-012, PATTERN-013, C-001 | one Postgres; no outbox rows yet (P2); Romanian data, English keys and code; catalog written once, validated in CI, loaded without an LLM; fixed IDs from insertion order; Pydantic for the seed files; ORM only, no migration; fixtures stored verbatim; no provider call; passwords from `SEED_*`; login per C-001 | confirm | 2026-11-26 |
| PATTERN-001 | Money is an integer in minor units; shipping 1999, free from a 20000 subtotal | `price_minor` is a StrictInt > 0; the shipping policy text states 19,99 lei and 200 lei | confirm | 2026-11-26 |
| PATTERN-003 | Tool results are quoted data, never instructions | Why the injection review exists and is stored verbatim for P3 | confirm | 2026-11-26 |
| PATTERN-015 (candidate) | API tests with the DB: httpx AsyncClient + ASGITransport, rolled-back session | Test 25 (login of seeded accounts) | confirm | 2026-11-26 |
| Q-001 | Image source open | No `product_images` rows | confirm | 2026-11-26 |
| Q-002 | Delivery estimate open; placeholder "2 to 4 business days" | The shipping policy body uses "2–4 zile lucrătoare" | confirm | 2026-11-26 |
| Q-015 | Stripe test cards for demo customers open (P4) | No Stripe data seeded | confirm | 2026-11-26 |
| GH-4 code | `Email`, `Password` (`app/schemas/auth.py`), `hash_password` (`app/auth/passwords.py`) | Reused so seeded accounts pass the same rules as register and login (Q8) | confirm | 2026-11-26 |

### Considered, not applied
- PATTERN-014 (candidate, schema changes): no model or migration changes.
- PATTERN-010 / D-006 (outbox in the same transaction): `reindex_outbox` does not exist yet (P2). The seed enqueues nothing; P2 decides how the seeded catalog is first indexed.
- PATTERN-005 (fixed texts as templates): the seed's console lines are developer output, not customer-facing texts.
- PATTERN-007 (authorization dependencies): no route added.
- C-003 / C-005: not touched.

### Assumptions (no entry behind them)
- A1: `catalog.json` stays one file. Five category fragments are written by parallel workers and joined by the conductor; the fragments are never committed to the integration branch.
- A2: English category slugs `clothing`, `laundry-and-cleaning`, `cosmetics-and-personal-care`, `small-electronics`, `home`. Romanian names: Îmbrăcăminte, Detergenți și curățenie, Cosmetice și îngrijire personală, Electronice mici, Casă.
- A3: 40 products per category (200 in total); about 7 reviews per product on average (about 1,400), spread over 3–15.
- A4: `python -m seed.validate_catalog` validates `users.json` too. The loader parses it with the same models anyway, so this costs one call.
- A5: The validator's `missing_attribute` check means no `material` key in product or variant attributes and no "material" substring in the description. The `xss` check means the body contains `<script` and `onerror=`.
- A6: `rating_avg` uses `ROUND_HALF_UP` to 2 decimals.
- A7: Review `created_at` values are between 2024-01-01 and 2026-10-31 UTC (not checked by the validator).
- A8: Both `SEED_*` variables are required on every run, even when all users already exist (the AC says "refuses to run").
- A9: An existing user is skipped entirely: their addresses and preferences are not topped up.
- A10: The exit code is 1 for a refused password or invalid files; other errors propagate with a traceback after the rollback.
- A11: Phone numbers in the style `0700 000 00x`; postal codes have 6 digits.

## Gate B
- Decision: approved — 2026-11-26 — user approved the plan as written; every knowledge entry confirmed; assumptions A1–A11 accepted.
