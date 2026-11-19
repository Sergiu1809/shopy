# Plan — GH-4 P1b: Authentication and roles

> Written by /plan (planner agent, full lane, 2026-11-19); the gate B calls are recorded below by /start.
> Source of every acceptance point: the context brief in `OVERVIEW.md` (gate A answers Q1–Q18, Q8 as changed by the user).

## Size
**M, close to L.** About 20 new files and 8 edited, all in `backend/` plus docs and the ledger. No schema change
(`users` and `refresh_tokens` came with GH-3). Weight comes from the security logic (rotation, reuse detection,
timing-safe login), four rate-limit buckets, one error envelope app-wide, and a new API test harness with the DB.

## Repos · branches
`feat/auth-GH-4` (integration branch)
Tickets covered: GH-4 (Fixes)

## Approach
Brief §6 layout: routers in `backend/app/api/` (`auth.py`, `me.py`, `admin.py`), Pydantic models in
`backend/app/schemas/auth.py`, auth logic in `backend/app/auth/` (passwords, tokens, rate limit, dependencies),
the error envelope in `backend/app/errors.py`.

- **Configuration:** no settings layer, no `pydantic-settings`. `jwt_secret()` and `app_origin()` read `os.environ`
  and raise `RuntimeError`, like `app/db.py::database_url()`. A FastAPI `lifespan` in `main.py` calls `jwt_secret()`
  first (fail fast), then builds the engine and sessionmaker with the existing helpers and keeps them on `app.state`.
  Token code calls `jwt_secret()` on each sign or decode, so tests need only the env var.
- **DB session:** new `get_session` dependency in `app/db.py`, from `request.app.state.sessionmaker`. Tests override
  it with GH-3's rolled-back `session` fixture and call the app through `httpx.AsyncClient(transport=ASGITransport(app),
  base_url="https://test")` (same event loop as asyncpg; `https` so httpx sends `Secure` cookies). Not `TestClient`.
- **Request flow:** `Annotated[..., Depends(...)]` everywhere (ruff B008). Argon2 runs in `run_in_threadpool`. 409
  from `IntegrityError` on `uq_users_email_lower` (race-safe). Refresh loads the token row `FOR UPDATE`. Handlers for
  `RequestValidationError` and Starlette `HTTPException` build every error; 429 is an `HTTPException` subclass with
  `Retry-After`. Refresh and logout return envelope responses directly so they can clear the cookie.
- **Rate limiting:** `app/auth/rate_limit.py`, `FixedWindowLimiter(limit, window_s)` with module-level buckets
  `LOGIN_IP` 20/900 s, `LOGIN_ACCOUNT_FAILURES` 5/900 s, `REGISTER_IP` 5/3600 s, `REFRESH_IP` 60/60 s,
  `LOGOUT_IP` 60/60 s; `reset_all()`; clock `_now()` = `time.monotonic()` (monkeypatched in tests); autouse fixture
  resets before each test. Key = `request.client.host`; no forwarded headers trusted (production: Q-014).
- **`JWT_SECRET` in tests and CI:** `tests/conftest.py` force-sets a generated `secrets.token_urlsafe(48)` at module
  top (no literal for gitleaks; a developer's `change-me` can't leak in). `test_health.py` is unaffected (no lifespan).
  No CI workflow change.
- **`/admin` and brief test 15:** `app/api/admin.py` = `APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])`,
  no routes yet. `tests/test_admin_access.py` mounts a test-only `GET /admin/__probe` reusing the router's dependency
  list, then parametrizes over every `/admin*` path in `app.routes` (asserted non-empty): no token / invalid / expired /
  wrong-type → 401 + `WWW-Authenticate: Bearer`; customer → 403; admin → 200. GH-6 routes join automatically.
- **Rejected:** `slowapi`/`limits` (nothing gained in-process), a rate-limit table (Q4, D-004), `pydantic-settings`
  (two env reads), a `create_app()` factory (test-only extension point), `TestClient` for DB tests (loop mismatch),
  a refresh-token family column (Q3 revokes all of the user's tokens).

### New dependencies
| Package | Pin | Why |
|---|---|---|
| `argon2-cffi` | `>=25.1,<26` | Argon2id `PasswordHasher`, RFC 9106 low-memory defaults, `check_needs_rehash` (Q11); no Argon2 in stdlib |
| `PyJWT` | `>=2.10,<3` | HS256 sign/verify with `exp`/`iat` checks and `require` (Q9); typed for mypy strict |
| `email-validator` | `>=2.2,<3` | required by Pydantic `EmailStr` (Q8) |

Added with `uv add` (updates `uv.lock`; CI's `uv sync --frozen` keeps passing).

## Files
| Action | Path | What |
|---|---|---|
| edit | `backend/pyproject.toml`, `backend/uv.lock` | the three dependencies |
| edit | `backend/app/main.py` | lifespan (secret check, engine on `app.state`, dispose); CORS (one origin, credentials, GET/POST/PUT/PATCH/DELETE, Authorization/Content-Type); error handlers; auth, me, admin routers; `/health` unchanged |
| edit | `backend/app/db.py` | `get_session(request)` dependency |
| add | `backend/app/errors.py` | `ApiError(HTTPException)` with `code`; `error_response(...)`; handlers for `RequestValidationError` (field from `loc` minus `"body"`, pydantic `msg`, never `input`/`ctx`) and `HTTPException`; `install_error_handlers(app)` |
| add | `backend/app/auth/__init__.py` | package |
| add | `backend/app/auth/passwords.py` | `hash_password`, `verify_password`, `needs_rehash`, `verify_dummy`; sync, so GH-5's seed reuses them |
| add | `backend/app/auth/tokens.py` | `jwt_secret()`; access token create/decode (HS256, 900 s, claims sub/iat/exp/type); refresh token `(raw, sha256_hex)`, 30-day TTL; cookie set/clear helpers |
| add | `backend/app/auth/rate_limit.py` | limiter, the five buckets, `reset_all()`, `RateLimited` (429 + `Retry-After`), `client_ip()`, `limit_by_ip(bucket)` |
| add | `backend/app/auth/dependencies.py` | `get_current_user` (401 `unauthorized` + `WWW-Authenticate: Bearer`), `require_admin` (403 `forbidden`), `CurrentUser` |
| add | `backend/app/schemas/__init__.py`, `backend/app/schemas/auth.py` | `Email`, `Password` (8–128, ≥1 uppercase, ≥1 digit), `RegisterIn`/`LoginIn` (`extra="forbid"`), `TokenOut`, `MeOut` |
| add | `backend/app/api/__init__.py`, `auth.py`, `me.py`, `admin.py` | register (201, 409 `email_taken`), login (limits, dummy verify, generic 401, rehash), refresh (rotate; reuse → revoke all + 401 + clear cookie), logout (always 204); `GET /me`; `/admin` router |
| edit | `backend/tests/conftest.py` | env setup, autouse `reset_all()`, `client`/`client_factory(ip)`, `make_user` with hash cache, `auth_header` |
| add | `backend/tests/test_{passwords,tokens,rate_limit,startup,auth_register,auth_login,auth_refresh,me,admin_access,errors,cors}.py` | see the table below |
| edit | `.env.example` | comment above `JWT_SECRET`: at least 32 bytes or the api won't start; how to generate one |
| add | `docs/API.md` | auth routes and `/me` with examples, cookie, token body, error envelope, limits, CORS |
| edit | `docs/agents/CONTRACTS.md` | C-001 Evidence → the code paths and `docs/API.md` |
| edit | `docs/agents/PATTERNS.md` | PATTERN-006/007 Examples → the new files; candidate a new candidate pattern (next free PATTERN- ID) (A15) |
| edit | `docs/agents/ARCHITECTURE.md`, `AGENTS.md` §3 | P1b status; `app/api/`, `app/auth/`, `app/schemas/`, `app/errors.py`; `JWT_SECRET` ≥32 bytes, `APP_ORIGIN` required |

## Acceptance points → tests
| # | Acceptance point | Test kind | Not automated? why |
|---|---|---|---|
| 1 | Five routes, JSON bodies only | test_auth_*.py, test_me.py · API | |
| 2 | Argon2id defaults; rehash on login; reusable hash function | test_passwords.py · unit; test_auth_login.py · API | |
| 3 | Access JWT HS256, 15 min, sub/iat/exp/type, no role; role read from DB | test_tokens.py · unit; test_me.py · API | |
| 4 | Startup fails on missing or <32-byte `JWT_SECRET` | test_startup.py · unit | `.env.example` comment reviewed by eye |
| 5 | Token body `{access_token, token_type, expires_in: 900}` | test_auth_register/login/refresh · API | |
| 6 | Opaque refresh token stored as SHA-256 hex, 30-day sliding, old row revoked | test_auth_refresh.py · API | |
| 7 | Cookie `refresh_token; HttpOnly; Secure; SameSite=Strict; Path=/auth; Max-Age=2592000` | test_auth_* · API | |
| 8 | Reuse → 401 and all of the user's tokens revoked; expired/unknown → 401 + cookie cleared | test_auth_refresh.py · API | |
| 9 | Register: customer only; `role`/unknown field → 422; 201 + token + cookie; duplicate → 409 | test_auth_register.py · API | |
| 10 | Logout: cookie only, revokes, clears, always 204 | test_auth_refresh.py · API | |
| 11 | Login failure: one generic 401; unknown email verifies a dummy hash | test_auth_login.py · API | real timing equality not asserted (flaky) |
| 12 | Password 8–128, ≥1 uppercase, ≥1 digit | test_auth_register.py · API (parametrized) | |
| 13 | Email `EmailStr`, ≤254, trimmed and lowercased | test_auth_register.py · API | |
| 14 | `GET /me` → exactly `{id, email, role, created_at}` | test_me.py · API | |
| 15 | `/admin` router dependency; 401 + `WWW-Authenticate`; customer 403 | test_admin_access.py · unit + API | |
| 16 | Brief test 15: parametrized over every `/admin*` route | test_admin_access.py · API | |
| 17 | One envelope for 422/4xx/429; no input echo; brief test 17 (bad email) | test_errors.py · API | |
| 18 | Rate limits and 429 + `Retry-After`; no lockout | test_rate_limit.py · unit; test_auth_* · API | |
| 19 | CORS: one origin, credentials, listed methods and headers | test_cors.py · API | |
| 20 | `docs/API.md`; C-001 Evidence moved | — | doc review at gate C |
| 21 | No cleanup job (Q17) | — | absence |
| — | Existing tests unchanged and green | full `pytest` | |

## Sequencing
One builder (all parts share `main.py`, `errors.py`, `conftest.py` and the auth dependency). Test author first
(tests red), then build: deps → errors → passwords/tokens/rate_limit → schemas → dependencies → routers and main →
docs and ledger.

## Manual test plan
Not needed (Q18): no manual-test path touched. Optional smoke: ≥32-byte `JWT_SECRET` in `.env`,
`docker compose up --build`, `POST /auth/register` → 201 + `set-cookie: refresh_token=…`; with `change-me` the api exits.

## Design (UI only)
None (no UI).

## Risks
- A local `.env` with `JWT_SECRET=change-me` stops the api container at startup until a ≥32-byte secret is set (intended, Q10). Named in the PR's Observations.
- Argon2 costs ~50–100 ms and 64 MiB per hash; run in a threadpool; tests cache fixture hashes.
- DB API tests must use `ASGITransport`, never `TestClient` (event loop) → candidate a new candidate pattern (next free PATTERN- ID).
- In-memory limiter: resets on restart; wrong with several processes or behind a proxy (Q-014).
- Strict rotation: two tabs refreshing at once log out every device (approved Q3); `FOR UPDATE` makes it deterministic.
- Test 15 sends no body (a malformed body would give 422 before 403); GH-6 keeps it so.
- `APP_ORIGIN` is read at import (middleware built once): a missing value fails at import (A2).
- email-validator messages can quote one stray character of the email (A6).
- Updating C-001 and PATTERN-006/007 removes their Confirmed lines (ledger rule); re-confirm at gate C.
- Hard to reverse: nothing (no migration).

## Out of scope
Passkeys/WebAuthn (P4), password reset, email verification, any UI, real `/admin` routes (GH-6), seeded accounts
(GH-5), production cookie/site/proxy topology (Q-014, Q-011), a rate-limit table, WebSocket auth (P3), a
`refresh_tokens` cleanup job (Q17), a 500 handler, multi-process rate limiting.

## Knowledge used
| Entry | What it says | Why it applies here | Call (confirm / wrong / outdated / answered) | Date |
|---|---|---|---|---|
| D-003, D-004, D-021, D-024, PATTERN-006, PATTERN-007, PATTERN-013, C-001 | confirmed before, unchanged | stack; no Redis → in-memory limits; English messages; bigint IDs; Pydantic + 422 envelope; role dependency on `/admin`; secrets in `.env`; REST/JWT/cookie/CORS/envelope (consumer: web client, not built yet) | | |
| PATTERN-008 | SQL only through SQLAlchemy with bound params; schema only via Alembic; UTC `timestamptz` | every query (user lookup, token `FOR UPDATE`, bulk revoke) and UTC-aware `revoked_at`/`expires_at` | | |
| Q-014 | open: production same-site, cookie, proxy IP | keeps production topology out of scope; local key is `request.client.host` | | |

### Considered, not applied
- PATTERN-014 (candidate): no schema change; drift test untouched and stays green.
- PATTERN-012: no external provider called.
- PATTERN-001/002/003/004/005/009/010/011: not about auth or REST input.
- Q-011: deploy host; D-001: no UI.
- `pydantic-settings`, `slowapi`/`limits`, `create_app()`, refresh-token family column: see Approach.

### Assumptions
- **A1 Error codes:** `validation_error` 422, `invalid_credentials` login 401, `unauthorized` token/refresh 401, `forbidden` 403, `email_taken` 409, `rate_limited` 429, `not_found` 404, `method_not_allowed` 405, else `http_error`. Short English messages.
- **A2** `APP_ORIGIN` is required; missing → `RuntimeError` at import.
- **A3** Refresh and logout have separate 60/IP/min buckets.
- **A4** The login failure bucket is keyed by the normalized submitted email whether or not the account exists; success does not reset it; the 20/IP bucket counts every attempt.
- **A5** IP limits run as dependencies, so requests that fail validation still count.
- **A6** `extra="forbid"` on `LoginIn` too; login password `str` 1–128, no composition rule; malformed login email → 422; email messages are Pydantic's.
- **A7** "Uppercase" = any `str.isupper()` character (Romanian diacritics count); "digit" = ASCII 0–9; length in characters.
- **A8** Logout with an already revoked token → 204, no reuse revocation (only refresh does that).
- **A9** Refresh without a cookie → 401 `unauthorized`, cookie cleared.
- **A10** `Retry-After` = whole seconds to the window end, at least 1.
- **A11** Expired limiter keys are swept past 10 000 keys per bucket.
- **A12** conftest force-sets a generated `JWT_SECRET` and `APP_ORIGIN=https://app.test`.
- **A13** `/me` `id` is a JSON integer.
- **A14** Routers in `app/api/`, schemas in `app/schemas/` (brief §6); ARCHITECTURE.md updated.
- **A15** Candidate a new candidate pattern (next free PATTERN- ID): API tests with the DB use httpx `AsyncClient` + `ASGITransport` (`https://test`, `get_session` override, vary IP via `client=`), never `TestClient` with DB fixtures. Example: `backend/tests/conftest.py`.

## Gate B
- Decision: pending
