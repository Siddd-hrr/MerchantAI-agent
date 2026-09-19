"""Multi-source concurrent Gateway sessions with per-turn timing.

Usage:
  python scripts/multi_session_scale_probe.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

GATEWAY = "http://127.0.0.1:8000/v1/converse"
OUT = Path(__file__).resolve().parents[1] / "MULTI_SESSION_SCALE_REPORT.md"


def _mandate(*, valid: bool = True) -> str:
    payload = {
        "issuer": "issuer-a" if valid else "evil-issuer",
        "subject": "scale-probe",
        "issued_at": int(datetime.now(timezone.utc).timestamp()),
        "signature": f"sig-{uuid.uuid4().hex}" if valid else "",
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


@dataclass
class TurnResult:
    turn: int
    message: str
    http_status: int
    latency_ms: float
    status: str | None = None
    session_id: str | None = None
    error_code: str | None = None
    reply_preview: str = ""
    suggestions: int = 0
    missing_fields: int = 0
    ok: bool = False


@dataclass
class SessionResult:
    session_label: str
    consumer_agent_id: str
    source: str
    expected: str
    started_at: str
    ended_at: str = ""
    total_ms: float = 0.0
    success: bool = False
    notes: str = ""
    turns: list[TurnResult] = field(default_factory=list)
    final_session_id: str | None = None


async def _one_turn(
    client: httpx.AsyncClient,
    *,
    consumer_agent_id: str,
    session_id: str | None,
    message: str,
    valid_mandate: bool,
    turn: int,
) -> TurnResult:
    body = {
        "consumer_agent_id": consumer_agent_id,
        "session_id": session_id,
        "message": message,
        "human_sign_mandate": _mandate(valid=valid_mandate),
    }
    t0 = time.perf_counter()
    try:
        resp = await client.post(GATEWAY, json=body)
        latency = (time.perf_counter() - t0) * 1000
        data = resp.json()
        reply = (data.get("reply") or "").replace("\n", " ")
        err = data.get("error") or {}
        error_code = err.get("code") if err else None
        preview = reply[:180]
        if error_code in {"AGENT_ERROR", "AGENT_UNAVAILABLE", "WORKER_UNAVAILABLE"} and err.get("message"):
            preview = f"{error_code}: {str(err.get('message'))[:160]}"
        return TurnResult(
            turn=turn,
            message=message,
            http_status=resp.status_code,
            latency_ms=round(latency, 1),
            status=data.get("status"),
            session_id=data.get("session_id"),
            error_code=error_code,
            reply_preview=preview,
            suggestions=len(data.get("catalog_suggestions") or []),
            missing_fields=len(data.get("missing_fields") or []),
            ok=resp.status_code == 200,
        )
    except Exception as exc:  # noqa: BLE001
        latency = (time.perf_counter() - t0) * 1000
        return TurnResult(
            turn=turn,
            message=message,
            http_status=0,
            latency_ms=round(latency, 1),
            error_code="EXCEPTION",
            reply_preview=str(exc)[:180],
            ok=False,
        )


async def run_session(spec: dict, sem: asyncio.Semaphore | None = None) -> SessionResult:
    async def _body() -> SessionResult:
        label = spec["label"]
        consumer = spec["consumer_agent_id"]
        source = spec["source"]
        expected = spec["expected"]
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        turns: list[TurnResult] = []
        session_id: str | None = None

        async with httpx.AsyncClient(timeout=120.0) as client:
            for idx, turn_spec in enumerate(spec["turns"], start=1):
                result = await _one_turn(
                    client,
                    consumer_agent_id=consumer,
                    session_id=session_id,
                    message=turn_spec["message"],
                    valid_mandate=turn_spec.get("valid_mandate", True),
                    turn=idx,
                )
                turns.append(result)
                if result.session_id:
                    session_id = result.session_id

        total_ms = (time.perf_counter() - t0) * 1000
        success = _evaluate(spec, turns)
        notes = _notes(spec, turns)

        return SessionResult(
            session_label=label,
            consumer_agent_id=consumer,
            source=source,
            expected=expected,
            started_at=started,
            ended_at=datetime.now(timezone.utc).isoformat(),
            total_ms=round(total_ms, 1),
            success=success,
            notes=notes,
            turns=turns,
            final_session_id=session_id,
        )

    if sem is None:
        return await _body()
    async with sem:
        return await _body()


def _evaluate(spec: dict, turns: list[TurnResult]) -> bool:
    if not turns or not all(t.ok for t in turns):
        return False
    kind = spec["kind"]
    last = turns[-1]
    if kind == "invalid_mandate":
        return last.status == "FAILED" and last.error_code == "MANDATE_INVALID"
    if kind == "order_start":
        return last.status in {"AWAITING_FIELDS", "VALIDATED", "INVOICED"} and last.error_code is None
    if kind == "off_topic":
        return last.error_code is None and last.status in {"AWAITING_FIELDS", "FAILED", "VALIDATED", "INVOICED"}
    if kind == "multi_turn":
        ids = {t.session_id for t in turns if t.session_id}
        return len(ids) == 1 and last.error_code is None
    return last.error_code is None


def _notes(spec: dict, turns: list[TurnResult]) -> str:
    if not turns:
        return "No turns executed"
    kind = spec["kind"]
    last = turns[-1]
    if kind == "invalid_mandate":
        return f"Mandate gate returned {last.error_code} / {last.status}"
    if kind == "order_start":
        return f"suggestions={last.suggestions}, missing_fields={last.missing_fields}"
    if kind == "multi_turn":
        return f"session continuity ids={len({t.session_id for t in turns if t.session_id})}"
    return last.reply_preview[:120]


def _health_snapshot() -> dict[str, str]:
    out: dict[str, str] = {}
    for port, name in [(8000, "gateway"), (8001, "async_worker"), (8002, "merchant_agent"), (8003, "merchant_admin")]:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=3.0)
            out[name] = f"{r.status_code} {r.text.strip()}"
        except Exception as exc:  # noqa: BLE001
            out[name] = f"DOWN ({exc})"
    return out


def _render_report(sessions: list[SessionResult], wall_ms: float, health: dict[str, str]) -> str:
    ok = sum(1 for s in sessions if s.success)
    latencies = [t.latency_ms for s in sessions for t in s.turns if t.ok]
    lines: list[str] = []
    lines.append("# Multi-Session Gateway Scale Probe — Human Review Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{datetime.now(timezone.utc).isoformat()}`")
    lines.append(f"- Gateway endpoint: `{GATEWAY}`")
    lines.append(f"- Concurrent sessions launched: **{len(sessions)}**")
    lines.append(f"- Sessions passed: **{ok}/{len(sessions)}**")
    lines.append(f"- Wall-clock for full concurrent batch: **{wall_ms:.1f} ms**")
    if latencies:
        lines.append(
            f"- Per-turn latency (ok turns): min **{min(latencies):.1f} ms**, "
            f"median **{statistics.median(latencies):.1f} ms**, "
            f"max **{max(latencies):.1f} ms**, "
            f"avg **{statistics.mean(latencies):.1f} ms**"
        )
    lines.append("")
    lines.append("## Deployment topology observed")
    lines.append("")
    lines.append("| Service | Health |")
    lines.append("|---|---|")
    for k, v in health.items():
        lines.append(f"| `{k}` | `{v}` |")
    lines.append("")
    lines.append(
        "**Scaling note:** At probe time, Postgres/Redis were in Docker, while "
        "`gateway` / `async_worker` / `merchant_agent` / `merchant_admin` were "
        "single local Uvicorn processes (1 replica each). So this run validates "
        "**concurrent multi-session correctness through the Gateway** and Redis "
        "session isolation under load. It does **not** prove nginx round-robin "
        "across N Docker replicas (that requires `docker compose up --scale "
        "async_worker=3 --scale merchant_agent=2`)."
    )
    lines.append("")
    lines.append("## Session matrix")
    lines.append("")
    lines.append("| Session | Source | Consumer ID | Expected | Success | Total ms | Final status | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in sessions:
        final_status = s.turns[-1].status if s.turns else "-"
        lines.append(
            f"| {s.session_label} | {s.source} | `{s.consumer_agent_id}` | {s.expected} | "
            f"{'PASS' if s.success else 'FAIL'} | {s.total_ms:.1f} | `{final_status}` | {s.notes} |"
        )
    lines.append("")
    lines.append("## Per-session turn timings")
    lines.append("")
    for s in sessions:
        lines.append(f"### {s.session_label}")
        lines.append("")
        lines.append(f"- Source: **{s.source}**")
        lines.append(f"- Consumer: `{s.consumer_agent_id}`")
        lines.append(f"- Session id: `{s.final_session_id}`")
        lines.append(f"- Window: `{s.started_at}` → `{s.ended_at}`")
        lines.append(f"- Total: **{s.total_ms:.1f} ms** — {'PASS' if s.success else 'FAIL'}")
        lines.append("")
        lines.append("| Turn | Latency ms | HTTP | Status | Error | Suggestions | Missing | Message | Reply preview |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for t in s.turns:
            msg = t.message.replace("|", "/")[:40]
            preview = t.reply_preview.replace("|", "/")[:70]
            lines.append(
                f"| {t.turn} | {t.latency_ms:.1f} | {t.http_status} | `{t.status}` | "
                f"`{t.error_code}` | {t.suggestions} | {t.missing_fields} | {msg} | {preview} |"
            )
        lines.append("")

    # Isolation check
    sid_map = {s.session_label: s.final_session_id for s in sessions if s.final_session_id}
    unique_ids = set(sid_map.values())
    lines.append("## Session isolation check")
    lines.append("")
    lines.append(f"- Distinct Redis/app session IDs observed: **{len(unique_ids)}** across labeled sessions with IDs.")
    if len(unique_ids) >= max(1, len(sid_map) - 1):
        lines.append("- Verdict: **PASS** — sessions did not collapse onto one shared id.")
    else:
        lines.append("- Verdict: **FAIL** — unexpected session-id reuse across consumers.")
    lines.append("")
    lines.append("## Human review checklist")
    lines.append("")
    lines.append("- [ ] Invalid-mandate sessions fail at the worker gate (no agent inventory leakage).")
    lines.append("- [ ] Order-start sessions return catalog suggestions and missing-field warnings.")
    lines.append("- [ ] Multi-turn sessions keep the same `session_id`.")
    lines.append("- [ ] Concurrent batch wall-clock is less than sum of serial session totals (overlap).")
    lines.append("- [ ] Latencies acceptable for demo (< ~30s/turn on free-tier Gemini).")
    lines.append("- [ ] For true horizontal scaling proof: re-run after Docker `--scale` with nginx DNS upstream.")
    lines.append("")
    serial_sum = sum(s.total_ms for s in sessions)
    lines.append("## Concurrency evidence")
    lines.append("")
    lines.append(f"- Sum of per-session totals (if serial): **{serial_sum:.1f} ms**")
    lines.append(f"- Actual concurrent wall-clock: **{wall_ms:.1f} ms**")
    if wall_ms < serial_sum * 0.85:
        lines.append("- Verdict: **PASS** — requests overlapped (Gateway accepted multi-source load).")
    else:
        lines.append("- Verdict: **WEAK** — little overlap; possible queueing or single-thread bottleneck.")
    lines.append("")
    lines.append("## Raw JSON")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps([asdict(s) for s in sessions], indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    health = _health_snapshot()
    specs = [
        {
            "label": "S1-WebUI-order",
            "source": "Simulated Web UI",
            "consumer_agent_id": "web-ui-consumer-001",
            "expected": "AWAITING_FIELDS + suggestions",
            "kind": "order_start",
            "turns": [{"message": "I wish to order beans", "valid_mandate": True}],
        },
        {
            "label": "S2-Mobile-order",
            "source": "Simulated Mobile Agent",
            "consumer_agent_id": "mobile-agent-002",
            "expected": "AWAITING_FIELDS + suggestions",
            "kind": "order_start",
            "turns": [{"message": "Need 2 liters milk Amul", "valid_mandate": True}],
        },
        {
            "label": "S3-PartnerAPI-order",
            "source": "Simulated Partner API",
            "consumer_agent_id": "partner-api-003",
            "expected": "AWAITING_FIELDS",
            "kind": "order_start",
            "turns": [{"message": "Order rice and sugar please", "valid_mandate": True}],
        },
        {
            "label": "S4-Invalid-mandate",
            "source": "Attack / bad client",
            "consumer_agent_id": "bad-client-004",
            "expected": "FAILED MANDATE_INVALID",
            "kind": "invalid_mandate",
            "turns": [{"message": "I want beans", "valid_mandate": False}],
        },
        {
            "label": "S5-Off-topic",
            "source": "Noisy consumer",
            "consumer_agent_id": "noisy-agent-005",
            "expected": "Redirect / no crash",
            "kind": "off_topic",
            "turns": [{"message": "Tell me a joke about cricket", "valid_mandate": True}],
        },
        {
            "label": "S6-Multi-turn",
            "source": "Persistent shopper",
            "consumer_agent_id": "shopper-006",
            "expected": "Same session_id across turns",
            "kind": "multi_turn",
            "turns": [
                {"message": "I want beans", "valid_mandate": True},
                {
                    "message": "Brand FreshFarm, quantity 2 kg, name Rahul, phone 9876543210, address Pune FC Road",
                    "valid_mandate": True,
                },
            ],
        },
    ]

    t0 = time.perf_counter()
    # Cap concurrent LLM-heavy sessions to reduce free-tier Gemini contention.
    sem = asyncio.Semaphore(2)
    sessions = await asyncio.gather(*(run_session(spec, sem) for spec in specs))
    wall_ms = (time.perf_counter() - t0) * 1000
    report = _render_report(list(sessions), wall_ms, health)
    OUT.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"passed={sum(1 for s in sessions if s.success)}/{len(sessions)} wall_ms={wall_ms:.1f}")


if __name__ == "__main__":
    asyncio.run(main())
