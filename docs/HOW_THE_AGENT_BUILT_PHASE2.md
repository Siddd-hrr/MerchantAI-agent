# How the AI Agent Built Merchant AI Agent (Phase 2)

**Project location:**  
`C:\Users\Siddhesh Akole\Desktop\Merchant-AI Agent\Merchant-AI-Agent`

**This is a continuation of Phase 1.**  
Phase 1 still works (gateway → worker → merchant agent → invoice). Phase 2 **adds** offers, cross-sell, smarter agent tools, and stock reservation. It does **not** replace Phase 1.

**Prompt sources:**  
- `..\Master-Build Prompt\merchant_ai_agent_phase2_master_prompt.md`  
- `..\Master-Build Prompt\merchant_ai_agent_phase2_master_prompt_1.md`  

**Related docs:**  
- Phase 1 story: [`HOW_THE_AGENT_BUILT_THIS.md`](HOW_THE_AGENT_BUILT_THIS.md)  
- Short Phase 2 status: [`PHASE2_BUILD_NOTES.md`](PHASE2_BUILD_NOTES.md)  

---

## 1. What Phase 2 is (in plain English)

Phase 1 could take an order and make an invoice.  
Phase 2 teaches the merchant agent to also:

1. **Show discounts / combos / coupons / festival offers** on real catalog items  
2. **Cross-sell** when something is out of stock (merchant’s preferred alternative first)  
3. Write a **short creative promo line** (Gemini) — but if Gemini fails, use a safe stub text  
4. **Reserve stock** so two buyers cannot both “buy the last unit”  
5. Put applied offers on the **invoice** with `offer_id` + description + money saved  
6. Let the **merchant create offers** from a separate UI (not free-typed fake item IDs)

**Important decision you confirmed:**  
Keep the **free-tier Gemini** agent. We did **not** switch to a paid model.  
Model stays: `gemini-3.6-flash` (free tier).  
(Older prompt text said `gemini-2.0-flash`, but that model is dead — we keep free-tier, just the working model id.)

---

## 2. What we deliberately did *not* do yet

The Phase 2 prompt also mentions **Vercel + Neon + Upstash**.  
For this build we kept everything **local like Phase 1** (Docker Postgres/Redis + FastAPI), so you can run it on your machine without cloud accounts.

| Prompt idea | What we did |
|-------------|-------------|
| Offer DB on Neon | Same local Postgres (extra tables) |
| Offer Redis on Upstash | Same local Redis (extra keys like `offer:item:{id}`) |
| Agent / Offer Engine on Vercel | Local FastAPI services on ports **8004** / **8005** |
| LangSmith tracing | Env flags ready; needs your LangSmith key to turn on |

So: **features first, cloud deploy later.**

---

## 2.1 Gate A status right now (honest)

- **A0 unified console done:** one Vite app at `:5173` — Home → Chat / Catalog CSV / Offers (Marketplace Pulse). Legacy `frontend/offer-engine` is archive-only; do not host `:5174`.
- **A1 true-available done:** offer engine uses merchant_admin true-available for pickable catalog, combo, and cross-sell create paths.
- **A2/A3 done (local):** stockout E2E checklist documented; `OFFER_SURFACED` / `CAMPAIGN_SURFACED` / `CROSS_SELL_SURFACED` audits in ReAct executor; stockout audits include `alternatives_source` + `creative_promo_source`.
- **Figma:** [https://www.figma.com/design/htVAMqe5vQGlNQATtGZ6cJ](https://www.figma.com/design/htVAMqe5vQGlNQATtGZ6cJ)
- **Still open:** live free-tier stockout→invoice run when the stack is up; Track B cloud (Neon/Upstash/Vercel) needs credentials — see `TRACK_B_CLOUD.md`.

---

## 3. How the Cursor agent built Phase 2 (process)

Same style as Phase 1 — split work across sub-agents:

| Part | Who | What they built |
|------|-----|-----------------|
| **Offer Engine + DB models** | Codex | Offers / cross-sell / memory tables, migration, FastAPI `:8004`, seed offers |
| **Reservation layer** | Codex | Reserve / commit / release, worker `:8005`, true-available API, race tests |
| **ReAct brain upgrades** | Codex | Tools, planner → tool-selector → executor loop, invoice offer embedding |
| **Offer merchant UI (v1)** | Sonnet | Originally `frontend/offer-engine` |
| **Unified console** | Main + Figma MCP | Merged Chat + Catalog + Offers into `frontend/` `:5173` |
| **Glue + docs** | Main + Codex | Audits, true-available, Gate A notes |

**Build order (simplified from Phase 2 §11):**

1. New database tables (offers, cross-sell, reservation, memory)  
2. Offer Engine API + Redis sync + seed offers  
3. Reservation service + expiry worker  
4. Agent tools + ReAct loop + update Phase 1 nodes  
5. Invoice writes offer audit rows  
6. Merchant Offer UI  
7. Tests + honest “definition of done” notes  

---

## 4. Simple architecture picture (Phase 1 + Phase 2)

```
You / Merchant console (:5173)     ← ONE UI: Home → Chat / Catalog / Offers
        │
        ├── Chat ──────────────────► GATEWAY (:8000) → worker → agent
        ├── Catalog CSV ───────────► MERCHANT ADMIN (:8003)
        └── Offers ────────────────► OFFER ENGINE (:8004)

   MERCHANT AI AGENT (:8002)       ← Phase 1 graph + Phase 2 ReAct tools
        ├── catalog / session Redis
        ├── Postgres items/orders/audit
        ├── OFFER ENGINE (:8004)
        └── RESERVATION WORKER (:8005)

MERCHANT ADMIN (:8003)             ← catalog upload + true-available API
```

---

## 5. New pieces explained simply

### 5.1 Offer Engine (`services/offer_engine`, port 8004)

This is the “promotions brain” for merchants.

Merchant can create:

- **Discount** — % or flat off  
- **Combo** — buy these together, save  
- **Coupon** — needs a code  
- **Festival campaign** — time-bound seasonal offer  
- **Cross-sell mapping** — “if Beans HomeSelect is OOS, prefer FreshFarm Beans”

Every create:

1. Saves to Postgres (`offers` / `cross_sell_preferences`)  
2. Updates Redis cache key `offer:item:{item_id}` so the agent can read offers fast  

Also:

- `GET /offers/by-item/{item_id}` — agent uses this  
- `GET /catalog/pickable-items` — UI item picker (only real catalog items)

Seed script: `python -m scripts.seed_offers` (about 5 demo offers).

---

### 5.2 Stock reservation (`services/reservation_worker`, port 8005)

Phase 1 problem: two shoppers could both be told “available” for the last unit.

Phase 2 fix:

1. When order is almost ready (`finalize_order`) → **`reserve()`** temporarily holds stock  
2. When invoice succeeds → **`commit()`** permanently reduces stock  
3. If shopper abandons / hold expires → **`release()`** gives stock back  

A background loop scans expired holds and writes audit:

`RESERVATION_EXPIRED_ROLLED_BACK`

“True available” quantity =  
`quantity_available − currently reserved`

Admin endpoint:  
`GET /internal/items/{item_id}/true-available`

---

### 5.3 Smarter Merchant Agent (ReAct tools)

Phase 1 graph still exists (load session → parse intent → catalog → availability → fields → invoice).

Phase 2 adds a small **ReAct loop**:

```
Planner → Tool Selector → Executor → (repeat, max ~4 times)
```

**Tools the agent can use:**

| Tool | Job |
|------|-----|
| `catalog_lookup` | Find products (Phase 1 catalog) |
| `offer_lookup` | Find discounts for an item |
| `cross_sell_lookup` | Merchant’s preferred OOS alternatives |
| `generate_creative_promo` | One short marketing line (Gemini; stub if 429) |
| `campaign_orchestrator_scan` | Look for active festival/combo opportunities |

**Important behavior on out-of-stock:**

1. Show the **same hard-coded Phase 1 warning** (never rewrite it)  
2. Prefer **merchant cross-sell list** if configured  
3. Else fall back to same-category brands (Phase 1 style)  
4. Add a **creative promo sentence under** the warning (not instead of it)

If Gemini quota is exhausted, promo falls back to a fixed stub string so the order flow does not die.

---

### 5.4 Memory types (simple meaning)

| Memory | Meaning | Where |
|--------|---------|--------|
| Short-term | This chat / draft order | Redis session (Phase 1) |
| Personal | Facts about a consumer agent across chats | Postgres `personal_memory` |
| Procedural | Playbooks like “how to handle stockout” | Postgres `procedural_memory` |
| Skill | Examples of good tool calls | Postgres `skill_memory` |

Seeded playbook: `handle_stockout` via `python -m scripts.seed_memory`.

---

### 5.5 Invoice changes

When an offer is actually accepted and used:

- Invoice JSON includes `{ offer_id, description, amount_saved_paise }`  
- A row is written to `offer_applied_log`  
- Reservation is **committed** (stock really deducted)

This keeps the audit trail explainable (Phase 1 “judged bar” still applies).

---

### 5.6 Unified console (`frontend/`, port 5173)

One Marketplace Pulse homepage with three features:

- **Chat** — converse via gateway (mandate + invoice)  
- **Catalog** — CSV/XLSX upload to merchant admin  
- **Offers** — Discounts / Combos / Coupons / Festival / Cross-sell (ported from `frontend/offer-engine`)

Item pickers call `/catalog/pickable-items` (true-available filtered) — merchant **cannot invent** fake item IDs.

---

## 6. New ports cheat-sheet

| Service | Port |
|---------|------|
| Unified console (Chat + Catalog + Offers) | 5173 |
| Gateway | 8000 |
| Async worker | 8001 |
| Merchant agent | 8002 |
| Merchant admin | 8003 |
| Offer engine | 8004 |
| Reservation worker | 8005 |
| Postgres (host) | 5433 |
| Redis (host) | 16379 |

---

## 7. How a Phase 2 conversation feels (story)

1. Consumer says: “I want HomeSelect Beans”  
2. Agent checks catalog + offers (“10% off if qty ≥ 2”)  
3. If HomeSelect is out of stock:  
   - Warning block (Phase 1 text)  
   - Prefer FreshFarm Beans (merchant cross-sell)  
   - Creative line: “Try FreshFarm — great with today’s rice combo!”  
4. Consumer accepts alternative + fills name/phone/address  
5. Agent **reserves** stock  
6. Invoice shows line items + offer id/description/savings  
7. Reservation is **committed**

If mandate is invalid → still fails at worker (Phase 1), never reaches agent.

---

## 8. What was tested

Examples of Phase 2 tests:

- Offer lookup (mocked HTTP)  
- Cross-sell preference + creative promo stub on LLM failure  
- Reservation: first reserve wins; second for last unit fails; release works  
- Phase 1 node tests still pass  

Run all:

```powershell
cd Merchant-AI-Agent
.\.venv\Scripts\python -m pytest -q
```

---

## 9. Definition of done — honest checklist

| Requirement | Status |
|-------------|--------|
| Offers come from real DB rows, not hard-coded fake discounts | Done |
| Cross-sell preference first, then category fallback | Done |
| Creative promo under warning; stub if Gemini fails | Done |
| Invoice embeds offer id + description + savings + log row | Done |
| Merchant UI create flows using pickable catalog | Done |
| Reservation prevents double-sell of last unit (logic + unit tests) | Done |
| Expired reservation auto-released by worker | Done |
| Free-tier Gemini kept | Done |
| Deploy agent/offer-engine on Vercel | **Not done** (local FastAPI instead) |
| Live LangSmith ReAct traces | **Needs your LangSmith key** |
| Full live Gemini E2E after quota burn | **Depends on free-tier reset** |

---

## 10. How to run Phase 2 (short)

```powershell
cd "C:\Users\Siddhesh Akole\Desktop\Merchant-AI Agent\Merchant-AI-Agent"

docker compose up -d postgres redis
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m scripts.seed_catalog
.\.venv\Scripts\python -m scripts.seed_offers
.\.venv\Scripts\python -m scripts.seed_memory

# start Phase 1 services (8000–8003) as before, plus:
.\.venv\Scripts\python -m uvicorn services.offer_engine.main:app --port 8004
.\.venv\Scripts\python -m uvicorn services.reservation_worker.main:app --port 8005

cd frontend
npm install
npm run dev
```

- Unified console: http://127.0.0.1:5173/ (Home → Chat / Catalog / Offers)

---

## 11. One-sentence summary

**Phase 2 = Phase 1 ordering, plus real offers, smarter out-of-stock cross-sell, stock holds so we don’t oversell, and one unified console for chat, catalog upload, and promotions — still on free-tier Gemma/Gemini, still runnable locally.**

---

*Written to match the Phase 1 explanation style. Update this file if you later migrate Offer Engine / Agent to Vercel or turn on LangSmith.*
