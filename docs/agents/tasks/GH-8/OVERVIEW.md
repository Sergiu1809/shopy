---
ticket: GH-8
type: task
parent:
covers: []
delivered_in:
title: "Design: phone mockups for the Assistant home and Settings (addresses, cards)"
status: done
lane: fast
branch: chore/mockups-GH-8
pr: https://github.com/Sergiu1809/shopy/pull/9
design_refs: [DS-shopy-assistant, DS-shopy-settings]
summary: "Two draft phone mocks with provisional Apple-site-inspired tokens, for the user to look at"
created: 2026-11-19 16:43
updated: 2026-11-19 16:55
---

# GH-8 — Design: phone mockups for the Assistant home and Settings (addresses, cards)

## Goal
Quick, simple phone mockups to look at before any screen is built (brief §9.5; Q-008).
Ticket: https://github.com/Sergiu1809/shopy/issues/8

## Context brief 🧾
- **Acceptance criteria (approved, GH-8):**
  - [x] `docs/design/mocks/DS-shopy-assistant.html`: home at 390 px; mic button, status, transcript, 3 product cards, cart drawer.
  - [x] `docs/design/mocks/DS-shopy-settings.html`: addresses (list, default, add form) and cards (brand + last4, primary, "Add card" placeholder for the Stripe Payment Element); no real card data.
  - [x] Provisional light/dark tokens inside the mocks (Q-008 stays open).
  - [x] `registry.yaml`: both screens, status draft.
- **Tickets covered:** GH-8 (Fixes)
- **Constraints that apply:** Q-008 (tokens open, so provisional only); D-021 (English UI, Romanian assistant content); DESIGN.md guardrails (AA contrast, 44 px targets, focus ring, light/dark, labels).
- **User direction (2026-11-19):** urgent, simple, phone size; style "like DESIGN.md, similar to the Apple website".
- **Where the code is:** `docs/design/mocks/`, `docs/design/registry.yaml`.
- **Ownership:** integration owner: conductor · drawn directly (no builder; design only).
- **Verify with:** open the two HTML files in a browser at 390 px, toggle light/dark; `python3 docs/agents/tools/ledger-lint.py`.

## Resume here ⏯
Nothing to resume — completed on 2026-11-19 (PR #9 merged by the developer).

## Summary of work so far
- 2026-11-19 — Ticket created with the user's OK; two mocks drawn, checked in light and dark at 390 px; registry updated. (log: `log_2026-11-19_1643.md`)

- 2026-11-19 — Close button on the cart sheet (user request); user confirmed both mocks.

## Approach
Self-contained HTML per screen, one identical provisional token block (CSS custom properties, light + dark,
`prefers-color-scheme` plus a mock-only toggle). Minimal Apple-site-inspired look: white and `#f5f5f7`, `#1d1d1f` text,
blue accent, pill buttons, large tight headings, translucent blurred bars. No Apple logo or branding.

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| add | `docs/design/mocks/DS-shopy-assistant.html` | Assistant home mock |
| add | `docs/design/mocks/DS-shopy-settings.html` | Settings mock: addresses, cards |
| modify | `docs/design/registry.yaml` | two draft entries |
| add | `docs/agents/tasks/GH-8/` | journal |
| modify | `docs/agents/STATE.md` | GH-8 row |

## Manual verification 🔧
none: a design to look at; the user's confirmation is the check.

## Decisions log 🧭
- **2026-11-19 — Tokens live inside the mocks, not in DESIGN.md** — Why: Q-008 is open and changing DESIGN.md tokens is a PROPOSAL. Rejected: writing them to DESIGN.md now.

## Open questions / blockers
- [ ] Q-008 — tokens confirmed? (these mocks are the proposed starting point)

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/8
- PR: https://github.com/Sergiu1809/shopy/pull/9
