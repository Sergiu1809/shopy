# Decisions — search and indexing

## D-005 · Hybrid search with SQL filters
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Search merges Romanian full-text (custom `romanian` + `unaccent` config) and pgvector cosine with Reciprocal Rank Fusion (k = 60), then applies SQL filters, then groups by product.
- **Why:** Pure vector search fails on exact brand, size and volume matches.
- **Rejected:** Pure vector search.
- **Evidence:** shopy_brief.md §11, §20
- **Source:** user (project brief §20) · confidence high

## D-006 · Incremental reindexing through a transactional outbox
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Any indexed change inserts a `reindex_outbox` row in the same transaction. A separate worker polls with `SELECT ... FOR UPDATE SKIP LOCKED`, rebuilds only that source and skips embedding calls when `content_hash` is unchanged. Price and stock are never indexed and never trigger reindexing.
- **Why:** A modified product must be reindexed alone; price and stock are always read live from the DB.
- **Rejected:** Full reindex on every change; a broker.
- **Evidence:** shopy_brief.md §2, §11, §20
- **Source:** user (project brief §20) · confidence high

## D-022 · Seed catalog generated once, committed, loaded deterministically
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** `generate_catalog.py` calls the LLM once, offline, to write `backend/seed/catalog.json`, which is committed and reviewed. `seed.py` loads it without any LLM call. Real brands; no brand-owned product photos.
- **Why:** Reproducible seeds and test fixtures; no cost or nondeterminism at seed time; no use of brand-owned images.
- **Rejected:** Generating the catalog at seed time.
- **Evidence:** shopy_brief.md §8, §20
- **Source:** user (project brief §20) · confidence high
