# Decisions — agent and voice

## D-008 · Voice pipeline is a cascade (STT, LLM, TTS)
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Voice runs as STT → LLM → TTS, not speech-to-speech.
- **Why:** Exact transcripts are needed for confirmation logging, and text must be validated before it is spoken.
- **Rejected:** Speech-to-speech models.
- **Evidence:** shopy_brief.md §9.1, §20
- **Source:** user (project brief §20) · confidence high

## D-010 · Prices, stock and totals come only from the DB
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Price, stock and totals are read only from the database. Tools accept IDs and quantities only. An output guard rejects unverified numbers and products. Order summaries are deterministic templates.
- **Why:** Every stated fact must be grounded; a test proves an invented price is rejected.
- **Rejected:** Trusting model-generated numbers.
- **Evidence:** shopy_brief.md §2, §10.2, §10.4, §20
- **Source:** user (project brief §20) · confidence high
- **Confirmed:** 2026-11-18

## D-018 · No memory across sessions
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Each assistant session starts fresh; only order history is available, through a tool.
- **Why:** inferred — scope and privacy for v1.
- **Rejected:** Cross-session memory (non-goal).
- **Evidence:** shopy_brief.md §2, §10.1, §20
- **Source:** user (project brief §20) · confidence high

## D-019 · Cost control with a usage ledger and caps
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Every paid external call writes to `usage_ledger`. Global cap 1 EUR per day; per-user cap 100 messages per day. At a cap, no paid call is made and a fixed limit message is returned.
- **Why:** The external API budget is 10 to 20 EUR per month.
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §4, §15, §20
- **Source:** user (project brief §20) · confidence high

## D-020 · Transcripts only, 90-day retention
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Store transcripts, never audio. Messages are kept 90 days.
- **Why:** inferred — privacy and storage.
- **Rejected:** Storing audio.
- **Evidence:** shopy_brief.md §7, §20
- **Source:** user (project brief §20) · confidence high
