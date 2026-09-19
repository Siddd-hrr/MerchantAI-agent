# Phase 2 Offer Logic — Manual Chat Testing Guide

Use this guide to verify whether the Merchant AI Agent correctly handles **cross-sell**, **upsell (discounts)**, **campaign orchestrator (combo + festival)**, **creative promo on stockout**, and **invoice discount application**.

Test in the unified console: **http://127.0.0.1:5173/** → **Chat**.

Always click **Send + Valid Mandate** (invoice path requires a verified mandate).

---

## 1) Before you start

### Services (must be running)

| Service | Port |
|---------|------|
| Frontend | 5173 |
| Gateway | 8000 |
| Async worker | 8001 |
| Merchant agent | 8002 |
| Merchant admin | 8003 |
| Offer engine | 8004 |
| Reservation worker | 8005 |
| Postgres | 5433 |
| Redis | 16379 |

### Seed catalog + offers (one-time per fresh DB)

```powershell
cd Merchant-AI-Agent
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m scripts.seed_catalog
.\.venv\Scripts\python -m scripts.seed_offers
.\.venv\Scripts\python -m scripts.seed_memory
```

### Confirm offers exist

Open **Offers → Saved** in the console, or call:

`GET http://localhost:8004/offers/saved`

You should see discounts, combo, coupon, festival, and an active cross-sell preference.

---

## 2) Catalog + offer reference (seeded data)

### Products you will order

| Product | Brand | Stock | Unit price |
|---------|-------|-------|------------|
| Beans | **HomeSelect** | **0** (out of stock) | ₹138.00 |
| Beans | **FreshFarm** | 18 | ₹145.00 |
| Milk | **DairyGold** | 25 | ₹62.00 |
| Milk | **Amul** | 1 | ₹65.00 |
| Rice | **Fortune** | 12 | ₹325.00 (5 kg) |
| Sugar | **Madhur** | 20 | ₹49.00 |

### Seeded offers (what should trigger)

| Type | Name | Trigger | Expected saving |
|------|------|---------|-----------------|
| **Cross-sell** | HomeSelect → FreshFarm Beans | Order **HomeSelect Beans** (any qty) | Suggests **FreshFarm Beans** when OOS |
| **Discount (upsell)** | FreshFarm Beans Bulk Saver | **2+ FreshFarm Beans** | 10% off beans subtotal |
| **Discount** | Fortune Rice Family Deal | **1+ Fortune Rice** | Flat ₹30 off |
| **Combo** | Breakfast Combo | **DairyGold Milk + Madhur Sugar** (1 each) | Flat ₹15 off |
| **Festival campaign** | Monsoon Pantry Festival | **Amul Milk + Fortune Rice** in cart | 5% cashback on those items |
| **Coupon** | Weekend Coupon `SAVE20` | Bill ≥ ₹500 + code | Flat ₹20 off |

> **Coupon note:** The coupon is stored in the Offer Engine, but the chat agent does **not** currently parse coupon codes in messages. Test coupons via the Offers UI / API; do not expect `SAVE20` in chat to apply automatically.

---

## 3) How the agent behaves (what to look for)

| Capability | Visible in chat reply? | Visible on invoice? |
|------------|------------------------|-------------------|
| **Cross-sell** on stockout | **Yes** — OOS warning + alternative list | After you accept substitute and complete order |
| **Creative advertisement** on stockout | **Yes** — short promo line under alternatives (LLM or stub fallback) | No |
| **Upsell / discount** | Separate **💡 Promotions & deals** block below catalog options (not inline on each line) | **Yes** — `accepted_offers` + lower total |
| **Combo / festival campaign** | Same promotions block + combo/festival lines when items match | **Yes** — if items match, offer appears in `accepted_offers` |

### Invoice pass criteria

When status becomes **INVOICED**, check the invoice block in Chat:

- Line items match what you confirmed (brand + product + qty).
- **Total** is subtotal minus all savings.
- **Accepted offers** lists each applied discount with `amount_saved_paise`.

Manual total check:

```
final_total = sum(qty × unit_price) − sum(amount_saved_paise)
```

---

## 4) Test scenarios — copy/paste chat scripts

Use **one fresh browser session per scenario** (refresh Chat or start a new tab) so line items do not mix.

**Multi-item stockouts in one turn:** You can order several items in a single message (e.g. `HomeSelect Beans 1, Amul Milk 10`). If more than one line is out of stock, the agent replies once with a section per item (cross-sell + promo for each). Reply with all substitutes in one message (e.g. `FreshFarm Beans 2, DairyGold Milk 1`). Avoid mixing unrelated test scenarios in the same cart — e.g. do not add Amul Milk qty 10 to a beans-only test, since Amul only has 1 in stock and will create a second stockout.

Provide **brand + product name** explicitly — the agent resolves against the real catalog.

---

### Scenario A — Cross-sell + creative promo (Phase 2 stockout path)

**Goal:** HomeSelect Beans is OOS → agent surfaces cross-sell target (FreshFarm) + promotional line.

**Turn 1 — send:**

```
I want to order 2 HomeSelect Beans
```

**Expect:**

- Status: `AWAITING_FIELDS`
- Reply contains: `HomeSelect Beans is not available`
- Alternatives list includes **FreshFarm Beans**
- Extra promo line below alternatives (creative ad from LLM, or stub: *"Promo tip: Try our smart substitute picks..."*)

**Turn 2 — accept substitute + add customer details:**

```
Switch to FreshFarm Beans instead, quantity 2. Customer name Siddhesh, phone 9876543210, address 42 Test Street Mumbai
```

**Turn 3 — if still awaiting fields, send:**

```
Confirmed — FreshFarm Beans 2 packs. Name Siddhesh, phone 9876543210, address 42 Test Street Mumbai
```

**Expect on invoice:**

- 2 × FreshFarm Beans
- **Bulk Saver** applied: 10% of ₹290.00 = **₹29.00 saved**
- Accepted offers includes *"Buy 2+ FreshFarm Beans packs and get 10% off."*
- Final total ≈ **₹261.00**

---

### Scenario A2 — Multiple stockouts in one chat turn

**Goal:** Two OOS lines resolved together — cross-sell/promo for **each** item in a single agent reply.

**Turn 1 — send:**

```
I want 2 HomeSelect Beans and 10 Amul Milk
```

**Expect (one reply):**

- Header: `Multiple items need substitutes`
- Section for **HomeSelect Beans** → FreshFarm alternative + promo
- Section for **Amul Milk** → DairyGold (or category) alternative + promo
- Both lines marked `stockout_pending` until substitutes are chosen

**Turn 2 — send all substitutes at once:**

```
FreshFarm Beans 2, DairyGold Milk 1. Customer name Siddhesh, phone 9876543210, address 42 Test Street Mumbai
```

**Expect:** Order proceeds toward invoice with both substituted lines and applicable offers.

---

### Scenario B — Upsell / discount only (no stockout)

**Goal:** Quantity-based discount without cross-sell.

**Turn 1 — send:**

```
Order 2 FreshFarm Beans. Customer name Test User, phone 9123456780, address 10 Discount Lane Pune
```

**Expect on invoice:**

- 2 × FreshFarm Beans @ ₹145.00 = ₹290.00
- Saved: **₹29.00** (10%)
- Final total: **₹261.00**
- `accepted_offers` has **FreshFarm Beans Bulk Saver**

---

### Scenario C — Flat discount (Fortune Rice)

**Goal:** Single-item flat discount.

**Turn 1 — send:**

```
I need 1 Fortune Rice 5kg. Name Ravi, phone 9988776655, address 7 Rice Road Delhi
```

**Expect on invoice:**

- 1 × Fortune Rice = ₹325.00
- Saved: **₹30.00** (Family Deal)
- Final total: **₹295.00**

---

### Scenario D — Combo (Breakfast Combo)

**Goal:** Campaign orchestrator detects **COMBO** when both items are in cart.

**Turn 1 — send:**

```
Order 1 DairyGold Milk and 1 Madhur Sugar. Customer name Combo Test, phone 9000000001, address 3 Breakfast Ave
```

**Expect on invoice:**

- DairyGold Milk ₹62.00 + Madhur Sugar ₹49.00 = ₹111.00
- Saved: **₹15.00** (Breakfast Combo)
- Final total: **₹96.00**
- `accepted_offers` mentions *"Buy DairyGold Milk with Madhur Sugar"*

---

### Scenario E — Festival campaign (Monsoon Pantry)

**Goal:** **FESTIVAL_CAMPAIGN** applies when Amul Milk + Fortune Rice are both ordered.

**Turn 1 — send:**

```
I want 1 Amul Milk and 1 Fortune Rice. Name Festival User, phone 9111111111, address 99 Monsoon Street
```

**Expect on invoice:**

- Amul ₹65.00 + Fortune Rice ₹325.00 = ₹390.00
- Saved: **5% cashback** = ₹19.50 (1950 paise)
- Final total: **₹370.50**
- `accepted_offers` mentions *"Monsoon Pantry Festival"* / cashback

---

### Scenario F — Stacked offers (advanced)

**Goal:** Multiple discounts on one invoice.

**Turn 1 — send:**

```
Order 2 FreshFarm Beans, 1 Fortune Rice, 1 DairyGold Milk, and 1 Madhur Sugar.
Customer name Stack Test, phone 9222222222, address 1 Multi Offer Road
```

**Rough expected savings (verify on invoice):**

| Offer | Approx. saving |
|-------|----------------|
| FreshFarm 10% on ₹290 | ₹29.00 |
| Fortune flat | ₹30.00 |
| Breakfast combo | ₹15.00 |
| **Subtotal** ₹466.00 − **₹74.00** | **≈ ₹392.00** |

Festival cashback may or may not stack depending on which items are in `resolved_offers` for that turn — treat this scenario as a **stress test** and record what the invoice actually shows.

---

## 5) Phase 2 “definition of done” checklist

Mark each after live chat testing:

- [ ] **Cross-sell:** OOS HomeSelect Beans → FreshFarm suggested first (not only random category fallback).
- [ ] **Creative promo:** Stockout reply includes promotional line (LLM or stub).
- [ ] **Upsell:** 2+ FreshFarm Beans → discount on invoice.
- [ ] **Combo:** Milk + Sugar → combo discount on invoice.
- [ ] **Festival:** Amul Milk + Fortune Rice → campaign discount on invoice.
- [ ] **Invoice math:** `accepted_offers` savings match manual calculation.
- [ ] **Mandate:** Invalid mandate does **not** reach INVOICED (use **Send + Invalid Mandate** once to confirm).
- [ ] **Offers UI:** Created offers appear under **Offers → Saved** and remain active during chat tests.

---

## 6) Optional deeper verification (audits)

If you want backend proof beyond the Chat UI:

```powershell
.\.venv\Scripts\python -m scripts.live_chat_watch
```

While chatting, look for audit actions on your `session_id`:

| Action | Meaning |
|--------|---------|
| `CROSS_SELL_SURFACED` | Cross-sell lookup ran |
| `ITEM_UNAVAILABLE` | Stockout handled; check `alternatives_source: cross_sell_preference` |
| `OFFER_SURFACED` | Offer engine returned promos for cart items |
| `CAMPAIGN_SURFACED` | Combo/festival scan ran |
| `INVOICE_GENERATED` | Order persisted |
| `OFFER_APPLIED_LOGGED` | Discounts written to `offer_applied_log` |

See also: `EDGE_CASE_TEST_REPORT.md`, `scripts/e2e_stockout_checklist.md`.

---

## 7) Troubleshooting

| Problem | Fix |
|---------|-----|
| Agent cannot resolve product | Use exact catalog wording: `FreshFarm Beans`, not just `beans`. |
| No cross-sell alternative | Re-run `seed_offers`; confirm HomeSelect Beans stock is 0 in catalog. |
| No discounts on invoice | Confirm offers are active under **Offers → Saved**; order must include eligible brands/qty. |
| Status stuck at `AWAITING_FIELDS` | Send missing fields: brand, qty, name, phone, address; use **Valid Mandate**. |
| Creative promo is generic stub | Normal on free-tier LLM quota (`429`); flow should still complete. |
| Connection error in Chat | Start gateway on port 8000 and merchant agent on 8002. |

---

## 8) Quick reference — messages only

| Test | Message to send |
|------|-----------------|
| Cross-sell | `I want to order 2 HomeSelect Beans` |
| Upsell | `Order 2 FreshFarm Beans. Name Test, phone 9876543210, address 1 Test St` |
| Rice discount | `1 Fortune Rice. Name Test, phone 9876543210, address 1 Test St` |
| Combo | `1 DairyGold Milk and 1 Madhur Sugar. Name Test, phone 9876543210, address 1 Test St` |
| Festival | `1 Amul Milk and 1 Fortune Rice. Name Test, phone 9876543210, address 1 Test St` |

Use **Valid Mandate** every time. Complete any follow-up turns until status is **INVOICED**, then verify line items, **accepted offers**, and final total.
