# Phase 3 Test Review (Simple English)

**Date:** 9 September 2026 (refreshed after remaster hardening)  
**Project:** Merchant-AI-Agent  
**What this file is:** a plain-English report of Phase 3 checks — what works, what we proved, and what still needs a full chat demo.

---

## Quick scoreboard

| Area | Result |
|------|--------|
| Phase 3 edge + auth + payment + dispatch (this refresh) | **34 passed**, 1 skipped (Postgres race — Docker was down) |
| Hardenings A2–A4 | **Done** (fail-closed issuers/crypto, reservation contract, payment envelope/test-mode) |
| DoD 6 Postgres race pytest | **Present** at `tests/test_reservation_postgres_race.py` (`@pytest.mark.integration`) |
| Live API smoke (`scripts/phase3_live_verification.py`) | Re-run when Docker Desktop is up |
| Phase 4 webhook capture path | **Scaffolded** (see below) — not part of Phase 3 DoD |

**Bottom line:** Phase 3 remaster gaps A2–A5 are closed in code/tests. Live Postgres race needs Docker running once to flip the skip to a pass.

---

## Checklist from the Phase 3 master prompt

| # | Requirement (simple) | Status | How we checked |
|---|----------------------|--------|----------------|
| 1 | Shop signup with Razorpay keys + ≥1 trusted issuer, login JWT | **PASS** | Unit + profile wipe of issuers rejected (422) |
| 2 | Razorpay secret encrypted, never in API answers | **PASS** | Fernet; crypto requires `CREDENTIAL_ENCRYPTION_KEY` outside tests |
| 3 | Mandate uses shop issuer list (fail-closed without fallback) | **PASS** | `ALLOW_GLOBAL_TRUSTED_ISSUERS_FALLBACK=false` default |
| 4 | Good order → invoice + payment link | **PASS** | LangGraph dispatch/resolve unit tests |
| 5 | Reservation fails + payment ok → cancel link | **PASS** | + `ORPHANED_PAYMENT_LINK_RISK` if cancel fails |
| 6 | Last unit race → only one winner | **PASS (unit)** / **integration pytest ready** | Fake atomic unit + real SQL race when Postgres up |
| 7 | Unpaid hold expires → stock returns + audit | **PASS** | `RESERVATION_EXPIRED_ROLLED_BACK` asserted |
| 8 | Invoice Redis TTL ~480s | **PASS** | Unit TTL assert |
| 9 | Outcomes write audit actions | **PASS** | Agent path audits covered |

---

## How to re-run

```powershell
cd "C:\Users\Siddhesh Akole\Desktop\Merchant-AI Agent\Merchant-AI-Agent"
.\.venv\Scripts\python.exe -m pytest tests/test_phase3_edge_cases.py tests/test_auth_service.py tests/test_reservation_service_phase3.py tests/test_payment_service.py tests/test_invoice_dispatch.py tests/test_reservation_postgres_race.py -q
```

Integration race (needs Postgres on `DATABASE_URL`, usually `:5433`):

```powershell
.\.venv\Scripts\python.exe -m pytest -m integration -q
```

Live script (services + Docker):

```powershell
.\.venv\Scripts\python.exe -m scripts.phase3_live_verification
```

---

## Honest gaps

1. **Full browser chat E2E** with LLM was not re-run in this hardening pass.
2. **Real Razorpay sandbox** still optional locally (`RAZORPAY_MODE=fake`).
3. **Phase 4** webhook → Kafka → `invoice_audit` / `PAID` is built next; unit capture tests exist (`test_webhook_capture_e2e.py`, `test_payment_log_processor.py`).
4. Live Postgres race was **skipped** while Docker Desktop was unavailable in this session.

---

## Phase 4 status (backend, this cycle)

| Piece | Status |
|-------|--------|
| `notes.{invoice_id,session_id,merchant_id}` on payment links | Done |
| `invoice_audit` model + Alembic `20260909_0006` | Done |
| `mark_reserved_paid` | Done |
| Kafka KRaft + `aiokafka` in Compose | Done (needs Docker up) |
| `:8008` ingress → async_worker verify+enqueue → consumer | Done in code |
| JWT `GET /invoice-audit/*` | Done in code |
| Mock capture E2E unit tests | Done (34-pass batch included these) |

---

## Final review answer

**Phase 3 remaster hardening is complete in code.** Re-run `@pytest.mark.integration` and `phase3_live_verification` once Docker is healthy to stamp the live race checkbox.
