# Architecture — Shopy

<!-- graffino-agentic:begin v1 -->
> How this repo is built, generated from the code at backfill and kept current by
> whoever changes the structure. The code wins: when this page is wrong, fix it.
<!-- graffino-agentic:end -->

> **Status 2026-11-18:** P0 skeleton exists (GH-1): Compose services, `GET /health`,
> an idle worker, an empty web shell, CI. Everything else on this page is still the
> target from `shopy_brief.md` §5–§6, §11, §12. Update it as each phase lands.

## Overview
A React PWA (customer `/app`, admin `/admin`) talks to one FastAPI service over REST
and one WebSocket per assistant session. The API runs the agent (Claude Haiku with
tools), hybrid search, the order state machine, payments and cost control. A separate
worker keeps the search index current from an outbox table. One Postgres database
holds everything. Locally all runs in Docker Compose; production is Railway or Fly.io
(Q-011) with Neon, R2 and Resend.

```text
 iPhone Safari PWA / desktop browser
  ├─ VAD + MediaRecorder ──audio──┐
  ├─ text input ──────────────────┤  WebSocket /ws/assistant (C-002)
  ├─ Web Audio player ◄───────────┤
  ├─ WebAuthn (Face ID) ──REST────┤  REST + OpenAPI (C-001)
  ├─ Stripe Payment Element ──────┼──────────────► Stripe (test)
  └─ Admin area ──REST────────────┤                  │ webhook (C-004)
                                  ▼                  ▼
                          FastAPI api ◄──────────────┘
   ├─ voice: STT ─► OpenAI      TTS ─► Azure Speech
   ├─ agent orchestrator ─► Claude Haiku (tools, C-003) ─► Langfuse traces
   │     └─ output guard · cost ledger + caps
   ├─ hybrid search ─► OpenAI embeddings
   ├─ order state machine ─► Stripe · Resend/Mailpit
   └─ images ─► MinIO / R2
                                  │
                       Postgres 16 + pgvector + unaccent
                                  │ reindex_outbox (SKIP LOCKED)
                       worker ─► OpenAI embeddings ─► kb_chunks
```

## Parts
| Part | Path | Responsibility | Talks to |
|---|---|---|---|
| web | `web/` | PWA: assistant screen, cart, confirmation sheet, settings, admin | api (REST, WS), Stripe.js |
| api | `backend/app/` | REST, WebSocket, Stripe webhook, agent, search, orders | db, all external services |
| agent | `backend/app/agent/` | orchestrator, tools, prompts, output guard, confirmation classifier | LLM, search, orders, usage |
| orders | `backend/app/orders/` | state machine, proposals, pricing | db, payments, mail |
| search | `backend/app/search/` | hybrid search with RRF | db, embeddings |
| indexing | `backend/app/indexing/` | chunking, embedding client | embeddings |
| voice | `backend/app/voice/` | STT, TTS, sentence splitter, number normalizer | OpenAI, Azure |
| payments | `backend/app/payments/` | Stripe service | Stripe |
| auth | `backend/app/auth/` | passwords, JWT, roles, WebAuthn | db |
| usage | `backend/app/usage/` | cost ledger, caps | db |
| worker | `backend/worker/` | polls the outbox, rebuilds chunks | db, embeddings |
| seed | `backend/seed/` | `catalog.json` (written once, D-023), `validate_catalog.py`, `seed.py` | db |
| evals | `evals/` | real-LLM scenarios, manual | api / agent |

## Data flow
**Voice turn** (brief §9.1)
1. VAD detects end of speech → `audio.utterance` over the WebSocket.
2. STT (`language=ro`) → `transcript.final`.
3. Orchestrator runs the LLM with tools (max 6 calls) → structured reply.
4. Output guard checks products and numbers (PATTERN-004); one retry, then a safe reply.
5. Sentences are normalized and sent to TTS → `agent.audio.chunk` + `agent.text.delta`.

**Order** (brief §12)
1. Cart → `create_order_proposal` → snapshot, totals, `proposal_hash`, summary spoken verbatim.
2. Utterance → deterministic classifier → CLEAR_YES / CLEAR_NO / AMBIGUOUS (2 strikes → screen fallback).
3. WebAuthn challenge bound to the proposal hash → Face ID → server verifies.
4. One transaction: lock variants, revalidate price and stock, decrement stock, order PLACING.
5. PaymentIntent (idempotency key = proposal ID) → webhook → PLACED + email, or PAYMENT_FAILED + stock restored.

**Reindex** (brief §11)
1. Catalog change + outbox row in one transaction.
2. Worker claims the row (`FOR UPDATE SKIP LOCKED`), rebuilds that source's chunks, skips unchanged hashes, swaps chunks atomically, marks done.

## State and storage
| What | Where | Owner | Notes |
|---|---|---|---|
| Catalog, users, carts, proposals, orders, confirmations | Postgres | api | money in minor units (PATTERN-001); Alembic only |
| Chunks and embeddings | Postgres `kb_chunks` | worker | vector(1536), HNSW; no prices or stock |
| Reindex jobs | Postgres `reindex_outbox` | api writes, worker consumes | |
| Usage and cost | Postgres `usage_ledger` | api, worker | |
| Product images | MinIO (local) / R2 (prod) | api | by `storage_key` |
| Transcripts | Postgres `messages` | api | 90 days, no audio (D-020) |
| Card data | Stripe only | Stripe | we store ID, brand, last4, expiry (D-016) |
| LLM traces | Langfuse Cloud | api | not in Compose |

## Configuration
| Name | Where set | Used by | Notes |
|---|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `.env` | Compose `db` | local only, not in brief §18 |
| `DATABASE_URL`, `JWT_SECRET`, `APP_ORIGIN` | `.env` | api, worker | |
| `ANTHROPIC_API_KEY`, `LLM_MODEL` | `.env` | agent | |
| `OPENAI_API_KEY`, `STT_MODEL`, `EMBEDDING_MODEL` | `.env` | voice, search, worker | |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `TTS_VOICE` | `.env` | voice | |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` | `.env` | payments, web | test mode only |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET` | `.env` | api; Compose `minio`, `minio-init` | access/secret key double as the local MinIO root user/password |
| `MAIL_PROVIDER`, `RESEND_API_KEY`, `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT` | `.env` | orders | |
| `WEBAUTHN_RP_ID`, `WEBAUTHN_RP_NAME`, `WEBAUTHN_ORIGIN` | `.env` | auth | tunnel host in dev |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | `.env` | agent | |
| `DAILY_COST_CAP_EUR`, `USER_DAILY_MESSAGE_CAP`, `PRICE_*` | `.env` | usage | Q-013 |
| `SEED_ADMIN_PASSWORD`, `SEED_CUSTOMER_PASSWORD` | `.env` | seed | |

## Build, deploy, runtime
Local: `docker compose up` (db, api, worker, web, minio + one-shot `minio-init` bucket
creation, mailpit; `docker-compose.yml`), then `make seed` (P1); an HTTPS tunnel (e.g.
`cloudflared`) for the iPhone. Local S3 is the archived `bitnamilegacy/minio` image,
pinned (no web console); production uses R2. CI: GitHub Actions — `ci.yml` on every
push (backend ruff/mypy/pytest, web oxlint/typecheck/vitest, ledger lint, gitleaks)
and `team-checks.yml`. Production: api, worker and static web on
Railway or Fly.io; Neon, R2, Resend, Langfuse. Commands: AGENTS.md section 2; release:
section 5.

## Boundaries
- **LLM ↔ data:** the model only calls tools with IDs and quantities (PATTERN-002); every reply passes the output guard (D-010); tool results are quoted data (PATTERN-003).
- **Order placement:** only the confirmation endpoint after a clear yes and a WebAuthn assertion bound to the proposal hash (D-011, D-012, D-013).
- **Roles:** FastAPI dependencies on every route (PATTERN-007).
- **Card data:** never reaches the server (D-016).
- **Budget:** every paid call through the cost ledger (D-019, PATTERN-011).
- **Browser:** untrusted text as plain text, strict CSP (PATTERN-009).
