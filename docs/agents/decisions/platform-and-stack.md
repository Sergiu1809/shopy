# Decisions — platform and stack

## D-001 · Client is a PWA, not a native iOS app
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Build the client as a React PWA (Safari, Add to Home Screen) that also works in desktop browsers; no native iOS code.
- **Why:** No Mac is available. A PWA allows Windows development, a live HTTPS demo and keyboard accessibility; Face ID works through WebAuthn. Trade-off: activation may need one tap and mic prompts may repeat.
- **Rejected:** Native iOS app (needs a Mac).
- **Evidence:** shopy_brief.md §2, §4, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-002 · Activation via in-app button and Action Button Shortcut
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** The assistant starts from the in-app mic button or from an iOS Shortcut opening `/app?listen=1` on the Action Button. With `?listen=1` the app opens on the assistant screen with one large "Tap to talk" button until audio is unlocked.
- **Why:** The side button is reserved for Siri; iOS needs a user gesture before audio capture or playback.
- **Rejected:** Side button activation (not available to third-party apps).
- **Evidence:** shopy_brief.md §4, §9.6, §20
- **Source:** user (project brief §20) · confidence high

## D-003 · Backend is Python + FastAPI
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** The backend is Python 3.12 with FastAPI, Pydantic v2, async SQLAlchemy 2 and Alembic.
- **Why:** inferred — the developer's chosen stack (brief §5); OpenAPI is generated automatically.
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §5, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-004 · Single Postgres database with pgvector
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** One PostgreSQL 16 database (pgvector + unaccent) holds catalog, embeddings, orders and the job queue. No Redis, broker or separate vector store.
- **Why:** inferred — one store keeps transactions (outbox, revalidation) atomic and the deployment small.
- **Rejected:** Redis or a message broker for the queue (brief §5).
- **Evidence:** shopy_brief.md §5, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-007 · LLM is Claude Haiku 5.5 with tool use and streaming
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** The agent uses `claude-haiku-5-5` (name from `LLM_MODEL`) with tool use and streaming. Escalate to Sonnet only when evals show Haiku fails.
- **Why:** Cost (budget in §4) and latency (target under 2 s to first audio).
- **Rejected:** A larger model by default.
- **Evidence:** shopy_brief.md §5, §10.1, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-009 · Speech and embedding providers
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** STT is the OpenAI transcription API with `language=ro`; TTS is an Azure AI Speech Romanian neural voice; embeddings are OpenAI `text-embedding-3-small`. Model and voice names come from env.
- **Why:** inferred — Romanian quality and cost (brief §5).
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §5, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-021 · Language split: Romanian voice, English everything else
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Voice input, TTS output and the assistant's spoken and written replies are Romanian. UI labels, admin panel, code, comments, docs and commit messages are English.
- **Why:** The users speak Romanian; the codebase stays readable in English.
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §1, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18
