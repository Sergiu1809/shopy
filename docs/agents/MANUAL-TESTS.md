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
| MT-002 | GH-13 | Real embeddings fill the index: kb_chunks for the 200 products, their reviews and the 5 policies; usage_ledger rows appear; a second full reindex (`make reindex`) makes no new paid call | [#16](https://github.com/Sergiu1809/shopy/pull/16) | — | desktop (Windows, Docker Desktop + WSL2); a real `OPENAI_API_KEY`; costs real money (well under 1 EUR) | 🔴 untested (not run; only the developer runs it and reports the result) | 1. In `.env`: a real `OPENAI_API_KEY`, `EMBEDDING_MODEL=text-embedding-3-small`, `PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS=0.02`, valid `SEED_*` passwords. 2. `docker compose down -v` (fresh db), then `docker compose up --build`. 3. `make seed`. 4. `docker compose logs -f worker` until it idles (no more rows processed). 5. In the db (`docker compose exec db psql -U <user> <db>`): `SELECT source_type, count(DISTINCT source_id) FROM kb_chunks GROUP BY 1;` → product 200, reviews ≤ 200 (products with reviews), policy 5. 6. `SELECT count(*), sum(units), sum(estimated_cost_eur) FROM usage_ledger;` → rows present, cost well under 1 EUR; note the count. 7. `SELECT count(*) FROM reindex_outbox WHERE done_at IS NULL;` → 0. 8. `make reindex`, wait for the worker to idle again. 9. Repeat step 6: the `usage_ledger` count is unchanged; repeat step 7: 0. |

## History
| MT | Ticket | What | Result | Tested by · date | Where | Evidence | Notes / waiver reason |
|---|---|---|---|---|---|---|---|
| MT-001 | GH-1 | `docker compose up` on the desktop: every service starts; Vite HMR works through the bind mount | ✅ passed | developer · 2026-11-18 | desktop (Windows, Docker Desktop + WSL2) | reported by the developer at GH-3 gate A | — |
