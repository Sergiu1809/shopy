# Decisions — orders and confirmation

## D-011 · Order confirmation is a server-side state machine
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** The order state machine on the server is authoritative and validates every transition. "Yes" detection is a deterministic classifier; the LLM can never upgrade a result to CLEAR_YES.
- **Why:** "Yes" does not always mean yes; the model must not decide whether an order is confirmed.
- **Rejected:** Letting the LLM judge confirmations.
- **Evidence:** shopy_brief.md §12.1, §12.3, §20
- **Source:** user (project brief §20) · confidence high

## D-012 · On-screen confirmation threshold is 0 RON
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Every order, of any amount, ends with Face ID or passcode through WebAuthn. Not configurable: no env var can disable it.
- **Why:** Explicit confirmation for every order; the twist requirement's threshold is set to 0.
- **Rejected:** A configurable threshold.
- **Evidence:** shopy_brief.md §12.4, §20
- **Source:** user (project brief §20) · confidence high

## D-013 · WebAuthn challenge is bound to the proposal hash
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** The confirmation challenge is SHA-256(`proposal_hash` || random nonce), single use, stored with the proposal. The server recomputes the proposal hash from the DB at verification.
- **Why:** A biometric confirmation is cryptographically tied to the exact items, total, card and address; an assertion for proposal A never confirms proposal B.
- **Rejected:** An unbound challenge.
- **Evidence:** shopy_brief.md §12.5, §20
- **Source:** user (project brief §20) · confidence high

## D-014 · Any price or stock change invalidates a proposal
- **Status:** approved
- **Confirmed:** 2026-11-26
- **Date:** 2026-11-17
- **Rule:** At confirmation, in one transaction with `SELECT ... FOR UPDATE`, any price change (up or down) or any stock change since the proposal makes it INVALIDATED. Proposals expire after 5 minutes.
- **Why:** The user confirms exact values; the literal requirement counts any stock change.
- **Rejected:** Invalidating only on price increases or insufficient stock (see Q-006).
- **Evidence:** shopy_brief.md §12.2, §12.6, §20
- **Source:** user (project brief §20) · confidence high

## D-015 · Two ambiguous answers move confirmation to the screen
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** After 2 AMBIGUOUS answers on one proposal it moves to SCREEN_FALLBACK; voice "yes" is no longer accepted.
- **Why:** Repeated ambiguity means voice is not reliable for this confirmation.
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §12.1, §12.3, §20
- **Source:** user (project brief §20) · confidence high

## D-017 · Voice cancellation only before shipping
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** An order can be cancelled by voice only while PLACED, with the same rules as ordering: cancellation proposal, clear yes (same classifier and 2-strike rule), WebAuthn bound to its hash.
- **Why:** inferred — after shipping, cancellation is a return.
- **Rejected:** none stated
- **Evidence:** shopy_brief.md §12.8, §20
- **Source:** user (project brief §20) · confidence high
