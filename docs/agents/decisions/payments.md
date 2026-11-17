# Decisions — payments

## D-016 · Cards via Stripe SetupIntent; never by voice
- **Status:** approved
- **Date:** 2026-11-17
- **Rule:** Cards are added only in Settings with the Stripe Payment Element and a SetupIntent. The server stores only the payment method ID, brand, last4, expiry and primary flag. Cards and addresses are never added by voice.
- **Why:** Card data never touches our server.
- **Rejected:** Adding cards or addresses by voice; Apple Pay (non-goal).
- **Evidence:** shopy_brief.md §2, §13, §20
- **Source:** user (project brief §20) · confidence high
