# Multi-Session Gateway Scale Probe — Human Review Report

## Executive summary (for human review)

**Goal:** Contact Merchant AI Agent through Gateway from multiple simulated sources at once, measure timings, and judge whether multi-session / scaling behavior works.

### Topology under test
- Postgres + Redis: Docker (healthy)
- Gateway / async_worker / merchant_agent / merchant_admin: **single local Uvicorn replicas** (not Docker `--scale`)
- Model: `gemini-3.6-flash` (free tier)

### Verdict
| Capability | Result |
|---|---|
| Gateway accepts multi-source traffic | **PASS** — 6 concurrent/staggered consumers |
| Session isolation (distinct `session_id`s) | **PASS** — 6 distinct IDs |
| Mandate gate under load | **PASS** — `MANDATE_INVALID` in ~0.5–4s, no agent needed |
| Happy-path order under light concurrency | **PASS** (earlier burst run: WebUI order + off-topic worked) |
| Heavy concurrent LLM turns | **FAIL / degraded** — Gemini `429 RESOURCE_EXHAUSTED` |
| True horizontal scale (nginx + N replicas) | **NOT PROVEN** — only 1 worker + 1 agent process running |

### Root cause of failed LLM sessions
Concurrent graph turns each call Gemini multiple times. Free-tier quota returns:

`AGENT_ERROR: ... gemini-3.6-flash ... 429 RESOURCE_EXHAUSTED`

This is **model rate-limit**, not Gateway routing failure. Mandate-only path stays fast and correct.

### Timing snapshot (latest staggered run, concurrency cap = 2)
- Sessions: **1/6 PASS** (only invalid-mandate reliably passed after quota exhaustion from prior runs)
- Wall-clock batch: **~144 s**
- Invalid mandate: **~776 ms**
- Failed LLM turns: **~35–37 s** each (wait/retry then 429)

### Earlier full-burst run (better LLM success before quota burn)
- **3/6 PASS** (WebUI order, invalid mandate, off-topic)
- Wall-clock **~78 s** vs serial sum **~183 s** → concurrency overlap **PASS**
- Failures then were mostly timeout/`AGENT_ERROR` under Gemini contention

### Fixes applied during this investigation
- Raised Gateway→Worker and Worker→Agent HTTP timeouts from 15–20s to **120s**
- Added probe script: `scripts/multi_session_scale_probe.py`

### Recommendations for reviewers
1. Re-test multi-source LLM after Gemini quota resets (or use paid tier / lower concurrency).
2. To prove **horizontal scaling**: `docker compose up --scale async_worker=3 --scale merchant_agent=2` + nginx DNS upstream.
3. Add LLM retry/backoff + request queue so one burst does not 429 all sessions.

---

- Generated (UTC): `2026-08-29T11:44:21.677548+00:00`
- Gateway endpoint: `http://127.0.0.1:8000/v1/converse`
- Concurrent sessions launched: **6**
- Sessions passed: **1/6**
- Wall-clock for full concurrent batch: **143944.5 ms**
- Per-turn latency (ok turns): min **550.0 ms**, median **35909.4 ms**, max **36709.9 ms**, avg **30940.8 ms**

## Deployment topology observed

| Service | Health |
|---|---|
| `gateway` | `200 {"status":"ok","service":"gateway"}` |
| `async_worker` | `200 {"status":"ok","service":"async_worker"}` |
| `merchant_agent` | `200 {"status":"ok","service":"merchant_agent"}` |
| `merchant_admin` | `200 {"status":"ok","service":"merchant_admin"}` |

**Scaling note:** At probe time, Postgres/Redis were in Docker, while `gateway` / `async_worker` / `merchant_agent` / `merchant_admin` were single local Uvicorn processes (1 replica each). So this run validates **concurrent multi-session correctness through the Gateway** and Redis session isolation under load. It does **not** prove nginx round-robin across N Docker replicas (that requires `docker compose up --scale async_worker=3 --scale merchant_agent=2`).

## Session matrix

| Session | Source | Consumer ID | Expected | Success | Total ms | Final status | Notes |
|---|---|---|---|---|---|---|---|
| S1-WebUI-order | Simulated Web UI | `web-ui-consumer-001` | AWAITING_FIELDS + suggestions | FAIL | 37039.1 | `FAILED` | suggestions=0, missing_fields=0 |
| S2-Mobile-order | Simulated Mobile Agent | `mobile-agent-002` | AWAITING_FIELDS + suggestions | FAIL | 36196.2 | `FAILED` | suggestions=0, missing_fields=0 |
| S3-PartnerAPI-order | Simulated Partner API | `partner-api-003` | AWAITING_FIELDS | FAIL | 35735.8 | `FAILED` | suggestions=0, missing_fields=0 |
| S4-Invalid-mandate | Attack / bad client | `bad-client-004` | FAILED MANDATE_INVALID | PASS | 776.0 | `FAILED` | Mandate gate returned MANDATE_INVALID / FAILED |
| S5-Off-topic | Noisy consumer | `noisy-agent-005` | Redirect / no crash | FAIL | 36804.5 | `FAILED` | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429 |
| S6-Multi-turn | Persistent shopper | `shopper-006` | Same session_id across turns | FAIL | 71676.1 | `FAILED` | session continuity ids=1 |

## Per-session turn timings

### S1-WebUI-order

- Source: **Simulated Web UI**
- Consumer: `web-ui-consumer-001`
- Session id: `ef11709f-fd87-4984-9516-473bf367ddfe`
- Window: `2026-08-29T11:41:57.731190+00:00` → `2026-08-29T11:42:34.767422+00:00`
- Total: **37039.1 ms** — FAIL

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 36709.9 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | I wish to order beans | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |

### S2-Mobile-order

- Source: **Simulated Mobile Agent**
- Consumer: `mobile-agent-002`
- Session id: `7ce7c247-693e-4071-8e8b-ff0e5f013c4c`
- Window: `2026-08-29T11:41:58.068681+00:00` → `2026-08-29T11:42:34.265754+00:00`
- Total: **36196.2 ms** — FAIL

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 35909.4 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | Need 2 liters milk Amul | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |

### S3-PartnerAPI-order

- Source: **Simulated Partner API**
- Consumer: `partner-api-003`
- Session id: `31201108-f5b1-4eb8-a48f-bbeba7be7f1d`
- Window: `2026-08-29T11:42:34.265754+00:00` → `2026-08-29T11:43:10.001936+00:00`
- Total: **35735.8 ms** — FAIL

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 35470.1 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | Order rice and sugar please | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |

### S4-Invalid-mandate

- Source: **Attack / bad client**
- Consumer: `bad-client-004`
- Session id: `c6541ab3-9da2-4d65-bd21-a1f66be74bbe`
- Window: `2026-08-29T11:42:34.767422+00:00` → `2026-08-29T11:42:35.545633+00:00`
- Total: **776.0 ms** — PASS

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 550.0 | 200 | `FAILED` | `MANDATE_INVALID` | 0 | 0 | I want beans | Please include a cryptographic signature issued by a trusted issuer to |

### S5-Off-topic

- Source: **Noisy consumer**
- Consumer: `noisy-agent-005`
- Session id: `0e5b9875-0b5c-4c71-ad24-ce2c61167a19`
- Window: `2026-08-29T11:42:35.545633+00:00` → `2026-08-29T11:43:12.353300+00:00`
- Total: **36804.5 ms** — FAIL

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 36547.7 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | Tell me a joke about cricket | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |

### S6-Multi-turn

- Source: **Persistent shopper**
- Consumer: `shopper-006`
- Session id: `724f7be4-bcb5-48ae-a94f-a6a7d1886b27`
- Window: `2026-08-29T11:43:10.001936+00:00` → `2026-08-29T11:44:21.677548+00:00`
- Total: **71676.1 ms** — FAIL

| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |
|---|---|---|---|---|---|---|---|---|
| 1 | 36097.5 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | I want beans | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |
| 2 | 35301.2 | 200 | `FAILED` | `AGENT_ERROR` | 0 | 0 | Brand FreshFarm, quantity 2 kg, name Rah | AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTE |

## Session isolation check

- Distinct Redis/app session IDs observed: **6** across labeled sessions with IDs.
- Verdict: **PASS** — sessions did not collapse onto one shared id.

## Human review checklist

- [ ] Invalid-mandate sessions fail at the worker gate (no agent inventory leakage).
- [ ] Order-start sessions return catalog suggestions and missing-field warnings.
- [ ] Multi-turn sessions keep the same `session_id`.
- [ ] Concurrent batch wall-clock is less than sum of serial session totals (overlap).
- [ ] Latencies acceptable for demo (< ~30s/turn on free-tier Gemini).
- [ ] For true horizontal scaling proof: re-run after Docker `--scale` with nginx DNS upstream.

## Concurrency evidence

- Sum of per-session totals (if serial): **218227.7 ms**
- Actual concurrent wall-clock: **143944.5 ms**
- Verdict: **PASS** — requests overlapped (Gateway accepted multi-source load).

## Raw JSON

```json
[
  {
    "session_label": "S1-WebUI-order",
    "consumer_agent_id": "web-ui-consumer-001",
    "source": "Simulated Web UI",
    "expected": "AWAITING_FIELDS + suggestions",
    "started_at": "2026-08-29T11:41:57.731190+00:00",
    "ended_at": "2026-08-29T11:42:34.767422+00:00",
    "total_ms": 37039.1,
    "success": false,
    "notes": "suggestions=0, missing_fields=0",
    "turns": [
      {
        "turn": 1,
        "message": "I wish to order beans",
        "http_status": 200,
        "latency_ms": 36709.9,
        "status": "FAILED",
        "session_id": "ef11709f-fd87-4984-9516-473bf367ddfe",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "ef11709f-fd87-4984-9516-473bf367ddfe"
  },
  {
    "session_label": "S2-Mobile-order",
    "consumer_agent_id": "mobile-agent-002",
    "source": "Simulated Mobile Agent",
    "expected": "AWAITING_FIELDS + suggestions",
    "started_at": "2026-08-29T11:41:58.068681+00:00",
    "ended_at": "2026-08-29T11:42:34.265754+00:00",
    "total_ms": 36196.2,
    "success": false,
    "notes": "suggestions=0, missing_fields=0",
    "turns": [
      {
        "turn": 1,
        "message": "Need 2 liters milk Amul",
        "http_status": 200,
        "latency_ms": 35909.4,
        "status": "FAILED",
        "session_id": "7ce7c247-693e-4071-8e8b-ff0e5f013c4c",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "7ce7c247-693e-4071-8e8b-ff0e5f013c4c"
  },
  {
    "session_label": "S3-PartnerAPI-order",
    "consumer_agent_id": "partner-api-003",
    "source": "Simulated Partner API",
    "expected": "AWAITING_FIELDS",
    "started_at": "2026-08-29T11:42:34.265754+00:00",
    "ended_at": "2026-08-29T11:43:10.001936+00:00",
    "total_ms": 35735.8,
    "success": false,
    "notes": "suggestions=0, missing_fields=0",
    "turns": [
      {
        "turn": 1,
        "message": "Order rice and sugar please",
        "http_status": 200,
        "latency_ms": 35470.1,
        "status": "FAILED",
        "session_id": "31201108-f5b1-4eb8-a48f-bbeba7be7f1d",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "31201108-f5b1-4eb8-a48f-bbeba7be7f1d"
  },
  {
    "session_label": "S4-Invalid-mandate",
    "consumer_agent_id": "bad-client-004",
    "source": "Attack / bad client",
    "expected": "FAILED MANDATE_INVALID",
    "started_at": "2026-08-29T11:42:34.767422+00:00",
    "ended_at": "2026-08-29T11:42:35.545633+00:00",
    "total_ms": 776.0,
    "success": true,
    "notes": "Mandate gate returned MANDATE_INVALID / FAILED",
    "turns": [
      {
        "turn": 1,
        "message": "I want beans",
        "http_status": 200,
        "latency_ms": 550.0,
        "status": "FAILED",
        "session_id": "c6541ab3-9da2-4d65-bd21-a1f66be74bbe",
        "error_code": "MANDATE_INVALID",
        "reply_preview": "Please include a cryptographic signature issued by a trusted issuer to establish contact with the Merchant-AI agent.",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "c6541ab3-9da2-4d65-bd21-a1f66be74bbe"
  },
  {
    "session_label": "S5-Off-topic",
    "consumer_agent_id": "noisy-agent-005",
    "source": "Noisy consumer",
    "expected": "Redirect / no crash",
    "started_at": "2026-08-29T11:42:35.545633+00:00",
    "ended_at": "2026-08-29T11:43:12.353300+00:00",
    "total_ms": 36804.5,
    "success": false,
    "notes": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429",
    "turns": [
      {
        "turn": 1,
        "message": "Tell me a joke about cricket",
        "http_status": 200,
        "latency_ms": 36547.7,
        "status": "FAILED",
        "session_id": "0e5b9875-0b5c-4c71-ad24-ce2c61167a19",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "0e5b9875-0b5c-4c71-ad24-ce2c61167a19"
  },
  {
    "session_label": "S6-Multi-turn",
    "consumer_agent_id": "shopper-006",
    "source": "Persistent shopper",
    "expected": "Same session_id across turns",
    "started_at": "2026-08-29T11:43:10.001936+00:00",
    "ended_at": "2026-08-29T11:44:21.677548+00:00",
    "total_ms": 71676.1,
    "success": false,
    "notes": "session continuity ids=1",
    "turns": [
      {
        "turn": 1,
        "message": "I want beans",
        "http_status": 200,
        "latency_ms": 36097.5,
        "status": "FAILED",
        "session_id": "724f7be4-bcb5-48ae-a94f-a6a7d1886b27",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      },
      {
        "turn": 2,
        "message": "Brand FreshFarm, quantity 2 kg, name Rahul, phone 9876543210, address Pune FC Road",
        "http_status": 200,
        "latency_ms": 35301.2,
        "status": "FAILED",
        "session_id": "724f7be4-bcb5-48ae-a94f-a6a7d1886b27",
        "error_code": "AGENT_ERROR",
        "reply_preview": "AGENT_ERROR: Error calling model 'gemini-3.6-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please",
        "suggestions": 0,
        "missing_fields": 0,
        "ok": true
      }
    ],
    "final_session_id": "724f7be4-bcb5-48ae-a94f-a6a7d1886b27"
  }
]
```
