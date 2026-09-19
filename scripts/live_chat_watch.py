"""Live-watch consumer chat sessions + audit_log for observation notes."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from shared.db import engine
from shared.redis_client import get_redis_client

LOG = Path(__file__).resolve().parents[1] / "CONSUMER_CHAT_LIVE_WATCH.md"
DURATION_SEC = 15 * 60
POLL = 6


async def snapshot_sessions() -> list[dict]:
    redis = get_redis_client()
    out: list[dict] = []
    async for key in redis.scan_iter(match="session:*:state", count=200):
        raw = await redis.get(key)
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


async def fetch_audits_since(since: datetime) -> list[dict]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT created_at, session_id, actor, action, detail
                    FROM audit_log
                    WHERE created_at > :since
                    ORDER BY created_at ASC
                    """
                ),
                {"since": since},
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def fmt_session(st: dict) -> str:
    items = [
        (i.get("item_name"), i.get("brand"), i.get("qty"), i.get("resolved"))
        for i in st.get("line_items") or []
    ]
    return (
        f"- status={st.get('status')} msg={repr((st.get('message') or '')[:120])}\n"
        f"  items={items}\n"
        f"  missing={st.get('missing_fields')} suggestions={len(st.get('catalog_suggestions') or [])}\n"
        f"  customer={st.get('customer_name')!r} phone={st.get('phone')!r} "
        f"address={repr((st.get('address') or '')[:60])}\n"
        f"  invoice={'yes' if st.get('invoice') else 'no'}"
    )


async def main() -> None:
    start = datetime.now(timezone.utc)
    LOG.write_text(
        (
            f"# Live consumer chat watch\n\n"
            f"Started: {start.isoformat()}\n"
            f"Polling every {POLL}s for ~{DURATION_SEC // 60} minutes.\n\n"
            f"Keep chatting in the browser — changes are appended below.\n"
        ),
        encoding="utf-8",
    )
    print("WATCH_RUNNING", flush=True)
    last_sig: dict[str, str] = {}
    last_audit_ts = start
    end = time.time() + DURATION_SEC

    while time.time() < end:
        now = datetime.now(timezone.utc)
        lines: list[str] = [f"\n## Tick {now.isoformat()}\n"]
        changed = False

        try:
            session_snapshot = await snapshot_sessions()
            audits = await fetch_audits_since(last_audit_ts)
        except Exception as exc:  # noqa: BLE001 — keep watch alive across brief Redis blips
            print(f"WATCH_POLL_ERROR {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(POLL)
            continue

        for st in session_snapshot:
            sid = st.get("session_id") or "unknown"
            sig = json.dumps(
                {
                    "status": st.get("status"),
                    "message": st.get("message"),
                    "missing": st.get("missing_fields"),
                    "items": st.get("line_items"),
                    "suggestions": st.get("catalog_suggestions"),
                    "customer_name": st.get("customer_name"),
                    "phone": st.get("phone"),
                    "address": st.get("address"),
                    "invoice": st.get("invoice"),
                },
                sort_keys=True,
                default=str,
            )
            if last_sig.get(sid) != sig:
                changed = True
                last_sig[sid] = sig
                lines.append(f"### Session `{sid}` changed\n")
                lines.append(fmt_session(st) + "\n")
                msg = (st.get("message") or "")[:80]
                print(f"CHANGE {sid} status={st.get('status')} msg={msg!r}", flush=True)

        events = audits
        for event in events:
            changed = True
            ts = event["created_at"]
            if ts > last_audit_ts:
                last_audit_ts = ts
            detail = event["detail"]
            ds = (
                json.dumps(detail, ensure_ascii=True)[:300]
                if not isinstance(detail, str)
                else detail[:300]
            )
            lines.append(
                f"- AUDIT {event['created_at']} | {event['session_id']} | "
                f"**{event['action']}** | `{ds}`\n"
            )
            print(f"AUDIT {event['action']} {event['session_id']}", flush=True)

        if changed:
            with LOG.open("a", encoding="utf-8") as handle:
                handle.writelines(lines)

        await asyncio.sleep(POLL)

    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\nWatch ended {datetime.now(timezone.utc).isoformat()}\n")
    print("WATCH_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
