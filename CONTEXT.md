# CONTEXT — Shopy vocabulary

<!-- graffino-agentic:begin v1 -->
> The approved terms for this project. Use each term exactly as defined, in the part
> of speech given. Never swap in a synonym; never use a word on an _Avoid_ line.
<!-- graffino-agentic:end -->

**Assistant** (noun) — the voice and text shopping agent the customer talks to.
_Avoid_: bot, chatbot, AI

**Customer** (noun) — a user with role `customer`, using the PWA under `/app`.
_Avoid_: client, shopper, buyer

**Admin** (noun) — a user with role `admin`, using `/admin`.
_Avoid_: operator, staff, merchant

**Session** (noun) — one assistant conversation from `session.start` to its end; stored as a `conversations` row. Nothing carries over between sessions.
_Avoid_: chat, thread

**Turn** (noun) — one user utterance and the assistant's reply, identified by `turn_id`.
_Avoid_: exchange, round

**Utterance** (noun) — one spoken (`audio.utterance`) or typed (`text.utterance`) user input.
_Avoid_: prompt, query (for user input)

**Product** (noun) — a catalog item with description and attributes; it has one or more variants.
_Avoid_: item (except in a cart or order), article

**Variant** (noun) — one buyable form of a product (size, color, volume) with its own SKU, price and stock.
_Avoid_: SKU (for the row), option

**Minor units** (noun) — integer money amounts in bani (1 RON = 100 bani), VAT included.
_Avoid_: cents, pennies

**Chunk** (noun) — one indexed text piece (`kb_chunks`) from a product, its reviews or a policy, with an embedding and a tsvector.
_Avoid_: document, passage

**Outbox** (noun) — the `reindex_outbox` table; a row asks the worker to rebuild one source's chunks.
_Avoid_: queue, job table

**Output guard** (noun) — the server check that every product and number in an assistant reply is grounded, before it is spoken or shown.
_Avoid_: filter, validator, moderator

**Grounded** (adjective) — stated by a tool result or a store policy in the current session or turn.
_Avoid_: verified, factual

**Proposal** (noun) — an `order_proposals` row: a frozen snapshot of cart, prices, address and card awaiting confirmation; kind `order` or `cancellation`.
_Avoid_: draft order, quote, pending order

**Summary** (noun) — the proposal's deterministic Romanian `summary_text`, spoken verbatim.
_Avoid_: recap, description

**Clear yes** (noun) — the classifier result `CLEAR_YES`. Only the deterministic classifier produces it.
_Avoid_: approval, consent, "the user agreed"

**Ambiguous answer** (noun) — the classifier result `AMBIGUOUS`; two on one proposal trigger screen fallback.
_Avoid_: unclear yes, maybe

**Screen fallback** (noun) — the `SCREEN_FALLBACK` state: confirmation only by tapping Confirm on the confirmation sheet.
_Avoid_: manual mode

**Confirmation** (noun) — the `order_confirmations` audit record: transcripts, path and WebAuthn assertion for one proposal. Append-only.
_Avoid_: receipt, approval log

**Passkey** (noun) — the WebAuthn credential registered at onboarding; used with Face ID or passcode.
_Avoid_: biometric key, Face ID key

**Cost cap** (noun) — the global daily EUR cap or the per-user daily message cap; reaching one emits `limit.reached`.
_Avoid_: quota, budget (for the cap itself)
