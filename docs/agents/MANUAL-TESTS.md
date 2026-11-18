# Manual tests — Shopy

<!-- graffino-agentic:team:begin v1 -->
> What only a person on real hardware or in a real environment can prove. Manual
> tests can be postponed, never skipped silently: a postponed test stays visible here.
>
> 1. **The builder adds the entry** with the change: status 🔴 untested, steps a person
>    can follow, where it must run. The ticket's manual-test field goes to Pending.
> 2. **Only the person who ran the test reports the result:** name, date, environment
>    or device, evidence (screenshot, log, photo on the ticket). Agents never mark a
>    test passed, and an automated test is never a manual test.
> 3. **Merging untested is allowed but never silent:** the entry stays in Queue, the
>    ticket cannot close, and the release check lists it.
> 4. **Waiving** is the developer's only, with a written reason.
> 5. **A passed entry is history.** A later change in the same area gets a new MT- ID.
> 6. **Regression runs** before a release use the environments below; one MT- per run.
> 7. Never create a separate ticket for one manual test; it belongs to the change's ticket.
>
> Baseline: everything released before 2026-11-17 counts as tested.
> Statuses: 🔴 untested · ❌ failed · ✅ passed · ⚪ waived.
<!-- graffino-agentic:team:end -->

## Environments
| Name | What (device / OS / account / env) | Who holds it |
|---|---|---|
| iphone | iPhone 17, iOS 27.x, Safari, installed PWA, HTTPS tunnel or deployed URL, Face ID enrolled | the developer |
| desktop | Windows laptop, current Chrome/Edge, text input, no mic required | the developer |

## Queue
| MT | Ticket | What to verify | PR | Merged / released in | Needs (where) | Status | Steps |
|---|---|---|---|---|---|---|---|
| MT-001 | GH-1 | `docker compose up` on the desktop: every service starts; Vite HMR works through the bind mount (covers `web/vite.config.*`) | #2 | — | desktop (Windows, Docker Desktop + WSL2) | 🔴 | 1. `cp .env.example .env`. 2. `docker compose up`; wait until all services run and `minio-init` exits 0. 3. http://localhost:8000/health shows `{"status":"ok"}`. 4. http://localhost:5173 shows "Shopy". 5. `docker compose logs minio-init` ends with "Bucket created successfully `local/shopy-images`" (or the bucket already exists). 6. http://localhost:8025 opens Mailpit. 7. `docker compose exec db psql -U shopy -d shopy -c '\dx'` lists `vector` and `unaccent`. 8. `docker compose logs worker` shows "worker idle". 9. Edit the heading in `web/src/App.tsx`; the open page updates without a manual reload; revert the edit. Note: port clashes on 5432/8000/5173/9000 with local services stop a container. |

## History
| MT | Ticket | What | Result | Tested by · date | Where | Evidence | Notes / waiver reason |
|---|---|---|---|---|---|---|---|
