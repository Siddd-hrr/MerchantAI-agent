# Consumer Chat Observation Log — Phase 1 (Gemma)

**When:** 2026-08-30 ~23:07–23:10 IST (UTC ~17:37–17:40)  
**Observer:** Cursor agent (backend audit + Redis + gateway logs; no browser automation)  
**Model config:** `GEMINI_MODEL_NAME=gemma-4-31b-it` (`.env`)  
**UI:** http://127.0.0.1:5173/ (consumer chat)  
**Session observed:** `0a3a1bf2-ce95-4518-9529-877c18d71d9f`  
**Consumer agent id:** `consumer-agent-demo-001`

---

## 1. What the consumer tried (reconstructed)

From Redis session state + audit trail:

| Turn (approx UTC) | Evidence | Outcome |
|-------------------|----------|---------|
| 17:37:50 | `FIELDS_STILL_MISSING` | Stuck asking for product+brand, qty, address, phone, name |
| 17:39:36 | same | No progress |
| 17:39:56 | same | Still no progress |

**Parsed cart at observation time:**

- Line item 1: `maggie` — brand=`null`, qty=`null`, `resolved=false`
- Line item 2: `milk` — brand=`null`, qty=`null`, `resolved=false`
- Customer name / address / phone: all `null`
- Status: `AWAITING_FIELDS`
- `catalog_suggestions`: **[]** (empty)
- Mandate: `mandate_verified=true` (valid mandate path worked)

Latest message stored on session state: `"Milk"`.

---

## 2. What worked

1. **Browser → Gateway → Worker → Agent** path is live (many `POST /v1/converse` 200s).
2. **Valid mandate** passes (session has `mandate_verified: true`).
3. **Intent parse** at least creates line items from casual words (`maggie`, `milk`).
4. Agent consistently returns the **hard-coded Phase 1 missing-fields warning** (spec-compliant wording).

---

## 3. Bugs / friction found (priority order)

### P0 — Redis `catalog:index` was empty → catalog never resolves

**Observed:** `catalog:index` in Redis was `[]` (empty list).

**Why it breaks chat:**  
`CatalogService.search_by_name` treats “index exists” as authoritative, including an empty list, and **does not fall back to Postgres**. So searches for `milk` returned **0 matches** even though Postgres has:

- `Milk` / `Amul`
- `Milk` / `DairyGold`
- (and other items)

**User-visible effect:**  
Forever stuck on “Exact product name + brand (per item)” with **no catalog suggestions** to pick from. Feels like the agent is ignoring the consumer.

**Mitigation applied during observation (2026-08-30):**  
Rebuilt catalog cache from DB via `rebuild_catalog_index_from_db` so live testing can continue.

**Future fix ideas:**

1. Treat empty index as cache miss → fall back to DB and re-warm.
2. On agent / admin startup, always warm `catalog:index` if missing or empty.
3. After `seed_catalog`, always warm Redis (document + automate).
4. Add health check: `catalog:index` length > 0.

---

### P1 — No Maggi / Maggie in seeded catalog

Consumer asked for **maggie**. Catalog has no Maggi/noodles SKU. Even with a healthy index, this should return “not found / suggest alternatives”, not silent empty suggestions.

**Future fix ideas:**

- Add Maggi (or common demo SKUs) to seed CSV.
- When `resolved=false` and suggestions empty, reply with explicit “not in catalog” + top categories / similar names (fuzzy).
- Typo handling: `maggie` → Maggi.

---

### P1 — Reply UX is repetitive / non-guiding

Every turn returns the same long warning block. It does **not**:

- Show catalog options when multiple brands exist (e.g. Amul vs DairyGold Milk)
- Ask one clarifying question at a time (“Which brand of milk?”)
- Acknowledge what was understood (“Got it — you want milk and maggie…”)

`ask_for_fields` only adds a suggestions sentence if `catalog_suggestions` is non-empty — which was empty due to P0.

**Future fix ideas:**

- Prefer **progressive disclosure**: ask brand, then qty, then address.
- Always surface suggestions or “not found” when items are unresolved.
- Keep the legal/spec warning, but prepend a short helpful sentence.

---

### P2 — Brand/qty extraction weak on short messages

Messages like `"Milk"` correctly set `item_name` but leave `brand`/`qty` null (expected). Multi-item vague carts (`maggie` + `milk`) accumulate unresolved rows and keep the same giant missing list.

**Future fix ideas (esp. with Gemma):**

- Stronger structured prompt / few-shot for brand+qty.
- If one catalog match exists for name-only, auto-resolve OR force brand choice from matches.
- Default qty=1 when user says “I want X” (optional product policy).

---

### P2 — Model switch / process hygiene

- `.env` is set to **`gemma-4-31b-it`**.
- Earlier agent logs still showed warnings for **`gemini-3.6-flash`** before reload/restart.
- Agent uvicorn process was restarted during the Gemma switch; some turns may have hit different process generations.

**Future fix ideas:**

- Log `model_name` on each `/v1/agent/turn` (audit action `LLM_MODEL_USED`).
- Expose `GET /healthz` with `{ model: "..." }` so UI can show which brain is live.

---

### P3 — Audit trail is thin for chat debugging

For this session, audit only recorded repeated `FIELDS_STILL_MISSING`. Missing:

- Raw consumer message text
- Parsed intent JSON
- Catalog match counts
- LLM errors / latency

**Future fix ideas:**

- Audit `TURN_RECEIVED`, `INTENT_PARSED`, `CATALOG_RESOLVE` with safe redacted payloads.
- Optional LangSmith once key is available.

---

### P3 — Catalog has low Amul Milk stock (`quantity_available=1`)

Once resolution works, stockout / reservation paths become easy to hit — good for Phase 2 demos, surprising for Phase 1 happy path.

---

## 4. Definition of “good” next consumer test (after catalog warm)

Have the consumer send **one clear turn**, e.g.:

> I want Amul Milk quantity 1. Customer name Siddhesh Test, mobile 9876543210, delivery address 12 MG Road Pune 411001.

Expected:

1. Catalog resolves Amul Milk  
2. Missing fields clear  
3. Status moves toward `VALIDATED` / invoice  
4. Audit shows more than `FIELDS_STILL_MISSING`

Also test invalid mandate once from UI (should fail at worker).

---

## 5. Improvement backlog (copy-paste)

- [ ] Fix empty Redis `catalog:index` treated as valid cache (P0)
- [ ] Auto-warm catalog on startup / after seed (P0)
- [ ] Empty-suggestion UX: “not in catalog” + fuzzy suggestions (P1)
- [ ] Add Maggi / common demo SKUs to seed (P1)
- [ ] Progressive field prompts; show brand choices (P1)
- [ ] Healthz includes active model id (P2)
- [ ] Richer per-turn audit events (P3)
- [ ] Gemma-specific structured extraction eval set (P2)

---

## 6. Snapshot IDs (for later repro)

```
session_id: 0a3a1bf2-ce95-4518-9529-877c18d71d9f
redis: session:0a3a1bf2-ce95-4518-9529-877c18d71d9f:state
redis: session:0a3a1bf2-ce95-4518-9529-877c18d71d9f:order_draft
model: gemma-4-31b-it
```

---

*Log created for future improvement while observing a live consumer browser chat. Update this file with later sessions rather than replacing it wholesale.*

---

## 7. Live watch resumed (2026-08-30 ~23:19 IST)

Continuous poller writing to [`CONSUMER_CHAT_LIVE_WATCH.md`](CONSUMER_CHAT_LIVE_WATCH.md).

**Active sessions at watch start:**

| Session | Last message | Issue |
|---------|--------------|--------|
| `877d3b53-…` (newest) | “I am thinking to purchase chocolates” | Not in catalog |
| `63a76f54-…` | “beans and milk” | Unresolved; earlier invalid-mandate attempt then valid |
| `0a3a1bf2-…` | “Milk” / maggie | Old stuck cart |
| `gemma-ok-…` | “1 liter Amul milk” | Extracted as item_name=`Amul milk` → **catalog miss** |

### P0b — Brand baked into `item_name` breaks search

Catalog names are `Milk`, `Beans`, etc.  
LLM often extracts `item_name="Amul milk"` + `brand="Amul"`.  
Search checks whether `"amul milk"` is contained in `"milk"` → **false** → 0 matches even when brand is correct.

**Fix ideas:** search on product token only; or strip brand from name; or match `name` OR (`brand`+`name`).

### Fix shipped (same night)

Implemented dynamic chat upgrades:

1. Catalog match: brand-in-name (`Amul milk`), fuzzy typos (`Millk`), empty Redis index → DB re-warm  
2. Missing-fields: **do not re-ask** brand/qty already provided  
3. Replies: “Already noted…” + **catalog suggestion list** + only truly missing fields  
4. Intent merge: keep prior cart; prefer product-only `item_name`
