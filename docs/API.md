# Shopy API

REST examples for the web client (C-001). The full schema is served by the api at
`/docs` and `/openapi.json`. WebSocket messages (C-002) arrive with P3.

Built so far: `GET /health`, the auth routes and `GET /me` (GH-4); the admin product
and variant routes (GH-6).

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
submitted input is never sent back. One exception: a CORS preflight that is not
allowed gets Starlette's `400` with a plain-text body such as `Disallowed CORS origin`
(no input echoed; the browser never shows that body to the page).

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "email", "message": "Invalid email address."}]}}
```

| Status | `code` | When |
|---|---|---|
| 422 | `validation_error` | invalid body, query or path parameter; unknown field; malformed JSON; an unknown `category_id` (admin) |
| 401 | `invalid_credentials` | login with a wrong email or password (one generic answer) |
| 401 | `unauthorized` | missing, invalid or expired access token (`WWW-Authenticate: Bearer`); invalid refresh cookie |
| 403 | `forbidden` | a customer on `/admin` |
| 404 | `not_found` | unknown route; an unknown product or variant ID in the path (admin) |
| 405 | `method_not_allowed` | wrong method |
| 409 | `email_taken` | register with an email that exists (case-insensitive) |
| 409 | `sku_taken` | a variant SKU that another variant already has (admin) |
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

## Admin · products

Every `/admin` route needs an admin: no token gets 401 `unauthorized`, a customer gets
403 `forbidden`. The role is checked before the body is validated, so a customer
never learns what a valid body looks like (only body text that is not JSON at all gets
its 422 first). No images (Q-001), reviews or categories here.

- **IDs** in the path are integers 1…2^63−1; anything else (`0`, `-1`, `abc`) is 422.
  An ID that no row has is 404 `not_found` (`"Product not found."` or
  `"Variant not found."`). A variant is found only under its own product:
  `/admin/products/2/variants/7` is 404 when variant 7 belongs to product 1.
- **Writable fields.** Product: `category_id`, `brand`, `name`, `description`,
  `attributes`. Variant: `sku`, `attributes`, `price_minor`, `stock`. Everything else
  (`id`, `store_id`, `product_id`, `rating_avg`, `rating_count`, `version`) is an
  unknown field: 422 under `"field": "body"`. `store_id` is always the store's own.
- **Text** (`brand`, `name`, `description`, variant attribute values) is trimmed and
  must not be empty; there is no maximum length.
- **`category_id`** must be a category of the store; otherwise 422 under
  `category_id` (`"Unknown category."`).
- **`attributes`** is replaced whole on PATCH, never merged. Keys match
  `^[a-z][a-z0-9_]*$`. Product values: text, whole number, `true`/`false`, or a list
  of text. Variant values: non-empty text. Any problem is one 422 under
  `attributes`; the bad key is never named. `{}` is valid.
- **`price_minor`** (bani, VAT included) and **`stock`**: integers 0…2147483647.
  `"100"`, `1.5`, `100.0` and `true` are not integers (422).
- **`sku`**: `^[A-Z0-9]+(-[A-Z0-9]+)*$`, unique across the store (409 `sku_taken`).
- **PATCH** sends only the fields to change; `{}` is valid and changes nothing.
  `null` is rejected (422 `"must not be null"`), although `/docs` shows the PATCH
  fields as nullable. No `If-Match`: the last write wins.
- **Versions** go up by one in SQL, and only when a value really changes (sending a
  field with its current value, or attributes in another key order, changes nothing;
  `1` → `true` is a change). Every response carries `version`.

| Change | `products.version` | variant `version` |
|---|---|---|
| a product field | +1 | — |
| a variant created or deleted | +1 | — |
| a variant's `sku` or `attributes` | +1 | — |
| a variant's `price_minor` or `stock` | — | +1 |
| `{}` or the same values | — | — |

- **DELETE** is permanent. Deleting a product deletes its variants, images and reviews
  with it. The last variant of a product may be deleted. Both answer
  `204 No Content`.

### `GET /admin/products`
`limit` 1–100 (default 50) and `offset` (default 0), ordered by `id`; no search or
filters. Items have no `variants`. `rating_avg` is a string with two decimals, or
`null` while the product has no reviews.

```http
GET /admin/products?limit=2&offset=0
Authorization: Bearer <access token>
```

```json
{"items": [{"id": 1, "store_id": 1, "category_id": 1, "brand": "Nike",
            "name": "Hanorac Nike Club", "description": "Hanorac cu glugă reglabilă.",
            "attributes": {"material": "bumbac", "fit": "regular"},
            "rating_avg": "4.30", "rating_count": 7, "version": 3,
            "updated_at": "2026-11-26T10:15:00.123456Z"},
           {"id": 2, "…": "…"}],
 "total": 200}
```

A bad `limit` or `offset` is reported with its location:

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "query.limit", "message": "Input should be less than or equal to 100"}]}}
```

### `POST /admin/products`
Every writable field is required. The product starts without variants (add them with
`POST /admin/products/{id}/variants`), with `version` 1.

```http
POST /admin/products
Authorization: Bearer <access token>
Content-Type: application/json

{"category_id": 1, "brand": "Nike", "name": "Hanorac Nike Club",
 "description": "Hanorac cu glugă reglabilă.",
 "attributes": {"material": "bumbac", "fit": "regular"}}
```

`201 Created` with the product detail:

```json
{"id": 201, "store_id": 1, "category_id": 1, "brand": "Nike", "name": "Hanorac Nike Club",
 "description": "Hanorac cu glugă reglabilă.",
 "attributes": {"material": "bumbac", "fit": "regular"},
 "rating_avg": null, "rating_count": 0, "version": 1,
 "updated_at": "2026-11-26T10:15:00.123456Z", "variants": []}
```

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "category_id", "message": "Unknown category."}]}}
```

### `GET /admin/products/{id}`
The product detail: the list item plus its `variants`, ordered by `id`.

```json
{"id": 1, "store_id": 1, "category_id": 1, "brand": "Nike", "name": "Hanorac Nike Club",
 "description": "Hanorac cu glugă reglabilă.", "attributes": {"material": "bumbac"},
 "rating_avg": "4.30", "rating_count": 7, "version": 3,
 "updated_at": "2026-11-26T10:15:00.123456Z",
 "variants": [{"id": 1, "product_id": 1, "sku": "CLO-001-NEGRU-M",
               "attributes": {"size": "M", "color": "negru"},
               "price_minor": 24999, "stock": 17, "version": 1}]}
```

```json
{"error": {"code": "not_found", "message": "Product not found."}}
```

### `PATCH /admin/products/{id}`
Any subset of the writable product fields; answers `200 OK` with the product detail.

```http
PATCH /admin/products/1
Authorization: Bearer <access token>
Content-Type: application/json

{"name": "Hanorac Nike Club Fleece", "attributes": {"material": "bumbac", "fit": "oversize"}}
```

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "attributes", "message": "Attributes must map lowercase keys (a-z, 0-9, _) to text, whole numbers, true/false or lists of text."}]}}
```

### `DELETE /admin/products/{id}`
`204 No Content`; the variants, images and reviews go with it.

### `GET /admin/products/{id}/variants`
A plain array of the product's variants, ordered by `id` (`[]` when it has none).

```json
[{"id": 1, "product_id": 1, "sku": "CLO-001-NEGRU-M",
  "attributes": {"size": "M", "color": "negru"},
  "price_minor": 24999, "stock": 17, "version": 1}]
```

### `POST /admin/products/{id}/variants`
Every writable field is required. `201 Created` with the variant (`version` 1); the
product's `version` goes up by one.

```http
POST /admin/products/1/variants
Authorization: Bearer <access token>
Content-Type: application/json

{"sku": "CLO-001-NEGRU-L", "attributes": {"size": "L", "color": "negru"},
 "price_minor": 24999, "stock": 12}
```

```json
{"error": {"code": "sku_taken", "message": "This SKU is already in use."}}
```

### `PATCH /admin/products/{id}/variants/{variant_id}`
Any subset of the writable variant fields; `200 OK` with the variant. A new price or
stock bumps the variant's `version`; a new `sku` or `attributes` bumps the product's.

```http
PATCH /admin/products/1/variants/1
Authorization: Bearer <access token>
Content-Type: application/json

{"price_minor": 19999}
```

```json
{"id": 1, "product_id": 1, "sku": "CLO-001-NEGRU-M",
 "attributes": {"size": "M", "color": "negru"},
 "price_minor": 19999, "stock": 17, "version": 2}
```

```json
{"error": {"code": "validation_error", "message": "Invalid input.",
           "fields": [{"field": "price_minor", "message": "Input should be less than or equal to 2147483647"}]}}
```

### `DELETE /admin/products/{id}/variants/{variant_id}`
`204 No Content`; the product's `version` goes up by one.

```json
{"error": {"code": "not_found", "message": "Variant not found."}}
```

## Health

### `GET /health`
`200 OK` `{"status": "ok"}`.
