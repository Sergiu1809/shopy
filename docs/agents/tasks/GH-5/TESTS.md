# Tests — GH-5

> Written by the test author before any code. Every new test failed first, for the right reason.

## Summary
- Added: 121 tests · 103 unit, 18 integration (17 DB through `main()` on a fresh migrated database, 1 API + DB)
- Approach: `backend/tests/test_seed_validate.py` builds a minimal valid catalog in code (190 small products, all four fixtures in `clothing`) and a minimal users file, so each bad case changes one thing. Every rejection asserts a `ValidationError` whose locations or messages (read with `include_input=False`) name the field or rule, so a test cannot pass on an unrelated error. A control test proves the base files are valid. `backend/tests/test_seed_load.py` calls the sync `seed.seed.main()` against `fresh_db_url` migrated with `command.upgrade`, loads the real `backend/seed/catalog.json` and `users.json`, and compares rows with the raw JSON. Passwords are generated at run time (`secrets`) and set with `monkeypatch.setenv`.
- Red state: both files fail at collection with `ModuleNotFoundError: No module named 'seed'`. After the code builder, the tests on the real files (1, 11, 15–25, and the real-users half of 10) stay red until `catalog.json` is assembled (they need 190–210 products and the four fixtures).
- Checked against a throwaway prototype kept outside the repo (scratchpad copy of `backend/`): all 121 pass, and switching to banker's rounding or a case-sensitive email lookup makes 13 and 23 fail.
- Existing tests changed: 0 · removed: 0

## Acceptance point → tests
`V` = `backend/tests/test_seed_validate.py`, `L` = `backend/tests/test_seed_load.py`. Every row was red before code: `ModuleNotFoundError: No module named 'seed'` at collection.

| # | Ticket | Acceptance point | File | Test(s) | Red reason before code |
|---|---|---|---|---|---|
| 1 | GH-5 | Real files pass; `main()` exits 0 and prints `OK` with the product count | V | `test_real_files_pass_the_validator`, `test_main_on_the_real_files_exits_0_and_prints_ok` (2) | no `seed` module; then no real files |
| 2 | GH-5 | 190–210 products | V | `test_product_count_bounds_are_accepted[190,210]`, `test_product_count_outside_190_to_210_is_rejected[189,211]` (4) | no `seed` module |
| 3 | GH-5 | ≥1 variant; 3–15 reviews | V | `test_a_product_without_variants_is_rejected`, `test_review_count_outside_3_to_15_is_rejected[2,16]`, `test_review_count_bounds_are_accepted[3,15]` (5) | no `seed` module |
| 4 | GH-5 | Unique SKUs; every problem reported | V | `test_a_duplicate_sku_across_two_products_is_rejected`, `test_every_problem_is_reported_not_only_the_first` (2) | no `seed` module |
| 5 | GH-5 | `price_minor` 0/-1/19.99/"1999"/true, stock -1, rating 0/6 rejected | V | `test_a_bad_price_minor_is_rejected[×5]`, `test_a_negative_stock_is_rejected`, `test_a_rating_outside_1_to_5_is_rejected[0,6]` (8) | no `seed` module |
| 6 | GH-5 | Category set exact; ASCII kebab slugs | V | `test_a_missing_category_is_rejected`, `test_an_extra_category_is_rejected`, `test_a_duplicate_category_is_rejected`, `test_a_slug_that_is_not_lowercase_ascii_kebab_is_rejected[casă,Home,home care,home_care]` (7, the last on `CategoryIn`) | no `seed` module |
| 7 | GH-5 | Fixtures once each; out_of_stock all 0; missing_attribute in clothing with no `material`; xss has `<script` and `onerror=` | V | `test_a_missing_product_fixture_is_rejected[×2]`, `test_a_missing_review_fixture_is_rejected[×2]`, `test_a_duplicated_out_of_stock_fixture_is_rejected`, `test_a_duplicated_missing_attribute_fixture_is_rejected`, `test_a_duplicated_review_fixture_is_rejected[×2]`, `test_out_of_stock_with_one_stocked_variant_is_rejected`, `test_missing_attribute_with_material_in_attributes_is_rejected`, `…_in_a_variant_is_rejected`, `…_in_the_description_is_rejected[×2]`, `test_missing_attribute_outside_clothing_is_rejected`, `test_xss_without_both_markups_is_rejected[×3]` (17) | no `seed` module |
| 8 | GH-5 | Policy kinds once each; unknown fields rejected; review date aware UTC | V | `test_a_missing_policy_kind_is_rejected`, `test_a_duplicated_policy_kind_is_rejected`, `test_an_unknown_policy_kind_is_rejected`, `test_an_unknown_field_is_rejected[file,store,policy,category,product,variant,review]`, `test_a_naive_or_non_utc_review_date_is_rejected[×2]` (12) | no `seed` module |
| 9 | GH-5 | Store is Shopy / RON | V | `test_a_store_other_than_shopy_ron_is_rejected[name,currency]` (2) | no `seed` module |
| 10 | GH-5 | Users file rules; real file: 1 admin, 2 customers, 2 addresses each with one default, one customer with preferences | V | `test_a_bad_user_email_is_rejected[.test,.local,not-an-email]`, `test_an_unknown_role_is_rejected`, `test_addresses_need_exactly_one_default[two,none]`, `test_a_duplicate_email_is_rejected[same,other case]`, `test_a_postal_code_that_is_not_six_digits_is_rejected`, `test_the_real_users_file_has_one_admin_and_two_customers` (10) | no `seed` module; then no `users.json` |
| 11 | GH-5 | Real catalog: every rating 1–5; shipping `19,99`, `200`, `2–4 zile lucrătoare`; returns `14`; warranty 2 years; payment by card | V | `test_the_real_catalog_uses_every_rating`, `test_the_real_catalog_store_and_policies` (2) | no `seed` module; then no `catalog.json` |
| 12 | GH-5 | `validate_files` gives located messages without the input; `main()` exits 1 | V | `test_validate_files_accepts_the_minimal_files`, `test_validate_files_names_the_location_without_echoing_the_input`, `test_validate_files_reports_a_broken_users_file`, `test_main_exits_1_and_prints_the_errors` (4) | no `seed` module |
| — | GH-5 | Control: the in-code base catalog and users file are valid | V | `test_the_minimal_catalog_and_users_are_valid` (1) | no `seed` module |
| 13 | GH-5 | `rating_summary` 2 decimals, half-up | L | `test_rating_summary_rounds_to_two_decimals`, `test_rating_summary_rounds_half_up_not_to_even` (2) | no `seed` module |
| 14 | GH-5 | Password refusal for both variables (unset, change-me, 7, no digit, no uppercase, 129); names the variable and rule, never the value; `main()` returns 1 with `DATABASE_URL` unset | L | `test_seed_passwords_refuses_a_bad_variable[×12]`, `test_seed_passwords_returns_the_password_per_role`, `test_main_refuses_a_bad_password_before_connecting[×12]` (25) | no `seed` module |
| 15 | GH-5 | First run: row counts equal the files; stdout reports them | L · DB | `test_first_run_loads_the_files` (1) | no `seed` module; then no real files |
| 16 | GH-5 | Fixed IDs in file order (store, categories, policies, products, variants, reviews with `created_at`) | L · DB | `test_store_categories_and_policies_follow_the_file`, `test_product_ids_follow_the_file_order`, `test_variant_ids_follow_the_file_order`, `test_review_ids_follow_the_file_order` (4) | same |
| 17 | GH-5 | `rating_avg` / `rating_count` from the file ratings | L · DB | `test_rating_avg_and_count_are_computed_from_the_file` (1) | same |
| 18 | GH-5 | Fixture texts verbatim; out-of-stock product all 0 | L · DB | `test_review_bodies_are_stored_verbatim`, `test_fixture_reviews_are_byte_for_byte_the_file[xss,prompt_injection]`, `test_the_out_of_stock_product_has_no_stock` (4) | same |
| 19 | GH-5 | Users: lowercase emails, roles, no Stripe id, Argon2 hash verifies; addresses and preferences as in the file | L · DB | `test_users_are_stored_with_hashed_passwords`, `test_addresses_and_preferences_follow_the_file` (2) | same |
| 20 | GH-5 | Rerun prints `already seeded`, counts and `max(id)` unchanged, exit 0 | L · DB | `test_a_rerun_changes_nothing` (1) | same |
| 21 | GH-5 | Admin edit survives a rerun | L · DB | `test_an_admin_edit_survives_a_rerun` (1) | same |
| 22 | GH-5 | Deleted `customer2` reinserted with addresses; other IDs unchanged; catalog skipped | L · DB | `test_a_deleted_user_is_inserted_again` (1) | same |
| 23 | GH-5 | Existing `Admin@Example.com` skipped, customers inserted | L · DB | `test_an_existing_email_matches_case_insensitively` (1) | same |
| 24 | GH-5 | One transaction: failure on the second user leaves every table empty | L · DB | `test_a_failure_on_the_second_user_rolls_everything_back` (1) | same |
| 25 | GH-5 | Seeded accounts log in; `/me` shows the role (PATTERN-015) | L · API + DB | `test_seeded_accounts_log_in` (1) | same |

## Not automated
| Acceptance point | Why | Covered by |
|---|---|---|
| 26 — `make seed` twice in Docker Compose | needs Compose with a real `.env` | conductor runs it, or names it as skipped in the PR's Testing done |
| 7 — `prompt_injection` review text actually tries to break the rules / ask for a discount | not mechanically checkable | reviewer |
| 10 — names, addresses and phones are fictitious | content | reviewer |
| 11 — Romanian quality, real brands, realistic RON prices, review realism | content | reviewer (sampled per category) |
| 18 — fixtures render harmlessly | later phases (P3/P6, PATTERN-009) | not in GH-5 |
| CI step runs `python -m seed.validate_catalog` | CI config | reviewer (and the CI run) |

## Changes after a logic change
| Date | Test | What changed | Why (trigger) |
|---|---|---|---|

## Reproductions for in-delivery fixes
| Date | Defect | Test | Red reason before the fix |
|---|---|---|---|

## Mechanical fixes by the builder
| Date | Test | Fix | Checked by reviewer |
|---|---|---|---|
