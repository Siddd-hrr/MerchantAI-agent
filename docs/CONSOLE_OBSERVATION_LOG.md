# Console observation log — 2026-08-31

## Stack ready for manual test

All ports up:

| Service | Port | Status |
|---------|------|--------|
| Unified console (only frontend) | 5173 | UP |
| Gateway | 8000 | UP |
| Async worker | 8001 | UP |
| Merchant agent | 8002 | UP |
| Merchant admin | 8003 | UP |
| Offer engine | 8004 | UP |
| Reservation worker | 8005 | UP |
| Postgres | 5433 | healthy |
| Redis | 16379 | healthy |

Live session/audit watcher: `scripts.live_chat_watch` → `CONSUMER_CHAT_LIVE_WATCH.md`

**URL:** http://127.0.0.1:5173/

Go ahead and test Chat / Catalog / Offers — observations append below and in the live watch file.

---

## Observation — catalog + warning overlap (fixed)

**Why it felt overlapping**
1. Agent reply already listed catalog options *and* a warning that again asked for “Exact product name + brand”.
2. Chat UI also re-rendered `catalog_suggestions` + `missing_fields` under the same bubble → triple redundancy / clutter.

**Fix**
- When catalog options are shown, drop the “Exact product name + brand” bullet from the warning.
- Shorter warning header + cleaner catalog list.
- Chat UI shows reply text only (no duplicate suggestion/missing blocks); `pre-wrap` for readable line breaks.

## Observation — “no milk required” (session `8b683d16-…`)

User: `FreshFarm Beans 4 , no milk required`

What happened:
- LLM **did** extract FreshFarm Beans ×4 (resolved) — so **yes, Gemma is used as the extraction brain**
- Sticky session still kept `milk` because parse prompt said “do not drop” known items and there was **no cancel path**
- Visible reply is mostly **templates** (`ask_for_fields`), not free-form LLM chat — so it felt “not understanding”

Fix shipped: cancel phrases (`no milk required`, remove/don't want/…) drop matching line items (LLM `remove_item_names` + rule backup).

Retest with a **new** message on that session or a fresh chat: e.g. again `FreshFarm Beans 4, no milk required` — milk should disappear; only delivery/name/phone remain.


