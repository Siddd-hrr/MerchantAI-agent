# Track B — Cloud migration (blocked on credentials)

Gate A local stack is the default demo path. Track B from the Phase 2 master prompt needs **your** cloud accounts — this repo does not provision Neon/Upstash/Vercel without keys.

## Prerequisites (provide these to continue)

1. Neon Postgres connection string → `OFFER_DATABASE_URL` / dual-URL Alembic
2. Upstash Redis URL + token → `OFFER_REDIS_URL` / session keys
3. Vercel project + token for Python FastAPI agent (`:8002`) and offer engine (`:8004`)
4. Optional: `LANGCHAIN_API_KEY` for LangSmith ReAct traces
5. Still **one** frontend deploy (this `frontend/` Vite app), not a second offers site

## Intended mapping

| Local | Cloud |
|---|---|
| Postgres offers/memory tables | Neon |
| Redis offer cache / short-term | Upstash |
| merchant_agent FastAPI | Vercel Python |
| offer_engine FastAPI | Vercel Python |
| Unified Vite console `:5173` | Single static/Vercel host |
| Phase 1 gateway/worker/admin | Stay Docker/local |

## Do not mark Gate B complete until

- [ ] Neon + Upstash live and migrated
- [ ] Agent + offer engine HTTPS URLs
- [ ] Worker `AGENT_URL` points at Vercel agent
- [ ] One UI URL
- [ ] At least one LangSmith Planner→Selector→Executor trace
