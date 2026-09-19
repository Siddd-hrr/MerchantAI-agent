# E2E Stockout Checklist (Track A2)

Use this runbook to verify: OOS item -> cross-sell preference -> accepted alternative -> invoice with offer attribution.

## 1) Bring services up

```powershell
docker compose up -d postgres redis
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m scripts.seed_catalog
.\.venv\Scripts\python -m scripts.seed_offers
.\.venv\Scripts\python -m scripts.seed_memory
```

Run app services in separate terminals:

- gateway `8000`
- worker `8001`
- merchant_agent `8002`
- merchant_admin `8003`
- offer_engine `8004`
- reservation_worker `8005`

## 2) Pre-check cross-sell guard

Create/update cross-sell preference in Offer Engine using an OOS source SKU and in-stock target SKU(s).

- Expected reject case: if any configured target has true-available `0`, API returns `409 ITEM_TRUE_AVAILABILITY_ZERO`.
- Expected pass case: accepted preference points to truly available targets.

## 3) Run the stockout scenario

1. Start a new chat session and request an OOS item (or excessive quantity).
2. Confirm agent returns stockout warning and alternatives from cross-sell preference first.
3. Accept one suggested alternative.
4. Provide customer name, phone, and address.
5. Confirm invoice is generated.

## 4) Audit assertions (required)

Look for these actions in sequence for the same `session_id`:

1. `CROSS_SELL_SURFACED`
2. `ITEM_UNAVAILABLE` (with `alternatives_source: cross_sell_preference`)
3. `OFFER_SURFACED`
4. `INVOICE_GENERATED`
5. `OFFER_APPLIED_LOGGED`

`ITEM_UNAVAILABLE.creative_promo_source` may be:

- `llm` when model call succeeds
- `stub_fallback` when free-tier Gemma/Gemini returns quota/rate-limit style failures (including `429`)

## 5) Invoice + DB assertions (required)

- Invoice response contains accepted offers with `offer_id` when applicable.
- DB table `offer_applied_log` contains rows for the invoice `order_id`:
  - `order_id`
  - `offer_id`
  - `amount_saved_paise`

If no offer is eligible, `OFFER_APPLIED_LOGGED` can still exist with an empty accepted-offers list.

