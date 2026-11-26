# Tests — GH-6

> Written by the test author before any code. Every new test failed first, for the right reason.

## Summary
- Added: 48 test functions (171 cases with parametrization) · 0 unit, 48 integration — all in `backend/tests/test_admin_products.py`
- Approach: HTTP tests with PATTERN-015 (httpx `AsyncClient` + `ASGITransport`, the rolled-back `session`, `make_user(role="admin")` + `auth_header`). A `catalog` fixture inserts store A (the first, lowest-id store), two categories, then store B with its own category. Rows are inserted with SQLAlchemy Core through `session` and committed (savepoint release, as `make_user` does), so the app's rollback on a 409 never removes them. Versions are checked through the API and through plain SQL. The seeded-admin test loads the real seed into `session` the way test 25 of `test_seed_load.py` does, with passwords generated at run time (`strong_password()` imported from that module).
- Red state (2026-11-26, before any product code): 171 failed. 166 fail on the status assertion with `{"error":{"code":"not_found","message":"Not Found"}}` (Starlette's 404: no route matches); 11 `test_unknown_id_is_404` / `test_variant_of_another_product_is_404` cases get the 404 but fail on `'Not Found' == 'Product not found.' / 'Variant not found.'` (A8 messages); the OpenAPI test fails on an empty route set. No import errors, no fixture errors. The existing suite stays green: 370 passed.
- Existing tests changed: 0 · removed: 0

## Acceptance point → tests
| # | Ticket | Acceptance point | File | Test(s) | Red reason before code |
|---|---|---|---|---|---|
| 1 | GH-6 | The 9 routes on `/admin`; a variant under another product → 404 | `backend/tests/test_admin_products.py` | `test_openapi_lists_every_admin_product_route`; `test_variant_of_another_product_is_404` [PATCH, DELETE] (with a positive control on the right product) | OpenAPI has no `/admin/products*` path; 404 "Not Found" instead of "Variant not found." |
| 2 | GH-6 | 401 without a token, 403 for a customer, 403 before body validation | `backend/tests/test_admin_access.py` (unchanged matrix, enumerates `app.routes`); `backend/tests/test_admin_products.py` | matrix: `test_customer_gets_403_on_every_admin_route`, `test_no_token_gets_401_on_every_admin_route`, `test_every_admin_route_depends_on_require_admin` (gain 9 routes on their own); new `test_customer_with_an_invalid_body_gets_403` [POST product, PATCH variant] | 404 (no route) instead of 403 |
| 3 | GH-6 | Writable fields only; `store_id` set by the server; unknown field → 422 | `backend/tests/test_admin_products.py` | `test_create_product_sets_the_store`; `test_read_only_product_field_is_rejected` [POST, PATCH × `store_id`, `rating_avg`, `rating_count`, `version`, `content_hash`, `id`]; `test_read_only_variant_field_is_rejected` [POST, PATCH × `version`, `product_id`, `id`] → 422 `field: "body"` | 404 instead of 201 / 422 |
| 4 | GH-6 | `products.version` +1 on product change, variant create/delete/`sku`/`attributes`; not on price/stock | `backend/tests/test_admin_products.py` | `test_product_patch_bumps_product_version` [5 fields]; `test_variant_create_bumps_product_version`; `test_variant_delete_bumps_product_version`; `test_variant_sku_change_bumps_product_not_variant`; `test_variant_attributes_change_bumps_product_not_variant`; `test_price_or_stock_change_leaves_product_version` [price, stock, both] | 404 instead of 200/201/204 |
| 5 | GH-6 | `product_variants.version` +1 only on price or stock | `backend/tests/test_admin_products.py` | `test_price_change_bumps_variant_version`; `test_stock_change_bumps_variant_version`; plus the sku/attributes tests in 4 (variant version stays 1) | 404 instead of 200 |
| 6 | GH-6 | Only on real change; empty PATCH accepted; atomic SQL increment; `version` in every response | `backend/tests/test_admin_products.py` | `test_empty_patch_changes_nothing` (product and variant: same body, same version, same `updated_at`); `test_same_values_change_nothing` (same text, same category, attributes in another key order, same price/sku/attributes); `test_one_becoming_true_is_a_change` (`{"k": 1}` → `{"k": true}`); `test_version_is_incremented_in_sql` (versions raised to 7 and 4 with SQL between requests → 8 and 5); `assert_product_out` / `assert_variant_out` check `version` in every success body | 404 instead of 200 |
| 7 | GH-6 | `attributes` replaced whole; product key/value shapes; variant text only | `backend/tests/test_admin_products.py` | `test_attributes_are_replaced_not_merged`; `test_every_seed_attribute_value_shape_is_accepted` (str, int, bool, list[str], empty list); `test_bad_product_attributes_are_422` [POST, PATCH × bad key, float, nested object, list of ints, null value] → `field: "attributes"`, key not echoed; `test_bad_variant_attributes_are_422` [POST, PATCH × int, bool, list, empty string, blank string, bad key] | 404 instead of 200 / 422 |
| 8 | GH-6 | `price_minor`, `stock`: integers 0…2147483647, else 422 | `backend/tests/test_admin_products.py` | `test_bad_price_or_stock_is_422` [POST, PATCH × price_minor, stock × -1, 2147483648, 1.5, 100.0, `"100"`, `true`, `null`]; `test_price_and_stock_bounds_are_accepted` [0, 2147483647] | 404 instead of 422 / 201 |
| 9 | GH-6 | SKU format; existing SKU → 409 `sku_taken` | `backend/tests/test_admin_products.py` | `test_badly_formed_sku_is_422` [POST, PATCH × lowercase, underscore, double dash, leading dash, space, empty]; `test_duplicate_sku_on_create_is_409`; `test_patch_to_another_variants_sku_is_409`; `test_patch_to_its_own_sku_is_a_no_op` | 404 instead of 422 / 409 / 200 |
| 10 | GH-6 | Unknown or foreign `category_id` → 422 on `category_id`; unknown path ID → 404 `not_found` | `backend/tests/test_admin_products.py` | `test_unknown_or_foreign_category_is_422` [POST, PATCH × missing, other store]; `test_unknown_id_is_404` [7 routes with an unknown product, 2 with an unknown variant; message "Product not found." / "Variant not found."]; `test_malformed_path_id_is_422` [0, -1, 2^63, `abc`] (A4) | 404 instead of 422; 404 with message "Not Found" instead of the A8 message |
| 11 | GH-6 | Text non-empty after trim; no max | `backend/tests/test_admin_products.py` | `test_blank_text_is_422` [POST, PATCH × `""`, `"   "` × brand, name, description] (variant attribute blank value: point 7); `test_null_on_product_patch_is_422` [5 fields]; `test_text_is_stored_trimmed` (A6); `test_long_description_is_accepted` (~20 400 chars) | 404 instead of 422 / 201 |
| 12 | GH-6 | List: `limit` 1–100 default 50, `offset`, by `id`, `{items,total}`, no variants | `backend/tests/test_admin_products.py` | `test_list_pages_by_id` (3 products, `limit=2&offset=1`, item keys exact: no `variants`, no `content_hash`); `test_list_default_limit_is_50` (51 products, bulk insert; `limit=100` returns 51); `test_bad_paging_is_422` [`limit=0`, `101`, `abc`, `offset=-1`, `offset=2^63`] → `field: "query.<name>"` | 404 instead of 200 / 422 |
| 13 | GH-6 | Detail with variants; `rating_avg` string or null; no `content_hash` | `backend/tests/test_admin_products.py` | `test_detail_includes_variants_in_id_order` (exact keys; variant body exact; `GET …/variants` equals `variants`, a plain array, A2); `test_rating_avg_is_a_string_or_null` (`4.3` via SQL → `"4.30"`, new → `null`, on detail and list) | 404 instead of 200 |
| 14 | GH-6 | POST product creates it without variants | `backend/tests/test_admin_products.py` | `test_create_product_returns_201_without_variants` (`variants == []`, `version == 1`, `rating_count == 0`, `rating_avg is None`, GET equals the POST body); `test_create_product_needs_every_field` [5]; `test_create_variant_needs_every_field` [4] (A3); `test_empty_attributes_are_valid` (A3) | 404 instead of 201 / 422 |
| 15 | GH-6 | Hard delete; cascade to variants, images, reviews; last variant deletable | `backend/tests/test_admin_products.py` | `test_delete_product_cascades` (rows of a second product stay; GET → 404 "Product not found."); `test_last_variant_can_be_deleted` (and product version +1) | 404 instead of 204 |
| 16 | GH-6 | One envelope; input never echoed | `backend/tests/test_admin_products.py` | `assert_error` (conftest) on every error assertion; `test_errors_never_echo_input` (bad SKU, bad attribute key, unknown field name: none in `response.text`); echo checks inside the attribute, category and unknown-ID tests | 404 instead of 422 |
| 17 | GH-6 | The seeded admin edits a seeded product; visible on GET | `backend/tests/test_admin_products.py` | `test_seeded_admin_edits_a_seeded_product` (seed into `session`, login via `POST /auth/login`, PATCH the lowest-id product's `name` and its first variant's `price_minor`, GET shows both and both versions +1) | 404 on the first GET |
| 18 | GH-6 | OpenAPI shows the routes; `docs/API.md` Admin section and codes | `backend/tests/test_admin_products.py` | `test_openapi_lists_every_admin_product_route` | empty route set |

## Not automated
| Acceptance point | Why | Covered by |
|---|---|---|
| 6 — atomicity under real concurrency (`FOR UPDATE`, `version = version + 1`) | The rolled-back shared session cannot run two transactions at once; `test_version_is_incremented_in_sql` proves the increment is relative to the row, not to what the app read | reviewer: the SQL expression and the row lock |
| 9 — SKU race safety | Same reason | reviewer: no pre-check SELECT; the unique constraint decides |
| 18 — `docs/API.md` Admin section, codes, "routes arrive with GH-6" line | Documentation | reviewer, then the user at gate C |

## Changes after a logic change
| Date | Test | What changed | Why (trigger) |
|---|---|---|---|

## Reproductions for in-delivery fixes
| Date | Defect | Test | Red reason before the fix |
|---|---|---|---|

## Mechanical fixes by the builder
| Date | Test | Fix | Checked by reviewer |
|---|---|---|---|
