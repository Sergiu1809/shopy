# Decisions — Shopy

<!-- graffino-agentic:begin v1 -->
> Constraints the code must obey. Status: `approved` (obey) · `proposed` (do not
> build on it) · `superseded-by <ID>` (kept to explain old code).
> Adding or changing an entry needs the user's OK (AGENTS.md → The gate).
<!-- graffino-agentic:end -->

Entries live in topic files under `decisions/`; this file is the index.

## Index
### [Agent and voice](decisions/agent-and-voice.md)
- D-008 · Voice pipeline is a cascade (STT, LLM, TTS)
- D-010 · Prices, stock and totals come only from the DB
- D-018 · No memory across sessions
- D-019 · Cost control with a usage ledger and caps
- D-020 · Transcripts only, 90-day retention

### [Orders and confirmation](decisions/orders-and-confirmation.md)
- D-011 · Order confirmation is a server-side state machine
- D-012 · On-screen confirmation threshold is 0 RON
- D-013 · WebAuthn challenge is bound to the proposal hash
- D-014 · Any price or stock change invalidates a proposal
- D-015 · Two ambiguous answers move confirmation to the screen
- D-017 · Voice cancellation only before shipping

### [Payments](decisions/payments.md)
- D-016 · Cards via Stripe SetupIntent; never by voice

### [Platform and stack](decisions/platform-and-stack.md)
- D-001 · Client is a PWA, not a native iOS app
- D-002 · Activation via in-app button and Action Button Shortcut
- D-003 · Backend is Python + FastAPI
- D-004 · Single Postgres database with pgvector
- D-007 · LLM is Claude Haiku 5.5 with tool use and streaming
- D-009 · Speech and embedding providers
- D-021 · Language split: Romanian voice, English everything else

### [Search and indexing](decisions/search-and-indexing.md)
- D-005 · Hybrid search with SQL filters
- D-006 · Incremental reindexing through a transactional outbox
- D-022 · Seed catalog generated once, committed, loaded deterministically

---
