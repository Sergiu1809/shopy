---
ticket: GH-4
type: task
parent:
covers: []
delivered_in:
title: "P1b: Authentication and roles"
status: in-progress
lane: full
branch: feat/auth-GH-4
pr: TBD
design_refs: []
summary: "Email + password auth (Argon2id, 15-min JWT, rotating refresh cookie), roles, rate limits, CORS, one error envelope"
created: 2026-11-19 00:00
updated: 2026-11-19 00:00
---

# GH-4 — P1b: Authentication and roles

## Goal
Customers and admins can sign in, and every route knows who is calling and what they
may do (brief §3, §14, §16; C-001). GH-5 (seed) is blocked by this ticket because it
needs the password hashing; GH-6 (admin CRUD) relies on the role dependency.
Ticket: https://github.com/Sergiu1809/shopy/issues/4

## Context brief 🧾
- **Acceptance criteria (approved, GH-4; ticket text + gate A answers 2026-11-19, user):**
  - [ ] Routes `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /me`. JSON bodies (no form login).
  - [ ] Passwords hashed with Argon2id: `argon2-cffi` `PasswordHasher` defaults (RFC 9106 low-memory: t=3, m=64 MiB, p=4); rehash on login when `check_needs_rehash` is true. The hash function is reusable by the seed (GH-5). (Q11)
  - [ ] Access token: JWT HS256 (PyJWT), signed with `JWT_SECRET` from env, valid 15 min. Claims `sub` (user ID as string), `iat`, `exp`, `type: "access"`; no role in the token. The auth dependency loads the user from the DB on every request, so roles come from the DB. Sent by the client in `Authorization: Bearer`. (C-001, Q9)
  - [ ] Startup fails if `JWT_SECRET` is missing or shorter than 32 bytes; the `.env.example` comment says so (the `change-me` placeholder would fail). Tests set their own secret. (Q10)
  - [ ] Login, register and refresh return `{"access_token": "...", "token_type": "bearer", "expires_in": 900}` in the body. (Q7)
  - [ ] Refresh token: opaque `secrets.token_urlsafe(32)`, stored as its SHA-256 hex in `refresh_tokens.token_hash` (unique lookup). Lifetime 30 days, sliding (each rotation issues a new token with a fresh 30-day expiry), a code constant, not env. Rotated on every use: the old row gets `revoked_at`. (Q5, Q12)
  - [ ] Refresh cookie: name `refresh_token`; `HttpOnly; Secure; SameSite=Strict; Path=/auth; Max-Age=` 30 days. (Q7)
  - [ ] Reuse of a revoked (rotated or logged-out) refresh token → 401, and every active refresh token of that user is revoked (all devices logged out). Expired or unknown token → 401 and the cookie is cleared. (Q3)
  - [ ] Register: always creates a `customer`; a `role` field (or any unknown field) is rejected with 422 (`extra="forbid"`). Register logs in: 201 with the access token body and the refresh cookie. Duplicate email (case-insensitive) → 409. Admins exist only through the seed (GH-5). (Q6)
  - [ ] Logout: needs only the cookie (no access token); revokes that refresh token, clears the cookie, always 204, also when the cookie is missing or invalid. Issued access tokens stay valid until they expire (max 15 min). (Q6)
  - [ ] Login failure: one generic 401 "invalid email or password"; for an unknown email, verify against a dummy hash so timing does not reveal it. (Q13)
  - [ ] Password: 8–128 characters, at least one uppercase letter and at least one digit; no other composition rules. (Q8, changed by the user at gate A)
  - [ ] Email: `EmailStr` (`email-validator`), max 254 characters, trimmed and lowercased on input (matches `uq_users_email_lower`). (Q8)
  - [ ] `GET /me` returns `{id, email, role, created_at}`; never `stripe_customer_id` or `password_hash`. (Q14)
  - [ ] Roles enforced in FastAPI dependencies (PATTERN-007): an `/admin` APIRouter carries the admin dependency at router level. No, invalid or expired token → 401 with `WWW-Authenticate: Bearer`; a customer → 403. (Q2)
  - [ ] Brief test 15: a parametrized test enumerates every `app.routes` path starting with `/admin` and asserts 403 for a customer; a test-only admin route makes it non-empty now, and GH-6's routes are covered automatically. (Q2)
  - [ ] One error envelope for every error (422, other 4xx, 429), from handlers for `RequestValidationError`, `HTTPException` and the rate limiter: `{"error": {"code": "...", "message": "...", "fields": [{"field": "...", "message": "..."}]}}` (`fields` only where relevant). It never echoes the input (no password in a response). Test 17: e.g. a bad email gives 422 with a useful message. (Q1; C-001 amended)
  - [ ] Rate limits, in-process memory (fixed window, no new dependency, no table; single api process, limitation written down; P7 revisits, Q-014), all returning 429 with `Retry-After` and no account lockout (Q4):
    - login: 5 failed attempts per account per 15 min, and 20 attempts per IP per 15 min;
    - register: 5 per IP per hour;
    - refresh and logout: 60 per IP per minute.
  - [ ] CORS: exactly one origin, `APP_ORIGIN`; `allow_credentials=True`; methods GET, POST, PUT, PATCH, DELETE; headers `Authorization`, `Content-Type`. (Q15)
  - [ ] `docs/API.md` created with examples for the auth routes and `GET /me`; C-001 Evidence moved to the code paths. (Q16)
  - [ ] Tests: register, login, refresh rotation, logout, reuse of a revoked refresh token fails (and revokes the user's other tokens), the 403/401 matrix, the 422 envelope, the rate limits, the cookie attributes.
  - [ ] No cleanup job for expired or revoked `refresh_tokens` rows. (Q17)
  - [ ] Manual test: not needed (`backend/app/auth/` is not on a manual-test path; only `backend/app/auth/webauthn*` is). (Q18)
- **Out of scope:** passkeys/WebAuthn (P4), password reset, email verification, any UI, the real `/admin` routes (GH-6), seeded accounts (GH-5), production site/cookie/proxy topology (Q-014, with Q-011), a rate-limit table, WebSocket auth (P3).
- **Scope overlaps:**
  - GH-5 creates the admin and demo customers with GH-4's hash function; GH-4 tests insert their admin directly through a DB fixture.
  - GH-6 adds `/admin` routes and expects 401 without a token and 403 for a customer (as above).
- **Tickets covered:** GH-4 (Fixes)
- **Constraints that apply:**
  - C-001 — REST API: JWT in Authorization header, rotating refresh token in an httpOnly Secure cookie, CORS to `APP_ORIGIN`, auth routes rate limited, one error envelope (amended 2026-11-19).
  - PATTERN-006 — every input validated with Pydantic; invalid input → 422 in the one format.
  - PATTERN-007 — role dependency on every `/admin` route; ownership checks on customer resources.
  - PATTERN-008 — SQL only through SQLAlchemy with bound parameters; schema only through Alembic.
  - PATTERN-013 — secrets only in `.env`; every variable named in `.env.example`.
  - D-003 — FastAPI, Pydantic v2, async SQLAlchemy 2.
  - D-004 — one Postgres database; no Redis (hence in-process rate limits).
  - D-021 — English error messages, code and docs.
  - D-024 — bigint identity keys; IDs are never a security boundary.
  - Q-014 — open: production same-site/cookie/proxy-IP (blocks P7, not GH-4).
- **New dependencies to approve at gate B:** `argon2-cffi`, `PyJWT`, `email-validator`. A settings layer (`pydantic-settings`) only with a concrete reason; `backend/app/db.py` reads `os.environ` today.
- **Where the code is:** `backend/app/models/user.py` (`User`, `RefreshToken`, from GH-3), `backend/app/main.py`, `backend/app/db.py`, `backend/tests/conftest.py`; new: `backend/app/auth/` (passwords, tokens, rate_limit, dependencies), `backend/app/api/` (auth, me, admin), `backend/app/schemas/auth.py`, `backend/app/errors.py`, `docs/API.md`; tests `backend/tests/test_{passwords,tokens,rate_limit,startup,auth_register,auth_login,auth_refresh,me,admin_access,errors,cors}.py`.
- **Ownership:** integration owner: conductor · one builder for the whole delivery (shared `main.py`, `errors.py`, `conftest.py`, auth dependency) · test author first · no worker branches.
- **Verify with:** `cd backend && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`; `python3 docs/agents/tools/ledger-lint.py`; `uvx pre-commit run --all-files` (gitleaks). DB tests need Docker.

## Resume here ⏯
Plan written (`PLAN.md`), gate B pending: the user approves the plan, calls PATTERN-008 and Q-014,
confirms assumptions A1–A15 and gives the go to push and open the draft PR. Resumed 2026-11-19
after GH-8 (rebased on main). Branch `feat/auth-GH-4` is local only (not pushed).

## Summary of work so far
- 2026-11-19 — Product owner: coverage report; gate A answered by the user (all recommendations accepted, password rule changed to 8–128 with one uppercase and one digit; C-001 envelope approved). Q-014 added.

## Approach
<planner: link PLAN.md and TESTS.md>

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| add | `docs/agents/tasks/GH-4/OVERVIEW.md` | journal and context brief |
| edit | `docs/agents/OPEN-QUESTIONS.md` | Q-014 (production same-site/cookie/proxy IP) |

## Manual verification 🔧
none: no manual-test path changed (Q18).

## Decisions log 🧭
- **2026-11-19 — Gate A answers Q1–Q18 as listed in the context brief** — Why: user accepted the product owner's recommendations; Q8 changed by the user. Rejected: FastAPI default errors (echo input, two shapes); a Postgres rate-limit table (not needed for one process); access-only logout.

## Open questions / blockers
- [ ] Q-014 — production site/cookie/proxy topology (blocks P7 only).

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/4
- PR: TBD
