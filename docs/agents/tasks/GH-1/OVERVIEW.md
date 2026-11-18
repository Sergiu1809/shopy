---
ticket: GH-1
type: task
parent:
covers: []
delivered_in:
title: "P0 Setup: Docker Compose skeleton, CI, .env.example, gitleaks"
status: in-progress
lane: fast
branch: chore/p0-setup-GH-1
pr: https://github.com/Sergiu1809/shopy/pull/2
design_refs: []
summary: "Project skeleton: Compose services, backend and web shells, CI, .env.example, gitleaks"
created: 2026-11-18 13:16
updated: 2026-11-18 13:40
---

# GH-1 — P0 Setup: Docker Compose skeleton, CI, .env.example, gitleaks

## Goal
Give the project a running skeleton so every later phase (P1–P8) has a place to land:
services start locally, CI checks every push, and secrets cannot leak.
Ticket: https://github.com/Sergiu1809/shopy/issues/1

## Context brief 🧾
- **Acceptance criteria (approved):** see the ticket (GH-1 body); mapped to checks in `PLAN.md` → Acceptance points.
- **Tickets covered:** GH-1 (Fixes)
- **Constraints that apply:** Q-012 answered (uv + `pyproject.toml` backend, npm web); D-003 (Python 3.12 + FastAPI); D-004 (one Postgres 16 + pgvector + unaccent, no Redis); D-001 (React PWA; PWA plugin waits for P6); PATTERN-013 (secrets only in `.env`, names in `.env.example`, gitleaks in CI + pre-commit); PATTERN-009 (lint rule against `dangerouslySetInnerHTML`); PATTERN-012 (CI makes no provider calls); D-007/D-009 fix `LLM_MODEL`/`EMBEDDING_MODEL`; Q-003, Q-004, Q-013 open → those env values stay empty. No models, migrations, seed, auth, provider calls or deploy. `web/vite.config.*` is a manual-test path → MT-001.
- **Where the code is:** none yet; this ticket creates it: `backend/` (`app/main.py`, `worker/__main__.py`, `tests/`, `pyproject.toml`, `uv.lock`, `Dockerfile`), `web/` (Vite react-ts shell, `vite.config.ts`, `.oxlintrc.json`, `src/App.test.tsx`, `Dockerfile`), root `docker-compose.yml`, `docker/db/init/01-extensions.sql`, `.env.example`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`. Nearest existing example: `.github/workflows/team-checks.yml` (checkout + ledger-lint steps).
- **Ownership:** integration owner: conductor · one builder
- **Prerequisites (user):** enable Docker Desktop WSL integration for this distro (`docker` is not reachable from WSL today); gitleaks and pre-commit are not installed and are run via `uvx pre-commit` (no system install).
- **Verify with:**
  - `cd backend && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
  - `cd web && npm ci && npm run lint && npm run typecheck && npx vitest run`
  - `python3 docs/agents/tools/ledger-lint.py`
  - `uvx pre-commit run --all-files`
  - `git check-ignore .env docs/explain.md`
  - with Docker: `docker compose config -q && docker compose up -d && curl -fsS localhost:8000/health && curl -fsS localhost:5173 && docker compose exec db psql -U shopy -d shopy -c '\dx'`; else MT-001
  - CI: `ci.yml` green on the first push (after the user's go)

## Resume here ⏯
Gate B adjusted 2026-11-18 (bitnamilegacy MinIO, pinned). Builder resumes step (4) docker-compose.yml from the scratchpad draft, then step (7) docs + MT-001. 14 local commits, not pushed.


## Summary of work so far
- 2026-11-18 — Ticket created, Q-012 answered, fast lane confirmed, branch created.
- 2026-11-18 — Plan approved at gate B; entries confirmed; branch pushed; draft PR #2 opened.

## Approach
See `PLAN.md` (approved at gate B 2026-11-18).

## Cumulative file manifest 📁
| Action | Path | Purpose / what changed |
|---|---|---|
| modify | `.gitignore` | ignore `docs/explain.md` |
| modify | `docs/agents/OPEN-QUESTIONS.md` | Q-012 answered |

## Manual verification 🔧
MT-001 (desktop): `docker compose up` on Windows; steps in `PLAN.md` → Manual test plan.

## Decisions log 🧭
- **2026-11-18 — Local S3: bitnamilegacy MinIO, pinned** — Why: official MinIO images are gone; archived image is fine for local-only use (prod uses R2). Rejected: Chainguard (unpinnable `:latest`), dropping MinIO (changes AC), quay.io login.
- **2026-11-18 — oxlint, not ESLint (A6)** — Why: create-vite 9.3.4 ships oxlint + TS 7; typescript-eslint doesn't support TS 7. `react/no-danger` covers PATTERN-009. Rejected: ESLint + TS 6 downgrade; older create-vite 8.x.
- **2026-11-18 — Fast lane** — Why: clear, checkable criteria; no UI, migration, auth or contract change. Rejected: full lane (no unclear requirements to resolve).

## Open questions / blockers
- [ ] none

## Links
- Ticket: https://github.com/Sergiu1809/shopy/issues/1
- PR: https://github.com/Sergiu1809/shopy/pull/2
