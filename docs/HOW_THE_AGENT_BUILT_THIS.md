# How the AI Agent Built Merchant AI Agent (Phase 1)

**Correct project location:**  
`C:\Users\Siddhesh Akole\Desktop\Merchant-AI Agent\Merchant-AI-Agent`

**What went wrong earlier:**  
The first build pass placed files in the parent folder (`Merchant-AI Agent\`) instead of inside `Merchant-AI-Agent\`. This document lives in the correct folder. All application code, tests, Docker config, and frontend should be run from **this** directory.

**Related docs:**  
- Phase 2 story (simple words): [`HOW_THE_AGENT_BUILT_PHASE2.md`](HOW_THE_AGENT_BUILT_PHASE2.md)  
- Phase 2 status checklist: [`PHASE2_BUILD_NOTES.md`](PHASE2_BUILD_NOTES.md)  

---

## 1. What we are building (in plain English)

This is a **hackathon demo** for **Agent-to-Agent (A2A) commerce**:

- A **Consumer AI Agent** (or a human using the demo UI) sends chat messages to order groceries.
- A **Merchant AI Agent** replies, finds real products in a catalog, collects missing details (name, brand, quantity, address, phone, customer name), checks stock, and finally creates an **invoice**.
- Every important step is **logged** so you can see *why* something happened (audit trail).
- One **failure path** is built on purpose: a bad **Human Sign Mandate** is rejected before the merchant agent is ever called.

Phase 1 does **not** include real payments (Razorpay), real crypto signatures, or discount logic.

---

## 2. How the Cursor agent built it (process)

The work was split across specialized AI sub-agents:

| Part | Who built it | What they did |
|------|----------------|---------------|
| **Backend scaffold** | Codex-style agent | `pyproject.toml`, `shared/` models, Postgres/Redis config, Alembic migrations, Docker base |
| **Admin + catalog** | Codex | CSV/XLSX upload, seed script, Redis cache refresh |
| **LangGraph merchant brain** | Codex | All conversation nodes, warnings, invoice, audit logs |
| **Gateway + worker** | Codex | Public API, mocked mandate gate, nginx compose wiring |
| **Frontend demo UI** | Sonnet-style agent | Vite + React chat + upload UI in `frontend/` |
| **Tests + docs** | Codex + main agent | 21 pytest tests, README, edge-case report |

**Build order followed the master prompt (§10):**

1. Folder layout + Postgres/Redis  
2. Database models + migrations  
3. Admin upload + sample catalog seed  
4. Catalog service (Redis first, Postgres fallback)  
5. LangGraph nodes with **stubbed** LLM in unit tests  
6. Real Gemini wiring (needs your `GOOGLE_API_KEY` in `.env`)  
7. Invoice + audit  
8. Async worker mandate check  
9. Gateway `/v1/converse`  
10. Full Docker Compose + nginx load balancers  
11–13. E2E tests, README, reports  

---

## 3. System architecture (simple picture)

```
You / Consumer Agent
        │
        ▼
   GATEWAY (port 8000)          ← rate limit, logging, CORS for frontend
        │
        ▼
   ASYNC WORKER                  ← checks Human Sign Mandate (mocked)
        │                              │
        │ mandate OK                   │ mandate FAIL → error, stop here
        ▼
   MERCHANT AI AGENT              ← LangGraph conversation + Gemini
        │
        ├── Redis (session memory, catalog cache, audit stream)
        └── Postgres (items, orders, audit_log)

   MERCHANT ADMIN (port 8003)    ← upload CSV/XLSX catalog (separate internal API)

   FRONTEND (port 5173)          ← demo UI talks to gateway + admin
```

**Why an “async worker”?**  
The spec treats it as a **gatekeeper**: verify the mandate, normalize the request, then forward to the merchant agent. It is **not** a background job queue (no Celery/RabbitMQ).

---

## 4. Main folders (what each does)

| Folder / file | Purpose |
|---------------|---------|
| `shared/` | Config, DB, Redis, LLM client, SQLAlchemy models, API schemas |
| `services/gateway/` | Public `POST /v1/converse` |
| `services/async_worker/` | Mandate verification + forward to agent |
| `services/merchant_agent/` | LangGraph state machine, persona, invoice |
| `services/merchant_admin/` | `POST /admin/items/upload` |
| `migrations/` | Alembic DB schema |
| `scripts/seed_catalog.py` | Load sample grocery CSV into DB + Redis |
| `scripts/demo_converse.py` | CLI demo (happy path / `--invalid-mandate`) |
| `tests/` | Automated edge-case tests |
| `frontend/` | React demo UI |
| `infra/nginx/` | Load balancer configs for worker/agent pools |
| `docker-compose.yml` | Postgres, Redis, all services |

---

## 5. Conversation logic (LangGraph) — step by step

Each user message runs through a **state machine**. State is saved to **Redis after every step** so a crash does not lose the half-filled order.

### Step flow

1. **load_session** — Load previous order draft from Redis, or start fresh if new `session_id`.

2. **off_topic_guard** — LLM checks: is this message about ordering?  
   - If **no** → short fixed reply (“I only handle orders…”) and **stop**.  
   - If **yes** → continue.

3. **parse_intent** — LLM extracts from the message: product names, brands, quantities, address, phone, customer name. Merges into the draft.

4. **resolve_catalog** — For each product, look up the **real catalog** (Redis cache, then Postgres). Attach matches, ambiguities, or “not found”.

5. **check_availability** — For items with brand + quantity, is `quantity_available >= requested`?  
   - If **no** → go to **suggest_alternative**.  
   - If **yes** → continue.

6. **suggest_alternative** — Find up to **3 other brands** in the **same category** that are in stock. Show a **fixed warning block** (not LLM-written) so the consumer must pick an alternative. Write audit `ITEM_UNAVAILABLE`. **Stop** this turn.

7. **check_missing_fields** — Are all required fields filled?  
   (items + brand + qty per line, address, phone, customer name, mandate already verified at worker)  
   - If **missing** → **ask_for_fields**.  
   - If **complete** → **finalize_order**.

8. **ask_for_fields** — Show the **hard-coded warning template** listing what is still missing (repeated every turn until complete). LLM may add **one short** context sentence only. Audit `FIELDS_STILL_MISSING`. **Stop** this turn.

9. **finalize_order** — **Re-check stock** (in case it changed), lock/decrement quantities, set status `VALIDATED`. If stock failed → back to alternatives.

10. **generate_invoice** — Sum prices in **integer paise** (no floats), save `Order` as `INVOICED`, audit `INVOICE_GENERATED` with full line-item breakdown.

### Money rule

All prices are stored and calculated as **paise** (1 rupee = 100 paise) integers — never floating point — to avoid rounding bugs.

---

## 6. Human Sign Mandate (mocked gate)

Before the merchant agent runs, the **async worker** checks `human_sign_mandate`:

- It is a **base64-encoded JSON** blob: `{ issuer, subject, issued_at, signature }`.
- Checks:
  - `issuer` is in your allow-list (`TRUSTED_MANDATE_ISSUERS` in `.env`)
  - `issued_at` is within the last 5 minutes
  - `signature` is not empty
  - Same signature was **not used before** (replay protection in Redis `mandate:seen:{hash}`)
- On **any failure**: exact error  
  `MANDATE_INVALID` — *"Please include a cryptographic signature issued by a trusted issuer..."*  
  plus audit `MANDATE_VERIFY_FAILED`. The merchant agent is **never called**.

This is **mocked** for Phase 1 (no real cryptography).

---

## 7. Catalog and admin upload

- **Postgres** is the source of truth for items (`items` table).
- **Redis** caches each item (`catalog:item:{id}`) and an index set (`catalog:index`) for fast search.
- **Admin upload** (`POST /admin/items/upload`): CSV or XLSX with columns  
  `name, brand, category, unit, price_paise, quantity_available`.
- Bad rows are **rejected per row** (negative price/qty, missing name/brand, non-integers).
- Good rows **upsert** by `(name, brand)`.
- After upload, Redis cache is **refreshed** so reads see new data immediately.

**Sample seed data** includes deliberate demo cases:
- **Beans, HomeSelect** — quantity **0** (out of stock)
- **Beans, FreshFarm** — in stock (alternative brand)
- **Milk, Amul** — quantity **1** (easy low-stock demo)

---

## 8. Edge cases tested (simple explanations)

**21 automated tests** (`pytest`). Below is what each area checks and **why it matters**.

### Mandate / security gate

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Invalid mandate (bad base64) | Garbage token | Exact `MANDATE_INVALID` error |
| Replay mandate | Same signature used twice | Second use rejected |
| Valid mandate | Good issuer + fresh timestamp | Accepted; signature marked “seen” in Redis |
| Worker blocks bad mandate | Invalid token hits worker API | Returns `FAILED` status; **does not** call agent |
| Gateway mandate failure | Bad token through full gateway path | Same error shape returned to client |

### Missing order fields

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Missing fields warning | Order missing address/phone/etc. | **Fixed warning text** appears verbatim every turn |
| Node-level missing fields | Partial draft in graph | Warning block includes required checklist |

### Stock / alternatives

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Out-of-stock alternative | Request more than available | Warning + up to 3 same-category alternatives; audit `ITEM_UNAVAILABLE` |
| OOS warning template | Template rendering | Exact wording from spec (brand, item, alternatives) |
| Seed catalog OOS SKU | Read `sample_catalog.csv` | HomeSelect Beans qty=0 exists for demos |

### Conversation guardrails

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Off-topic message | “Tell me a joke” | Short redirect; graph stops; no invoice |
| Invoice total | Multiple line items | `total_paise` = sum of qty × unit price (integers) |

### Catalog / admin

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Redis cache hit | Item in Redis | Served from cache, not DB |
| Redis miss | Item only in Postgres | Loaded from DB and cache warmed |
| Search by name | “Beans” query | Returns matching catalog entries |
| Alternatives filter | OOS brand | Other brands in same category, in stock |
| CSV bad rows | Negative price, missing brand | Row rejected with reason |
| CSV happy path | Valid rows | Inserted/updated counts returned |

### Gateway

| Test | What we simulate | What should happen |
|------|------------------|-------------------|
| Forward to worker | Valid converse request | Gateway proxies to worker URL |
| Rate limit | Too many requests/minute | Throttled / failed response |

### Phase 2 leftovers (must stay unused)

| Test | What we check | What should happen |
|------|---------------|-------------------|
| Discount table unused | Scan service code | **No** runtime reads from `discounts` table (schema only) |

### Not fully automated yet

- **Live Gemini** multi-turn conversation (needs your `GOOGLE_API_KEY` in `.env`)
- **Full `docker compose up --build`** for all scaled replicas (infra was partially validated; Postgres/Redis seeded on remapped ports)

See also: `EDGE_CASE_TEST_REPORT.md` for pass/fail checklist.

---

## 9. Frontend (what it does)

Located in `frontend/`:

- **Hero** — “Acme Mart” branding, A2A ordering intro  
- **Chat panel** — sends messages to `http://localhost:8000/v1/converse`  
  - Buttons: generate **valid** or **invalid** mandate for testing  
  - Shows status, missing fields, suggestions, invoice, errors  
- **Catalog upload** — sends file to `http://localhost:8003/admin/items/upload`  

Run: `cd frontend && npm install && npm run dev` → open `http://localhost:5173`

---

## 10. How to run (from this folder)

```powershell
cd "C:\Users\Siddhesh Akole\Desktop\Merchant-AI Agent\Merchant-AI-Agent"

# 1. Copy and edit secrets (you do this manually)
copy .env.example .env
# Set GOOGLE_API_KEY, and ports if needed:
#   DATABASE_URL → localhost:5433
#   REDIS_URL → redis://localhost:16379/0

# 2. Python deps
uv sync

# 3. Database (Docker)
docker compose up -d postgres redis
alembic upgrade head
python -m scripts.seed_catalog

# 4. Services (separate terminals) OR full compose:
docker compose up --build -d

# 5. Demo CLI
python scripts/demo_converse.py
python scripts/demo_converse.py --invalid-mandate

# 6. Tests
.\.venv\Scripts\python -m pytest -q

# 7. Frontend
cd frontend
npm install
npm run dev
```

**Port note:** Host ports **5433** (Postgres) and **16379** (Redis) avoid clashes with other local services on 5432/6379.

---

## 11. Definition of Done (master prompt §11)

| Requirement | Status |
|-------------|--------|
| Docker brings up gateway, workers, agents, postgres, redis, admin, LB | Built; full scaled smoke test pending your run |
| Catalog upload → queryable in Postgres + Redis | ✅ Implemented + tested |
| Full ambiguous → invoice via gateway | ✅ Logic built; live Gemini needs API key |
| OOS → same-category alternative + audit | ✅ Tested |
| Invalid mandate → exact error + audit, agent not called | ✅ Tested |
| Money actions have audit rows | ✅ Implemented |
| Discounts table exists, unused | ✅ Tested |
| README < 10 min demo | ✅ See `README.md` |
| Frontend demo | ✅ In `frontend/` |

---

## 12. Files to read first

1. `README.md` — quick start  
2. `EDGE_CASE_TEST_REPORT.md` — test results matrix  
3. `services/merchant_agent/graph/build_graph.py` — conversation flow wiring  
4. `services/merchant_agent/persona.py` — fixed warning templates  
5. `services/async_worker/mandate_verifier.py` — mandate gate logic  
6. `tests/` — all edge-case proofs  

---

*Generated to document the AI-assisted Phase 1 build. Update this file if you change architecture or add Phase 2 features.*
