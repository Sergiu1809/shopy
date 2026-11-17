# AGENTS.md — Shopy

<!-- graffino-agentic:begin v1 -->
## How we work here

**Before any work:** `git fetch --all --prune`, then `git pull --ff-only`. Stop on a
non-fast-forward or on uncommitted changes you did not make.

**Always load** (indexes; open the entry, or its topic file, before you rely on it):
`docs/agents/DECISIONS.md`, `docs/agents/PATTERNS.md`,
`docs/agents/CONTRACTS.md`, `docs/agents/OPEN-QUESTIONS.md`, `CONTEXT.md`.

**Load on demand:**

| When | Load |
|---|---|
| You rely on an entry | the entry, or its topic file under `docs/agents/<kind>/` |
| Structural work | `docs/agents/ARCHITECTURE.md` |
| Old code or a past decision needs explaining | `docs/agents/DECISIONS-SUPERSEDED.md`, `PATTERNS-SUPERSEDED.md` (never obeyed) |
| UI work | `docs/design/DESIGN.md`, `docs/design/registry.yaml` |
| Scope, requirements, phase plan, data model, test list | `shopy_brief.md` (the section named in the entry) |
| A ticket (team addon) | `docs/agents/TEAM.md`, `docs/agents/STATE.md`, `docs/agents/tasks/<ticket>/` |
| A change on a manual-test path (`.github/manual-test-paths`) | `docs/agents/MANUAL-TESTS.md` |

**Flow:** a change to more than a few lines, or one with a design choice, starts with
`/plan`. The approved plan runs with `/build`. Small fixes go straight to build, with
tests first where tests exist.

### The gate
Ask yourself: **does this change something already approved?**
- **Do, then report:** add a `candidate` pattern; add or answer an open question
  (only with an answer the user gave); write a `Proposed answer` the evidence
  supports (the question stays `investigating` until the user confirms it); fix a
  typo, link or moved path; code that follows the approved entries.
- **Propose and wait:** change, supersede or delete an `approved` pattern or
  decision; promote `candidate → approved`; add a decision; code that contradicts an
  entry. Use this shape, then stop:

```text
PROPOSAL: <add-decision | change | supersede | promote | delete>
- Existing: <ID and what it says, or "none">
- Proposed: <the new rule>
- Why now: <what changed>
- Impact: <files that follow the old rule>
- If approved: <old ID> → superseded-by <new ID> (kept, not deleted)
```
Before you propose, check `docs/agents/REJECTED.md`: never re-propose a rejected item
without new evidence. A rejected proposal is added there with the reason.

### Hard rules
- Build only from `approved` entries. Unanswered means out of scope: record a Q-,
  never invent a value, a requirement or a behaviour.
- Add nothing nobody asked for. Note it as a suggestion instead.
- Build the smallest change that meets the approved criteria, reusing existing code.
  A new abstraction, dependency, configuration option, extension point or broad
  refactor needs a concrete reason today. Never at the cost of tests or error handling.
- Tests first where the repo has tests. Never change what an existing test asserts
  to make code pass; an assertion you think is wrong goes to the user.
- Never write a secret, token, password or personal data into a file, commit or log.
- Never push, tag, release, or deploy without the user's go for that action.
- When you cite past work, label the intent: **replicate** (only for an `approved`
  pattern) or **for awareness only**. History is not a template.
- The code wins over any document. When they disagree, say so and fix the document.
- Report honestly: a failed check is reported with its output; a skipped step is
  named with its reason.

### Ledger rules
- IDs are one sequence per kind in this repo: `D-`, `PATTERN-`, `C-`, `Q-`. Never renumber.
- A provided contract (C-) lives here only; consumers link to it. Changing one is a
  PROPOSAL, and the plan names the consumer files too.
- Superseded entries stay (`status: superseded-by <ID>`) so old code stays explainable.
  Their index lines live in `DECISIONS-SUPERSEDED.md` / `PATTERNS-SUPERSEDED.md`, not
  in the always-loaded indexes; the lint (`--fix`) moves them.
- After any ledger change: `python3 docs/agents/tools/ledger-lint.py --fix` (next free
  ID: `--next D`). It must pass.
- **Confirmed:** when the user confirms an entry in a plan, set `- **Confirmed:** <date>`
  on it. Any edit to an entry removes its Confirmed line.
- A new reusable practice becomes a `candidate` pattern in the same session.
- A settled constraint becomes a decision PROPOSAL in the same session.
<!-- graffino-agentic:end -->

## 1. What this repo is
Shopy is a voice shopping assistant for one demo online store. A customer speaks
Romanian into a PWA on an iPhone (or types on desktop); the assistant finds products,
answers only from store data, builds a cart and places orders after a clear "yes" plus
Face ID. An admin area manages the catalog, index, conversations, orders and costs.
Personal project, one developer. Scope and design: `shopy_brief.md` (source of truth).

## 2. Stack and commands
React + Vite + TS PWA · Python 3.12 FastAPI + async SQLAlchemy + Alembic · Postgres 16
+ pgvector · reindex worker · Docker Compose locally (Windows, Docker Desktop + WSL2).

```bash
# Ledger (works now)
python3 docs/agents/tools/ledger-lint.py            # --fix rebuilds indexes, --next D
PREFIX=GH python3 .github/scripts/team-checks.py --branch <branch> --base main
# Planned in P0 (shopy_brief.md §17–§18) — not run: the code does not exist yet
docker compose up                                   # db, api, worker, web, minio, mailpit
make seed                                           # = docker compose run api python -m seed.seed
cd backend && ruff check . && mypy . && pytest      # Postgres+pgvector via testcontainers
cd web && npm run lint && npm run typecheck && npx vitest run
gitleaks detect                                     # also a pre-commit hook
python evals/run_evals.py                           # real LLM, manual only, never in CI
# Screenshots: not defined yet (Q-009)
```
Replace the planned lines with the real ones when P0 lands; dependency tools: Q-012.

## 3. Layout
Target layout (brief §6); only the docs exist so far.
- `shopy_brief.md` — the project brief (the brief's §6 layout calls it `PROJECT_BRIEF.md`; this name is kept).
- `backend/` — FastAPI app (`app/`), `worker/`, `migrations/`, `seed/`, `tests/`.
- `web/` — React PWA: `/app` (customer) and `/admin`.
- `evals/` — real-LLM scenarios (manual).
- `docs/agents/` — the ledger; `docs/design/` — design rules and mocks; `docs/API.md` — REST and WebSocket examples.
- `.github/` — CI, PR template, team checks.

## 4. Rules for this repo
- Work phase by phase (brief §19, P0 → P8). A phase ends with passing tests, green CI and an updated ledger.
- Read the brief section a task touches before planning it. Never invent a requirement: ask, or add a Q-.
- Stripe runs in test mode only. No real card data anywhere, ever.
- Real-LLM evals run only by hand; CI mocks every provider (PATTERN-012).
- Romanian in assistant replies and voice; English in UI, code, docs and commits (D-021).

## 5. Release
Base branch `main`. Feature branches and draft PRs per ticket (Team workflow below);
the developer merges with a merge commit. No version scheme or deploy yet: deploy is
P7 (Railway or Fly.io, Q-011). Never push, tag, release or deploy without the go.

## 6. Definition of done
- Backend: `ruff check`, `mypy` and `pytest` pass (once P0 exists).
- Web: lint, type check and `vitest` pass (once P0 exists).
- `python3 docs/agents/tools/ledger-lint.py` passes.
- UI changes: screenshots of every changed screen, light and dark, compared with `docs/design/DESIGN.md` (command: Q-009).
- Manual-test paths changed: an MT- entry exists in `docs/agents/MANUAL-TESTS.md`.
- New practices recorded as candidate patterns; open points recorded as Q- entries.

<!-- graffino-agentic:team:begin v1 -->
## Team workflow (tickets, PRs, reviews)

This repo runs the team addon. These rules add to "How we work here" and win where
they are stricter. Team settings: `docs/agents/TEAM.md`.

### Tickets
- **No ticket, no code.** Every change needs a `GH-<id>` ticket in GitHub Issues (issue #n = GH-n).
  Without one, stop and ask for it. This overrides any "keep working" default.
- Read the ticket, its parent and **every comment** before work; comments change
  requirements more often than descriptions do.
- Routine ticket updates are allowed without asking: comments that start with
  "AI:", the branch and PR link comment, and moving the ticket to in progress,
  blocked or in review.
- **Creating** a ticket needs the user's OK on the exact text. New tickets go to
  GitHub Issues of this repo, open, no milestone. Never close a ticket or change its scope fields.
- Tickets you create that depend on each other get the tracker's dependency: the one
  that waits is *blocked by* the one it needs (a screen ticket is blocked by its
  design subtask). A plain link only for related tickets that don't wait on each other.
- A ticket that adds or changes a screen has a **design subtask**. The screen is
  built only after that design is confirmed (`docs/design/DESIGN.md`).

### Deliveries
A **delivery** is one reviewable piece of work: a ticket, or a ticket with the
dependent subtasks that only make sense together. Tracking and code are separate.
- One **integration branch** and one draft PR per delivery, named after the
  delivery's ticket. The PR Summary has one `Fixes GH-…` or
  `Part of GH-…` line per ticket it covers. Every covered ticket gets the
  branch and PR links.
- A separate PR only when a part is independently reviewable or releasable, owned by
  someone else, or too big to review with the rest. Then the PRs **stack**: the
  parent ticket's branch has its draft PR into `main`; each subtask
  branches from it (or from the subtask it builds on) and its PR targets it.
- A subtask never needs its own agent, worktree, branch or PR just because it exists.

### Git
- Branch: `feat|fix|chore/<short-name>-GH-<id>` from `main` (or
  from the parent's branch, above).
- Push the integration branch and open a **draft PR at once**, then comment both
  links on every ticket it covers before any further work.
- **Worker branches** (parallel builders, in a worktree) are private: never pushed,
  no PR, no link comment. Only the conductor updates the integration branch.
- Commits: `GH-<id> - <type>(<scope>): <what>` naming the ticket the commit
  implements (a subtask's own ID inside a shared delivery), with the co-author
  trailer. History stays linear.
- **Never amend, squash, rebase or force-push anything already pushed.** Update a
  pushed branch from `main` only when a person asks.
- PR description: the five sections of `.github/pull_request_template.md`.
- **Never merge or approve a PR**, and never count your own review as the human
  review. Never touch `main`, `master`/`main`, `release/*`, `hotfix/*`.

### Defects you meet
- One your own work introduced: fix it.
- An existing one that blocks an approved acceptance criterion, with clear expected
  behaviour and a small fix: fix it in the same PR, **reproduction first** (a failing
  test). Name it in the PR's Testing done; no separate ticket.
- Anything else (unrelated, worth releasing on its own, a production problem, growing
  scope): don't fix it; write it under the PR's Observations. Unspecified behaviour or
  conflicting requirements: stop and ask.

### Pipeline
`/start GH-<id>` runs: product owner → **gate A** (you answer) → `/plan`
→ **gate B** (you approve the plan and the knowledge used) → test author (tests
red) → `/build` → reviewer (at most 2 rounds) → **gate C** (you review and merge).
The conductor **proposes the lane** by risk and you confirm it; the fast lane is plan
→ gate B → build (test first) → reviewer (1 round) → gate C. `/start <ticket> fast`
asks for the fast lane directly. When the intended behaviour changes, the test author
goes first again.

### IDs
Before you take the next ledger ID: `git fetch`, then `ledger-lint.py --next D` on the
up-to-date base branch. On a collision, the ID already on the base branch wins;
renumber yours.

### Journal
Every session ends written down, finished or not, in
`docs/agents/tasks/GH-<id>/` (the delivery's ticket): `OVERVIEW.md` (context
brief, "Resume here", status, manifest) and `log_YYYY-MM-DD_HHMM.md`. Templates:
`docs/agents/tasks/_templates/`. Each other covered ticket gets a stub `OVERVIEW.md`
(`delivered in:` the delivery's ticket). "What happened on GH-123?" is
answered from that folder alone. Load only the one ticket folder you need, never the
whole journal. Under `/start`, workers return handoffs and only the conductor writes
the journal.
`docs/agents/STATE.md` holds one row per ticket in flight and the last 10 done (each
row ≤ 220 characters); every session that starts, pauses or finishes a ticket updates
its row.
Manual tests: anything only a person can prove gets an entry in `docs/agents/MANUAL-TESTS.md`; only the person who ran it reports the result.
<!-- graffino-agentic:team:end -->
