# Phase 2 Build Notes

Continuation of Phase 1. **Free-tier Gemini is unchanged** (`GEMINI_MODEL_NAME=gemini-3.6-flash`). No paid LLM switch.

## What was built (local Docker / FastAPI — same style as Phase 1)

| Area | Status |
|---|---|
| Offer Engine service (`:8004`) | Built — discounts/combos/coupons/festival/cross-sell + Redis sync |
| Reservation worker (`:8005`) | Built — reserve/commit/release + expiry loop |
| True-available API | Built — `GET /internal/items/{id}/true-available` on merchant_admin |
| ReAct tools + planner/selector/executor | Built into merchant_agent graph |
| Cross-sell + creative promo (stub on LLM fail) | Built |
| Offer invoice embedding + `offer_applied_log` | Built |
| Offer Engine UI | Merged into unified console — `frontend/` (Vite `:5173`) |
| Figma Marketplace Pulse | [design file](https://www.figma.com/design/htVAMqe5vQGlNQATtGZ6cJ) — Home/Chat/Catalog/Offers |
| True-available in offer engine | Wired — `availability_client` + pickable/combo/cross-sell filters; tests pass |
| Neon / Upstash / Vercel deploy | **Not done** — needs user cloud credentials (Track B) |
| LangSmith live traces | Env flags present; needs `LANGCHAIN_API_KEY` to enable |

## Gate A progress

- Unified console: **done** — one homepage with Chat / Catalog CSV / Offers (Marketplace Pulse).
- Figma: [https://www.figma.com/design/htVAMqe5vQGlNQATtGZ6cJ](https://www.figma.com/design/htVAMqe5vQGlNQATtGZ6cJ)
- Offer/cross-sell/campaign surfaces write audit events via `append_audit`.
- True-available used by offer engine catalog/combo/cross-sell paths.

### Gate A checklist (current)

- [x] A0 unified console UI (`frontend/` only; no `:5174` host required)
- [x] A1 true-available wired + `tests/test_offer_engine_true_availability.py`
- [x] A2 stockout E2E path documented (`EDGE_CASE_TEST_REPORT.md`, `scripts/e2e_stockout_checklist.md`)
- [x] A3 offer/cross-sell/campaign audit coverage on backend path
- [ ] Live free-tier E2E stockout→invoice captured in this environment (run checklist when stack is up)

## Run

```powershell
cd Merchant-AI-Agent
docker compose up -d postgres redis
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m scripts.seed_catalog
.\.venv\Scripts\python -m scripts.seed_offers
.\.venv\Scripts\python -m scripts.seed_memory

# terminals: gateway 8000, worker 8001, agent 8002, admin 8003, offer_engine 8004, reservation 8005
.\.venv\Scripts\python -m uvicorn services.offer_engine.main:app --port 8004
.\.venv\Scripts\python -m uvicorn services.reservation_worker.main:app --port 8005

cd frontend
npm install
npm run dev   # http://127.0.0.1:5173 — Home → Chat / Catalog / Offers
```

## Phase 2 DoD (honest)

- [x] Catalog can attach real offers (via offer_lookup)
- [x] Cross-sell preference first, then same-category fallback + creative line (stub if Gemini 429)
- [x] Reservation race + expire worker logic + tests
- [x] Invoice can embed accepted offers + offer_applied_log
- [x] Merchant UI create flows with pickable catalog items
- [ ] Vercel HTTPS deploy of agent + offer engine (deferred — local FastAPI instead)
- [ ] LangSmith full live trace (needs key + non-exhausted Gemini quota)
- [ ] Full E2E stockout→cross-sell→invoice with live Gemini (quota may block today)

Tests: run `.\.venv\Scripts\python -m pytest -q`
