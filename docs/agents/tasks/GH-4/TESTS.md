# Tests — GH-4

> Written by the test author before any code. Every new test failed first, for the right reason.

## Summary
- Added: 147 tests · 51 unit (no database), 96 integration (API + Postgres through testcontainers)
- Approach: API tests call the real app through httpx `AsyncClient` + `ASGITransport`
  (`base_url="https://test"`, so the `Secure` cookie comes back; client IP set per client
  for the rate limits), with `get_session` overridden to GH-3's rolled-back `session`
  (A15). DB state is checked with plain SQL. `conftest.py` force-sets a generated
  `JWT_SECRET` and `APP_ORIGIN=https://app.test` at import (A12), resets the rate-limit
  buckets before and after every test (autouse), and inserts users directly
  (`make_user`, one cached Argon2 hash per password; admins only this way, GH-5 seeds
  the real ones). PyJWT and argon2 are imported inside the tests that craft tokens or
  hashes.
- Existing tests changed: 0 · removed: 0 (`conftest.py` gained fixtures and helpers; the
  GH-3 fixtures are unchanged, its docstring got one GH-4 paragraph).

### Interfaces the tests pin (the builder follows these names)
| Module | Name | Contract the tests assume |
|---|---|---|
| `app.auth.passwords` | `hash_password(password) -> str` | Argon2id, `PasswordHasher()` defaults (`m=65536,t=3,p=4`) |
| | `verify_password(password, password_hash) -> bool` | **password first**; `False` on mismatch or a malformed hash, never raises |
| | `needs_rehash(password_hash) -> bool` | `PasswordHasher().check_needs_rehash` |
| | `verify_dummy(password) -> None` | exactly one `PasswordHasher.verify` call on an `$argon2id$` hash |
| `app.auth.tokens` | `jwt_secret() -> str` | `RuntimeError` naming `JWT_SECRET` when missing or < 32 UTF-8 bytes |
| | `create_access_token(user_id: int) -> str` | HS256, claims exactly `sub` (str), `iat`, `exp` (= iat + 900), `type="access"`; secret read on each call |
| `app.auth.rate_limit` | `FixedWindowLimiter(limit, window_s)` | attributes `limit`, `window_s`; `hit(key)` records an attempt and raises `RateLimited` once the limit is passed |
| | `RateLimited` | Starlette `HTTPException` subclass, 429, `headers["Retry-After"]` whole seconds ≥ 1 |
| | `LOGIN_IP`, `LOGIN_ACCOUNT_FAILURES`, `REGISTER_IP`, `REFRESH_IP`, `LOGOUT_IP` | 20/900, 5/900, 5/3600, 60/60, 60/60; five distinct objects |
| | `reset_all()`, `_now()` | `_now` is looked up at call time (tests monkeypatch it) |
| `app.auth.dependencies` | `require_admin` | used as `Depends(require_admin)` |
| `app.api.admin` | `router` | `prefix="/admin"`, `Depends(require_admin)` in `router.dependencies` |
| `app.db` | `get_session(request)` | async generator yielding an `AsyncSession` from `request.app.state.sessionmaker` |
| `app.main` | `app` | lifespan checks `jwt_secret()` before anything else, then keeps `app.state.sessionmaker`; importing it without `APP_ORIGIN` fails with a message naming `APP_ORIGIN` |

Schema module names (`app.schemas.auth`) and `app.errors` are not imported by the tests:
they are exercised through the API only.

## Acceptance point → tests
| # | Ticket | Acceptance point | File | Test(s) | Red reason before code |
|---|---|---|---|---|---|
| 1 | GH-4 | Five routes, JSON bodies only | `test_auth_register.py`, `test_auth_login.py`, `test_auth_refresh.py`, `test_me.py` | every API test; `test_register_takes_json_only`, `test_login_takes_json_only` | `ModuleNotFoundError: app.auth` / `app.db.get_session` missing; routes 404 |
| 2 | GH-4 | Argon2id defaults; rehash on login; reusable hash function | `test_passwords.py`; `test_auth_login.py` | `test_hash_is_argon2id_with_rfc9106_low_memory_defaults`, `test_hash_is_salted`, `test_verify_password_*`, `test_needs_rehash_for_weaker_parameters`; `test_login_rehashes_a_weak_hash`, `test_login_keeps_a_current_hash` | `ModuleNotFoundError: app.auth`; argon2 not installed |
| 3 | GH-4 | Access JWT HS256, 15 min, sub/iat/exp/type, no role; role from DB | `test_tokens.py`; `test_me.py`; `test_admin_access.py` | `test_access_token_is_hs256_with_the_four_claims`, `test_access_token_lives_15_minutes`, `test_access_token_is_signed_with_the_current_env_secret`; `test_me_reads_the_role_from_the_database`, `test_me_for_a_deleted_user_is_401`; `test_a_customer_promoted_in_the_db_reaches_admin_with_the_same_token`, `test_a_bad_token_of_an_admin_gets_401[*]` (garbage, expired, wrong/no type, no exp, no/non-numeric sub, wrong secret, alg none) | `ModuleNotFoundError: app.auth` / `app.api` |
| 4 | GH-4 | Startup fails on missing or < 32-byte `JWT_SECRET` | `test_tokens.py`; `test_startup.py` | `test_jwt_secret_*`; `test_startup_fails_without_jwt_secret`, `test_startup_fails_with_a_short_jwt_secret[*]`, `test_secret_is_checked_before_the_database`, `test_startup_with_a_strong_secret_keeps_a_sessionmaker` | `DID NOT RAISE RuntimeError` (no lifespan); `State` has no `sessionmaker` |
| 5 | GH-4 | Token body `{access_token, token_type, expires_in: 900}` | `test_auth_register.py`, `test_auth_login.py`, `test_auth_refresh.py` | `assert_token_body` in the register, login and refresh success tests | routes missing |
| 6 | GH-4 | Opaque refresh token, SHA-256 hex stored, 30-day sliding, old row revoked | `test_auth_refresh.py`; `test_auth_login.py` | `test_refresh_rotates_the_token`, `test_refresh_stores_only_the_sha256_of_the_token`, `test_refresh_gives_a_fresh_30_day_expiry`, `test_refresh_chain_with_the_client_cookie_jar`; `test_login_returns_the_token_body_and_the_refresh_cookie` | routes missing |
| 7 | GH-4 | Cookie `refresh_token; HttpOnly; Secure; SameSite=Strict; Path=/auth; Max-Age=2592000` | conftest `issued_refresh_token` / `assert_refresh_cookie_cleared`, used in register, login, refresh, logout tests | every test that reads or clears the cookie | routes missing |
| 8 | GH-4 | Reuse → 401 + all of the user's tokens revoked; expired/unknown → 401 + cookie cleared | `test_auth_refresh.py` | `test_reuse_of_a_rotated_token_revokes_every_token_of_the_user` (other users untouched), `test_reuse_of_a_logged_out_token_revokes_every_token_of_the_user`, `test_refresh_with_an_expired_token_is_401_and_clears_the_cookie`, `test_refresh_with_an_unknown_token_is_401_and_clears_the_cookie`, `test_refresh_without_a_cookie_is_401_and_clears_the_cookie` (A9), `test_refresh_ignores_an_access_token` | routes missing |
| 9 | GH-4 | Register: customer only; `role`/unknown field 422; 201 + token + cookie; duplicate 409 | `test_auth_register.py` | `test_register_creates_a_customer_and_logs_in`, `test_register_rejects_a_role_field[*]`, `test_register_rejects_any_unknown_field`, `test_register_duplicate_email_is_409[*]`, `test_register_duplicate_of_a_seeded_admin_is_409`, `test_register_needs_email_and_password` | routes missing |
| 10 | GH-4 | Logout: cookie only, revokes, clears, always 204 | `test_auth_refresh.py` | `test_logout_revokes_the_token_and_clears_the_cookie`, `test_logout_needs_no_access_token_and_leaves_it_valid`, `test_logout_without_a_cookie_is_204`, `test_logout_with_an_unknown_cookie_is_204`, `test_logout_with_a_revoked_token_is_204_without_reuse_revocation` (A8), `test_logout_with_an_expired_token_is_204` | routes missing |
| 11 | GH-4 | Login failure: one generic 401; unknown email verifies a dummy hash | `test_auth_login.py`; `test_passwords.py` | `test_wrong_password_and_unknown_email_get_the_same_generic_401`, `test_unknown_email_still_runs_an_argon2_verify`; `test_verify_dummy_runs_a_real_argon2_verify` | routes / `app.auth` missing |
| 12 | GH-4 | Password 8–128, ≥ 1 uppercase, ≥ 1 digit (A7) | `test_auth_register.py`; `test_auth_login.py` | `test_register_accepts_valid_passwords[*]` (8, 128, `Ă`, spaces), `test_register_rejects_invalid_passwords[*]` (7, 129, no upper, no digit, Arabic-Indic digits, empty); login A6: `test_login_password_must_be_1_to_128_characters[*]`, `test_login_password_has_no_composition_rule` | routes missing |
| 13 | GH-4 | Email `EmailStr`, ≤ 254, trimmed and lowercased; one fixed message (A6) | `test_auth_register.py`; `test_auth_login.py` | `test_register_trims_and_lowercases_the_email`, `test_register_accepts_a_254_character_email`, `test_register_rejects_invalid_emails_with_one_fixed_message[*]` (incl. 255 chars); `test_login_trims_and_lowercases_the_email`, `test_login_malformed_email_is_422_with_the_fixed_message`, `test_login_rejects_unknown_fields` | routes missing |
| 14 | GH-4 | `GET /me` → exactly `{id, email, role, created_at}`; `id` an integer (A13) | `test_me.py` | `test_me_returns_exactly_id_email_role_created_at`, `test_me_without_a_valid_token_is_401_with_www_authenticate[*]` | route missing |
| 15 | GH-4 | `/admin` router dependency; 401 + `WWW-Authenticate: Bearer`; customer 403 | `test_admin_access.py` | `test_admin_router_carries_require_admin_at_router_level`, `test_every_admin_route_depends_on_require_admin[*]`, `test_no_token_gets_401_on_every_admin_route[*]`, `test_a_bad_token_of_an_admin_gets_401[*]`, `test_admin_reaches_the_probe` | `ModuleNotFoundError: app.api` |
| 16 | GH-4 | Brief test 15: parametrized over every `/admin*` route | `test_admin_access.py` | `test_there_is_at_least_one_admin_route`, `test_customer_gets_403_on_every_admin_route[*]` (test-only `GET /admin/__probe` today; GH-6 routes join on collection) | `ModuleNotFoundError: app.api` |
| 17 | GH-4 | One envelope for 422/4xx/429; no input echo; brief test 17 | `test_errors.py`; conftest `assert_error` (used by every error assertion) | `test_bad_email_gives_422_with_a_useful_message`, `test_422_never_echoes_the_password`, `test_422_for_a_wrong_type_does_not_echo_the_value`, `test_malformed_json_gives_the_envelope`, `test_every_field_error_is_listed`, `test_unknown_route_is_404_in_the_envelope`, `test_wrong_method_is_405_in_the_envelope`, `test_401_409_429_use_the_envelope` | `get_session` missing; FastAPI's default `{"detail": …}` |
| 18 | GH-4 | Rate limits, 429 + `Retry-After`, no lockout (A3, A4, A5, A10) | `test_rate_limit.py`; `test_auth_login.py`, `test_auth_register.py`, `test_auth_refresh.py` | limiter unit tests and `test_the_five_buckets[*]`; `test_login_is_limited_to_20_attempts_per_ip`, `test_login_is_limited_to_5_failures_per_account`, `test_account_limit_uses_the_normalized_email`, `test_account_limit_also_counts_unknown_emails`, `test_a_success_does_not_reset_the_failure_count`, `test_no_lockout_the_account_works_again_after_the_window`; `test_register_is_limited_to_5_per_ip_per_hour`, `test_register_limit_counts_invalid_requests`; `test_refresh_is_limited_to_60_per_ip_per_minute`, `test_logout_is_limited_to_60_per_ip_per_minute`, `test_refresh_and_logout_have_separate_buckets` | `ModuleNotFoundError: app.auth`; routes missing |
| 19 | GH-4 | CORS: one origin, credentials, listed methods and headers; `APP_ORIGIN` required (A2) | `test_cors.py`; `test_startup.py` | `test_preflight_from_app_origin_is_allowed`, `test_preflight_allows_each_listed_method[*]`, `test_preflight_rejects_another_method`, `test_preflight_rejects_another_header`, `test_preflight_rejects_other_origins[*]`, `test_simple_requests_get_cors_headers_only_for_app_origin`; `test_app_origin_is_required_at_import` | no CORS middleware: preflight 405/404, no `access-control-*` headers; import succeeds without `APP_ORIGIN` |
| — | GH-4 | Existing tests unchanged and green | all GH-3 test files | full `pytest` | n/a (must stay green) |

## Not automated
| Acceptance point | Why | Covered by |
|---|---|---|
| 4 — `.env.example` comment above `JWT_SECRET` | text for people | reviewer |
| 11 — equal timing for unknown and known emails | wall-clock timing is flaky in CI; the dummy verify call is asserted instead | reviewer |
| 18 — A11 sweep of expired limiter keys past 10 000 per bucket | internal memory hygiene, no observable behaviour without pinning private state | reviewer |
| 18 — the limitation (single process, resets on restart) written down | documentation | reviewer (`docs/API.md`) |
| 20 — `docs/API.md`; C-001 Evidence moved | documentation | reviewer at gate C |
| 21 — no cleanup job for `refresh_tokens` (Q17) | an absence | reviewer |
| Manual tests | none needed (Q18): `backend/app/auth/` is not a manual-test path (only `backend/app/auth/webauthn*` is) | — |

## Changes after a logic change
| Date | Test | What changed | Why (trigger) |
|---|---|---|---|

## Reproductions for in-delivery fixes
| Date | Defect | Test | Red reason before the fix |
|---|---|---|---|

## Mechanical fixes by the builder
| Date | Test | Fix | Checked by reviewer |
|---|---|---|---|
