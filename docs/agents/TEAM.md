# TEAM — Shopy

<!-- graffino-agentic:team:begin v1 -->
> Settings for the team addon. AGENTS.md → "Team workflow" holds the rules; this
> file holds the values they use. Change a value here, not in the rules.
<!-- graffino-agentic:team:end -->

| Setting | Value |
|---|---|
| Ticket prefix | GH (GitHub issue `#n` is ticket `GH-n`) |
| Tracker | GitHub Issues of https://github.com/Sergiu1809/shopy |
| Backlog for new tickets | open issues with no milestone |
| Ticket types | labels: `task`, `bug`, `investigation`, `design` (a screen ticket's design subtask uses `design`) |
| Ticket URL pattern | https://github.com/Sergiu1809/shopy/issues/N for `GH-N` |
| Base branch | main |
| Merge method | merge commit (who merges: the developer) |
| Ready-for-review notice | none: marking the draft PR ready on GitHub is the notice |
| Team rules doc | none |
| Manual tests | yes: `docs/agents/MANUAL-TESTS.md` + an MT- line in the PR |
| Manual-test paths | `.github/manual-test-paths` (a PR that changes them must name an MT- ID or say "Manual test: not needed") |
| Manual-test waiver | the developer (repo owner) |
| Manual-test baseline | 2026-11-17 (everything released before it counts as tested) |
| Tracker access for agents | `gh` CLI, signed in (`gh auth status`): `gh issue view N --comments`, `gh issue create`, `gh issue comment` |
| CI checks | `.github/workflows/team-checks.yml` on runner `ubuntu-latest` |

## Ticket template (for new tickets)
```text
Title: <what, and where>
Goal: <why>
Acceptance criteria: <checkable bullets>
Out of scope: <…>
Design: <the design subtask, or "no UI">
Open questions: <Q- IDs, or "none">
```
