# Contracts — Shopy

<!-- graffino-agentic:begin v1 -->
> Promises across a boundary. **Provided:** this repo owns the contract; the text
> lives here only. **Consumed:** a link to the provider's entry plus the fields this
> repo relies on. **External:** what we rely on from a third-party service.
> Changing a provided contract is a PROPOSAL (AGENTS.md → The gate) and the plan
> lists the consumers' files too. Status: `approved` · `proposed` · `superseded-by`.
<!-- graffino-agentic:end -->

Seeded from `shopy_brief.md` §21 before any code existed. Each `Evidence` moves to
the producer's `path:line` once it is written.

## Index
- C-001 · REST API · provided
- C-002 · WebSocket assistant protocol · provided
- C-003 · Agent tool schemas · provided
- C-004 · Stripe webhook handling · provided
- C-005 · Proposal hash canonicalization · provided

---

## Provided

### C-001 · REST API
- **Status:** approved
- **Interface:** HTTP REST, OpenAPI at `/docs` and `/openapi.json`; examples in `docs/API.md`.
- **Consumers:** the web client (`/app` and `/admin`).
- **Shape:** routes listed in brief §14 (auth, me, payment methods, webauthn, proposals, orders, products, webhooks, health, admin). Errors: every error response (422, other 4xx, 429) uses one envelope, `{"error": {"code": "<machine code>", "message": "<English text>", "fields": [{"field": "<name>", "message": "<text>"}]}}`, with `fields` only when relevant; the submitted input is never sent back. 422 for invalid input, 403 for a customer on `/admin`.
- **Rules:** JWT access token (15 min) in the Authorization header; rotating refresh token in an httpOnly Secure cookie. CORS restricted to `APP_ORIGIN`. Auth routes are rate limited.
- **Evidence:** `backend/app/main.py:6` (`GET /health`); other routes: `shopy_brief.md` §14, §16 (not built yet)
- **Source:** user (project brief) · confidence high
- **Confirmed:** 2026-11-19

### C-002 · WebSocket assistant protocol
- **Status:** approved
- **Interface:** WebSocket `/ws/assistant`, versioned by the `v` field.
- **Consumers:** the web client assistant screen.
- **Shape:** JSON messages with `type`, `v` and `turn_id` where applicable; audio as binary frames preceded by a JSON header. Client → server: `session.start`, `audio.utterance`, `text.utterance`, `turn.cancel`, `ui.screen_completed`. Server → client: `transcript.final`, `agent.text.delta`, `agent.audio.chunk`, `agent.turn.done`, `ui.show_products`, `ui.show_images`, `ui.cart_updated`, `ui.open_screen`, `proposal.created`, `proposal.ambiguous`, `proposal.screen_fallback`, `proposal.invalidated`, `proposal.expired`, `confirmation.required`, `order.placed`, `order.payment_failed`, `order.cancelled`, `limit.reached`, `error`. Payload schemas: to be written in `docs/API.md` (P3).
- **Rules:** authenticated with the access token at connect. A breaking change bumps `v`.
- **Evidence:** `shopy_brief.md` §9.1, §14 (no code yet)
- **Source:** user (project brief) · confidence high

### C-003 · Agent tool schemas
- **Status:** approved
- **Interface:** LLM tool definitions; source of truth `backend/app/agent/tools.py`.
- **Consumers:** the LLM (Claude Haiku) through the orchestrator; evals in `evals/`.
- **Shape:** the tools in brief §10.2: `search_products`, `get_product`, `get_reviews`, `search_product_info`, `get_policy`, `show_images`, `add_to_cart`, `update_cart_item`, `remove_from_cart`, `view_cart`, `get_checkout_profile`, `create_order_proposal`, `submit_confirmation_utterance`, `get_order_status`, `create_cancellation_proposal`, `open_screen`. Final message: `{speech, product_refs, ui}` (brief §10.3).
- **Rules:** parameters are IDs and quantities only (PATTERN-002); no tool places or cancels an order; max 6 tool calls per turn.
- **Evidence:** `shopy_brief.md` §10.1–§10.3 (no code yet)
- **Source:** user (project brief) · confidence high

### C-004 · Stripe webhook handling
- **Status:** approved
- **Interface:** `POST /webhooks/stripe`.
- **Consumers:** Stripe (test mode) as the caller.
- **Shape:** accepted events: `payment_intent.succeeded` → order PLACED and confirmation email; `payment_intent.payment_failed` → PAYMENT_FAILED and stock restored. Other events are acknowledged and ignored.
- **Rules:** signature verified with `STRIPE_WEBHOOK_SECRET`; unsigned or invalid events are rejected (test 23). PaymentIntents use `idempotency_key = proposal_id`; a repeated event or confirmation never creates a second order (test 14).
- **Evidence:** `shopy_brief.md` §12.7, §13 (no code yet)
- **Source:** user (project brief) · confidence high

### C-005 · Proposal hash canonicalization
- **Status:** approved
- **Interface:** `proposal_hash` = SHA-256 of a canonical JSON of the proposal snapshot; the WebAuthn challenge = SHA-256(`proposal_hash` || random nonce).
- **Consumers:** the WebAuthn confirmation (D-013); the `order_confirmations` audit record.
- **Shape:** fields: items (variant ID, quantity, unit price), subtotal, shipping, total, payment method ID, address snapshot, expiry. Exact serialization (key order, separators, number and time encoding) is open: Q-010.
- **Rules:** the server recomputes the hash from the DB at verification; any field change gives a new hash.
- **Evidence:** `shopy_brief.md` §12.2, §12.5 (no code yet)
- **Source:** user (project brief) · confidence medium

## Consumed

_None: no other repo._

## External

### Anthropic · Messages API with tool use
- **Interface:** Messages API, streaming, tool use; model from `LLM_MODEL` (`claude-haiku-5-5`).
- **We rely on:** tool calls, streamed text, token usage for the cost ledger.
- **Known quirks:** output can invent numbers or products; the output guard handles it (D-010).
- **Evidence:** `shopy_brief.md` §5, §10 (no code yet)

### OpenAI · transcription and embeddings
- **Interface:** transcription API with `language=ro` (model from `STT_MODEL`, Q-004); embeddings `text-embedding-3-small` (1536 dimensions, `EMBEDDING_MODEL`).
- **We rely on:** Romanian transcripts; a fixed vector size matching `kb_chunks.embedding vector(1536)`.
- **Known quirks:** Safari records `audio/mp4`.
- **Evidence:** `shopy_brief.md` §5, §7, §9.1 (no code yet)

### Azure AI Speech · Romanian neural TTS
- **Interface:** TTS with a Romanian neural voice (`TTS_VOICE`, Q-003), key and region from env.
- **We rely on:** sentence-by-sentence synthesis streamed to the client.
- **Evidence:** `shopy_brief.md` §5, §9.1 (no code yet)

### Stripe · test mode
- **Interface:** Customer, SetupIntent with Payment Element, PaymentIntent on-session, refunds, webhooks; `stripe` (Python), `@stripe/react-stripe-js`.
- **We rely on:** tokenized payment methods (brand, last4, expiry); 3DS through `handleNextAction`; signed webhooks (C-004).
- **Evidence:** `shopy_brief.md` §12.7, §13 (no code yet)

### WebAuthn platform authenticator · iOS Safari
- **Interface:** `navigator.credentials.create/get` with `userVerification: "required"`; `webauthn` (py_webauthn) on the server, `@simplewebauthn/browser` on the client.
- **We rely on:** Face ID or passcode as user verification; RP ID and origin from env (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`).
- **Known quirks:** needs a secure context; dev on the phone needs an HTTPS tunnel.
- **Evidence:** `shopy_brief.md` §4, §12.5 (no code yet)

### Email, storage, tracing · Resend / Mailpit, R2 / MinIO, Langfuse
- **Interface:** Resend API (prod) or SMTP to Mailpit (local); S3 API to R2 (prod) or MinIO (local); Langfuse Cloud for LLM traces.
- **We rely on:** order emails; product image storage by `storage_key`; trace upload (not in Docker Compose).
- **Evidence:** `shopy_brief.md` §5, §18 (no code yet)
