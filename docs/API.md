# Shopy API

REST examples for the web client (C-001). The full schema is served by the api at
`/docs` and `/openapi.json`. WebSocket messages (C-002) arrive with P3.

Built so far: `GET /health`, the auth routes and `GET /me` (GH-4). The `/admin` router
exists with its admin dependency; its routes arrive with GH-6.

## Conventions

- JSON bodies only (`Content-Type: application/json`); unknown fields are rejected
  with 422, reported as `"field": "body"` (the unknown name is not echoed).
- **Access token:** a JWT (HS256, 15 min) in `Authorization: Bearer <token>`. It
  carries only the user ID; the role is read from the database on every request.
- **Refresh token:** an opaque token in the `refresh_token` cookie, sent only to
  `/auth/*`:
  `refresh_token=<token>; HttpOnly; Max-Age=2592000; Path=/auth; SameSite=strict; Secure`.
  30 days, renewed on every refresh (sliding). The server stores only its SHA-256.
- **CORS:** only `APP_ORIGIN`, with credentials; methods GET, POST, PUT, PATCH,
  DELETE; headers `Authorization`, `Content-Type`. The client sends requests to
  `/auth/*` with `credentials: "include"`.
- **Token body** (register, login, refresh):

```json
{"access_token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "bearer", "expires_in": 900}
```

### Errors
Every error uses one envelope. `fields` appears only on validation errors (422); the
submitted input is never sent back.

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "email", "message": "Invalid email address."}]}}
```

| Status | `code` | When |
|---|---|---|
| 422 | `validation_error` | invalid body, unknown field, malformed JSON |
| 401 | `invalid_credentials` | login with a wrong email or password (one generic answer) |
| 401 | `unauthorized` | missing, invalid or expired access token (`WWW-Authenticate: Bearer`); invalid refresh cookie |
| 403 | `forbidden` | a customer on `/admin` |
| 404 | `not_found` | unknown route |
| 405 | `method_not_allowed` | wrong method |
| 409 | `email_taken` | register with an email that exists (case-insensitive) |
| 429 | `rate_limited` | a rate limit is reached (`Retry-After: <seconds>`) |

### Rate limits
Fixed windows, counted in the api process's memory: they reset when the api restarts
and are only correct with one api process. The key is the client address the api
sees; no forwarded header is trusted (production topology: Q-014). No account is ever
locked: a limit ends with its window.

| Route | Limit |
|---|---|
| `POST /auth/login` | 20 attempts per IP per 15 min, and 5 failed attempts per email per 15 min (the 6th attempt gets 429, even with the right password; attempts still in progress count, so parallel requests cannot get past the limit) |
| `POST /auth/register` | 5 per IP per hour (invalid requests count) |
| `POST /auth/refresh` | 60 per IP per minute |
| `POST /auth/logout` | 60 per IP per minute (a bucket of its own) |

## Auth

### `POST /auth/register`
Creates a customer and signs them in. The email is trimmed and lowercased (at most 254
characters). Password: 8–128 characters, at least one uppercase letter and one digit
(0–9). A `role` field is rejected: admins exist only through the seed.

```http
POST /auth/register
Content-Type: application/json

{"email": "ana@example.ro", "password": "<password>"}
```

`201 Created` with the token body and `Set-Cookie: refresh_token=…`.
Errors: 409 `email_taken`, 422 `validation_error`, 429.

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "password", "message": "Password must contain at least one uppercase letter and one digit."}]}}
```

### `POST /auth/login`

```http
POST /auth/login
Content-Type: application/json

{"email": "ana@example.ro", "password": "<password>"}
```

`200 OK` with the token body and `Set-Cookie: refresh_token=…`. A wrong password and
an unknown email get the same answer:

```json
{"error": {"code": "invalid_credentials", "message": "Invalid email or password."}}
```

### `POST /auth/refresh`
No body, no access token: only the cookie. Rotates the refresh token (the old one is
revoked) and returns a new access token.

```http
POST /auth/refresh
Cookie: refresh_token=<token>
```

`200 OK` with the token body and a new `Set-Cookie: refresh_token=…`.
A missing, unknown or expired cookie gets 401 `unauthorized` and clears it:
`Set-Cookie: refresh_token=""; expires=<now>; HttpOnly; Max-Age=0; Path=/auth; SameSite=strict; Secure`.
A revoked token presented again (already rotated or logged out) is treated as stolen:
401, and every active refresh token of that user is revoked (all devices signed out).
Two tabs refreshing with the same cookie at once trigger this too.

### `POST /auth/logout`
Only the cookie. Revokes that refresh token and clears the cookie. Always
`204 No Content`, also without a cookie or with an invalid one. Access tokens already
issued stay valid until they expire (at most 15 min); the client drops its copy.

```http
POST /auth/logout
Cookie: refresh_token=<token>
```

## Me

### `GET /me`

```http
GET /me
Authorization: Bearer <access token>
```

```json
{"id": 1, "email": "ana@example.ro", "role": "customer", "created_at": "2026-11-19T10:15:00.123456Z"}
```

Without a valid token: 401 `unauthorized` with `WWW-Authenticate: Bearer`.

## Health

### `GET /health`
`200 OK` `{"status": "ok"}`.
