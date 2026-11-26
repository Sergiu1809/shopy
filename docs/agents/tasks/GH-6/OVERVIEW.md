---
ticket: GH-6
type: task
parent:
covers: []
delivered_in:
title: "P1d: Admin product CRUD API"
status: not-started
lane: full
branch: feat/admin-products-GH-6
pr:
design_refs: []
summary: "Admin CRUD for products and their variants under /admin, with version bumps, validation and docs/API.md examples"
created: 2026-11-26 17:27
updated: 2026-11-26 17:27
---

# GH-6 — P1d: Admin product CRUD API

## Goal
An admin can manage the catalog through the API (brief §14; §19 P1 "admin can edit a
product"). Last P1 ticket; P2 indexing builds on these routes.
Ticket: https://github.com/Sergiu1809/shopy/issues/6

## Context brief 🧾
- **Acceptance criteria (approved, GH-6; ticket text + gate A answers 2026-11-26, user):**
  - [ ] Routes on the existing `/admin` router: `GET/POST /admin/products`, `GET/PATCH/DELETE /admin/products/{id}`, `GET/POST /admin/products/{id}/variants`, `PATCH/DELETE /admin/products/{id}/variants/{variant_id}`. A variant under another product → 404. (Q2)
  - [ ] Admin only: 401 without a token, 403 for a customer. The routes join the parametrized matrix in `tests/test_admin_access.py`, which sends no body (403 must come before body validation).
  - [ ] Writable product fields: `category_id`, `brand`, `name`, `description`, `attributes`. Writable variant fields: `sku`, `attributes`, `price_minor`, `stock`. `store_id` is set by the server (the single store), never from the body. `rating_avg`, `rating_count`, `version` and `content_hash` are not writable (an unknown field → 422). (Q12)
  - [ ] `products.version` +1 on every product change, and when one of its variants is created, deleted, or has its `sku` or `attributes` changed; not on a variant price or stock change. (Q3)
  - [ ] `product_variants.version` +1 only when `price_minor` or `stock` changes; not on `sku` or `attributes`. (Q4)
  - [ ] A version goes up only when a value actually changes; an empty PATCH body is accepted and changes nothing. Increments are atomic in SQL (`version = version + 1`). No optimistic concurrency (no If-Match): last write wins; `version` is returned in every response. (Q5, Q6)
  - [ ] `attributes` on PATCH is replaced whole, never merged. Product attributes: keys `^[a-z][a-z0-9_]*$`, values str, int, bool or list[str] (the seed's `AttributeValue`); variant attributes: text values only. No per-key type check (PATTERN-016 candidate, Q-016 deferred). (Q7)
  - [ ] Money in integer bani (PATTERN-001). `price_minor` and `stock`: integers ≥ 0 and ≤ 2147483647; outside → 422 (never a DB error or 500). (Q8)
  - [ ] SKU format as in `seed/schema.py` (`^[A-Z0-9]+(-[A-Z0-9]+)*$`); a SKU that exists → 409 `sku_taken`. (Q9)
  - [ ] Unknown `category_id` (or one of another store) → 422 with `fields: [{"field": "category_id", …}]`; unknown product or variant ID in the path → 404 `not_found`. (Q10)
  - [ ] Text fields: non-empty after trimming; no maximum length. (Q14)
  - [ ] `GET /admin/products`: `limit` 1–100 (default 50) and `offset`, ordered by `id`; response `{"items": [...], "total": n}`; list items without variants. No search or filters. (Q11)
  - [ ] `GET /admin/products/{id}` includes the product's variants. `rating_avg` is returned as a string (e.g. `"4.30"`) or null; `content_hash` is not exposed. (Q12)
  - [ ] `POST /admin/products` creates the product without variants; variants are added through the variants routes. (Q13)
  - [ ] DELETE is a hard delete, no migration: a product delete cascades to its variants, images and reviews (existing FKs); deleting the last variant of a product is allowed. (Q1; the P4 follow-up is Q-017)
  - [ ] Every error uses the one envelope (C-001, `app/errors.py`); the input is never echoed.
  - [ ] Test: the seeded admin edits a seeded product; the change is visible on GET.
  - [ ] OpenAPI at `/docs` shows the routes; an Admin section with examples in `docs/API.md` (new codes `sku_taken`, `not_found` for resources in its error table; the "routes arrive with GH-6" line updated).
- **Out of scope:** image endpoints (Q-001); the reindex outbox (P2; PATTERN-010 applies then); any admin UI (Q-008); review endpoints (not in brief §14); category CRUD; search or filters on the list; archive/soft delete and the behaviour once orders or carts reference a variant (Q-017, P4); the "admin edit invalidates open proposals" event (brief §12.6, P4).
- **Tickets covered:** GH-6 (Fixes)
- **Constraints that apply:**
  - PATTERN-001 — money as integers in bani (`price_minor`).
  - PATTERN-006 — Pydantic v2, `extra="forbid"`, ranges; 422 in the one envelope.
  - PATTERN-007 — admin dependency at router level; the 403 matrix covers every `/admin` route.
  - PATTERN-008 — SQLAlchemy with bound parameters only; no schema change expected.
  - PATTERN-010 — not yet (no outbox table); P2 adds an outbox row to product and descriptive-variant changes.
  - PATTERN-015 (candidate) — API tests with httpx AsyncClient + ASGITransport and the rolled-back session.
  - PATTERN-016 (candidate), Q-016 (deferred) — attribute types not enforced per key.
  - C-001 — error envelope, OpenAPI, examples in `docs/API.md`.
  - D-006, D-010, D-014 — price and stock never indexed, read live; the variant version feeds proposal invalidation.
  - D-021 — English API and docs; catalog values stay Romanian.
  - D-024 — bigint identity IDs in paths.
  - Q-001, Q-008, Q-017 — images, admin UI and archive behaviour out of scope.
- **Where the code is:**
  - Router: `backend/app/api/admin.py` (prefix `/admin`, `require_admin` at router level).
  - Models: `backend/app/models/catalog.py` (`Category`, `Product`, `ProductVariant`; CHECKs on price, stock, ratings; `sku` unique; CASCADE from products).
  - Errors: `backend/app/errors.py` (`ApiError`, envelope). Auth: `backend/app/auth/dependencies.py`.
  - Schemas: `backend/app/schemas/` (only `auth.py` today). Reusable shapes: `backend/seed/schema.py` (`Key`, `Sku`, `AttributeValue`, `Text`).
  - Tests: `backend/tests/conftest.py` (`client_factory`, `make_user`, `auth_header`), `backend/tests/test_admin_access.py`.
  - Docs: `docs/API.md`.
- **Ownership:** integration owner: conductor · one builder
- **Verify with:** `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`; `python3 docs/agents/tools/ledger-lint.py`

## Resume here ⏯
Gate A done (2026-11-26). Next: the conductor creates the branch and draft PR, then
`/plan` for gate B.

## Summary of work so far
- 2026-11-26 — Product owner coverage report; gate A answered (all recommendations accepted); Q-017 recorded.

## Approach
<Planner: PLAN.md and TESTS.md.>

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| modified | docs/agents/OPEN-QUESTIONS.md | Q-017 (archive or 409 once P4 references variants) |
| added | docs/agents/tasks/GH-6/OVERVIEW.md | this file |

## Manual verification 🔧
none yet: the planner decides (API only; automated tests cover the AC).

## Decisions log 🧭
- **2026-11-26 — Hard delete, no migration; the last variant may be deleted** — Why: matches the AC and the current schema; no table references a variant yet. Rejected: soft delete (migration plus unspecified read-path filtering); 409 on reference (moot until P4). Follow-up: Q-017. (gate A Q1)
- **2026-11-26 — Nested variant routes** — Why: follows brief §14 `.../variants`. Rejected: flat `/admin/variants/{id}`. (gate A Q2)
- **2026-11-26 — Product version bumps on variant create/delete/sku/attributes, not price/stock** — Why: the product chunk holds a variant summary but never price or stock (brief §11, D-006), so the P2 index status stays right. Rejected: bump on every variant change (stale status with no reindex queued); never bump. (gate A Q3)
- **2026-11-26 — Variant version only on price or stock** (Q4); **no optimistic concurrency, last write wins, atomic increment** (Q5); **bump only on real change, empty PATCH accepted** (Q6); **attributes replaced whole, seed value shapes** (Q7); **price and stock 0–2147483647, else 422** (Q8); **409 `sku_taken`, seed SKU format** (Q9); **unknown category 422, unknown path ID 404** (Q10); **limit/offset list, `{items,total}`** (Q11); **detail with variants, read-only ratings, server-set `store_id`** (Q12); **product created without variants** (Q13); **non-empty text, no max length** (Q14) — Why: the product owner's defaults, accepted by the user at gate A.

## Open questions / blockers
- [ ] Q-017 — archive or 409 once orders or carts reference a variant (P4; not blocking GH-6).

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/6
- PR: 
