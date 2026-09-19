# EDGE_CASE_TEST_REPORT

## Automated Test Summary

- Command run: `.\.venv\Scripts\python -m pytest -q`
- Latest result: `21 passed in 1.80s`
- Collection/runtime blocker fixed before final run:
  - `tests/test_merchant_agent_flow.py` was importing a non-existent `MANDATE_INVALID_MESSAGE`; updated to use `MANDATE_INVALID_ERROR["error"]["message"]`.

## Edge-Case Matrix Status

- Mandate invalid/replay: **PASS**
  - Invalid path covered in `tests/test_async_worker.py` and gateway-flow validation in `tests/test_merchant_agent_flow.py`.
  - Replay detection covered in `tests/test_async_worker.py::test_replay_mandate_fails`.
- Missing fields template: **PASS**
  - Covered by `tests/test_merchant_agent_flow.py::test_missing_fields_warning_is_verbatim` and node-level prompt verification.
- OOS alternatives: **PASS**
  - Covered by `tests/test_merchant_agent_nodes.py::test_oos_alternative_warning_and_audit`.
- Off-topic guard: **PASS**
  - Covered by `tests/test_merchant_agent_nodes.py::test_off_topic_guard_short_circuits`.
- Discount zero-reads: **PASS**
  - Covered by `tests/test_merchant_agent_flow.py::test_discount_model_has_no_runtime_readers`.
- Gateway rate limit: **PASS**
  - Covered by `tests/test_gateway.py::test_gateway_rate_limit_returns_failed`.
- Catalog seed OOS SKUs: **PASS**
  - Fixture-level verification covered by `tests/test_merchant_agent_flow.py::test_sample_catalog_supports_oos_and_alternatives`.

## §11 Definition of Done Checklist

- ✅ Unit tests execute cleanly in local venv (`21 passed`)
- ✅ Mandate invalid/replay behavior covered by automated tests
- ✅ Missing-fields, off-topic, OOS alternatives covered by automated tests
- ✅ Gateway rate-limit handling covered by automated tests
- ✅ Discount table remains unused at runtime (explicit guard test)
- ✅ Docker daemon available on this machine (`docker info` succeeded)
- ❌ Full Docker compose stack not validated in this pass (`docker compose up --build -d` not executed here)
- ❌ Live Gemini end-to-end not verified (pending user-provided `.env` `GOOGLE_API_KEY` validation path)
- ✅ Frontend delivered under `frontend/`
- ✅ Postgres host port remapped to **5433**; Redis host port remapped to **16379** (local 5432/6379/6380 were occupied)
- ✅ Alembic migration applied; catalog seed ran (`15` items upserted)
- ⚠️ Update your local `.env` to match `.env.example` ports (`DATABASE_URL` → `:5433`, `REDIS_URL` → `:16379`) and set `GOOGLE_API_KEY`

## Notes

- No real API keys were written into repository files.
- `Master-Build Prompt` directory was not modified or removed.

## Track A2: stockout E2E live-ready checklist

Goal: validate **OOS item + cross-sell preference** flow end-to-end, ensuring the agent prioritizes cross-sell alternatives, applies offers, and writes invoice/audit artifacts.

### Preconditions

- [ ] Services up: `gateway` (`8000`), `consumer_chat_worker` (`8001`), `merchant_agent` (`8002`), `merchant_admin` (`8003`), `offer_engine` (`8004`), `reservation_worker` (`8005`), Postgres, Redis.
- [ ] Seed data applied: `scripts.seed_catalog`, `scripts.seed_offers`, `scripts.seed_memory`.
- [ ] Cross-sell preference exists for the chosen OOS source SKU and points to in-stock targets.
- [ ] Runtime note: free-tier Gemma/Gemini may hit quota (`429`); creative promo fallback stub is acceptable for this test.

### Scenario steps

1. Start a fresh `session_id` and send a request for an SKU configured to fail availability (requested qty > available qty).
2. Verify response is stockout-guided and includes alternatives from cross-sell preference first (not only same-category fallback).
3. Check audit stream includes:
   - `CROSS_SELL_SURFACED`
   - `ITEM_UNAVAILABLE` with `alternatives_source="cross_sell_preference"`
   - `ITEM_UNAVAILABLE` with `creative_promo_source` (`llm` or `stub_fallback`)
4. Continue same session: accept one surfaced alternative and provide customer fields (name, phone, address) so status can move to invoice path.
5. Verify offer path during resolution and invoicing:
   - `OFFER_SURFACED` appears before invoice
   - invoice payload includes `accepted_offers[*].offer_id`
6. Complete invoice and verify audit rows:
   - `INVOICE_GENERATED` present with `order_id`
   - `OFFER_APPLIED_LOGGED` present with accepted offers (can be empty if no eligible discount)
7. Query DB and confirm persisted offer logs for accepted discounts:
   - `offer_applied_log.order_id`
   - `offer_applied_log.offer_id`
   - `offer_applied_log.amount_saved_paise`

### Pass criteria

- [ ] Stockout turn prefers cross-sell targets when configured.
- [ ] Creative promo fallback does not block flow on LLM `429`.
- [ ] Invoice generated in same session after alternative acceptance.
- [ ] Offer attribution visible in both invoice response and `offer_applied_log`.
