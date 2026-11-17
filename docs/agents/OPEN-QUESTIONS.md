# Open questions — Shopy

<!-- graffino-agentic:begin v1 -->
> Unknowns. Work that depends on an open question is out of scope until it is
> answered. Only the user answers; an agent never answers by guessing. An agent may
> write a `Proposed answer` the evidence supports; the question stays
> `investigating` until the user confirms it.
> Answered entries stay, with the answer and date, and usually become a D- or PATTERN-.
<!-- graffino-agentic:end -->

Q-001 to Q-006 are the brief's OQ-01 to OQ-06 (`shopy_brief.md` §22), in order.

## Index
- Q-001 · Where do the product images come from?
- Q-002 · What is the store-wide delivery estimate?
- Q-003 · Which Azure Romanian neural voice?
- Q-004 · Which OpenAI transcription model, and is its Romanian good enough?
- Q-005 · Does barge-in ship? · _deferred_
- Q-006 · Should any stock change keep invalidating a proposal? · _deferred_
- Q-007 · Where is the GitHub repo? · _answered_
- Q-008 · What are the design tokens?
- Q-009 · How do we screenshot the web UI?
- Q-010 · What is the exact canonical JSON for the proposal hash?
- Q-011 · Railway or Fly.io?
- Q-012 · Which package and dependency tools?
- Q-013 · Does the 1 EUR daily cap fit the monthly budget?

---

## Q-001 · Where do the product images come from?
- **Status:** open
- **Blocks:** P1 seed images. Brand-owned product photos are excluded (D-022).
- **Who answers:** the developer
- **Proposed answer:** royalty-free stock photos per category, or generated neutral product images (brief OQ-01 lists both).

## Q-002 · What is the store-wide delivery estimate?
- **Status:** open
- **Blocks:** the final shipping policy text and the confirmation email; stored in `store_policies` and config, never in prompts.
- **Who answers:** the developer
- **Proposed answer:** placeholder "2 to 4 business days" until answered (brief §8).

## Q-003 · Which Azure Romanian neural voice?
- **Status:** open
- **Blocks:** the default `TTS_VOICE` (P5).
- **Who answers:** the developer, after listening tests
- **Proposed answer:** `ro-RO-AlinaNeural` as the starting default (brief §5).

## Q-004 · Which OpenAI transcription model, and is its Romanian good enough?
- **Status:** open
- **Blocks:** the default `STT_MODEL` (P5).
- **Who answers:** the developer, after tests on real recordings
- **Proposed answer:** start with `gpt-4o-transcribe` (brief §5), verified against current OpenAI docs at P5.

## Q-005 · Does barge-in ship?
- **Status:** deferred
- **Blocks:** P8 only.
- **Who answers:** the developer, after tests on the target iPhone
- **Proposed answer:** ship only if reliable; otherwise keep the Stop button (brief §9.4).

## Q-006 · Should any stock change keep invalidating a proposal?
- **Status:** deferred
- **Blocks:** nothing now; D-014 applies (any change invalidates).
- **Who answers:** the developer, once several users exist

## Q-007 · Where is the GitHub repo?
- **Status:** answered 2026-11-17
- **Blocks:** the ticket URL pattern in `TEAM.md`, issues as tickets, CI runs, the PR flow of the team addon.
- **Who answers:** the developer
- **Answer:** public repo https://github.com/Sergiu1809/shopy, remote `origin`; issue `#n` is ticket `GH-n`.

## Q-008 · What are the design tokens?
- **Status:** open
- **Blocks:** any UI work (P1 admin, P3 assistant screen). `docs/design/DESIGN.md` has no tokens yet.
- **Who answers:** the developer
- **Proposed answer:** draft a token set (light and dark, WCAG AA) and mocks of the first screens in `docs/design/mocks/`, then confirm them before building.

## Q-009 · How do we screenshot the web UI?
- **Status:** open
- **Blocks:** step 5 of the UI procedure in `docs/design/DESIGN.md`.
- **Who answers:** the developer
- **Proposed answer:** a Playwright script (headless Chromium and WebKit, light and dark, 390 px and 1280 px wide) run against the Vite dev server, saving to `docs/design/screens/`.

## Q-010 · What is the exact canonical JSON for the proposal hash?
- **Status:** open
- **Blocks:** C-005 and the WebAuthn confirmation (P4).
- **Who answers:** the developer
- **Proposed answer:** RFC 8785 (JSON Canonicalization Scheme): sorted keys, no whitespace, integers in minor units, IDs as strings, expiry as RFC 3339 UTC with seconds.

## Q-011 · Railway or Fly.io?
- **Status:** open
- **Blocks:** P7 deploy (the brief leaves both open).
- **Who answers:** the developer

## Q-012 · Which package and dependency tools?
- **Status:** open
- **Blocks:** P0 skeleton (Dockerfiles, CI, commands in AGENTS.md section 2).
- **Who answers:** the developer
- **Proposed answer:** `uv` with `pyproject.toml` for the backend; `npm` for `web/`.

## Q-013 · Does the 1 EUR daily cap fit the monthly budget?
- **Status:** open
- **Blocks:** the default `DAILY_COST_CAP_EUR`. 1 EUR × 30 days = 30 EUR, above the 10–20 EUR monthly budget (brief §4 vs §15, D-019).
- **Who answers:** the developer
- **Proposed answer:** keep 1 EUR per day and add a monthly cap (e.g. 20 EUR), or lower the daily cap to about 0.60 EUR.
