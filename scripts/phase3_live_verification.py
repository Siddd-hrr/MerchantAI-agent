"""Live Phase 3 checks against running local services (auth/reservation/payment + redis/db)."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text

from shared.db import AsyncSessionLocal
from shared.models.item import Item
from shared.models.merchant import Merchant
from shared.models.reserved_item import ReservedItem
from shared.redis_client import close_redis_client, get_redis_client


AUTH = "http://127.0.0.1:8006"
RES = "http://127.0.0.1:8005"
PAY = "http://127.0.0.1:8007"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    # Health
    for url, name in [(AUTH, "auth"), (RES, "reservation"), (PAY, "payment")]:
        try:
            r = httpx.get(f"{url}/healthz", timeout=5)
            record(f"{name} healthz", r.status_code == 200 and r.json().get("status") == "ok", r.text)
        except Exception as exc:
            record(f"{name} healthz", False, str(exc))

    # Auth login + secret leak check
    try:
        r = httpx.post(
            f"{AUTH}/auth/login",
            json={"email": "demo@acmemart.test", "password": "demo-pass-123"},
            timeout=10,
        )
        body = r.json()
        secret_leaked = "secret_demo" in r.text or "razorpay_key_secret" in body.get("profile", {})
        record("auth login JWT", r.status_code == 200 and bool(body.get("access_token")), f"status={r.status_code}")
        record("auth login no secret leak", not secret_leaked)
        token = body.get("access_token", "")
        merchant_id = body.get("profile", {}).get("id", "")
    except Exception as exc:
        record("auth login JWT", False, str(exc))
        token = ""
        merchant_id = ""

    # Profile
    if token:
        r = httpx.get(f"{AUTH}/auth/profile", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        record("auth profile", r.status_code == 200, r.json().get("email", ""))
        record("auth profile no secret leak", "secret_demo" not in r.text)

    # Redis merchant cache
    redis = get_redis_client()
    try:
        if merchant_id:
            issuers = await redis.get(f"merchant:{merchant_id}:trusted_issuers")
            creds = await redis.get(f"merchant:{merchant_id}:razorpay_creds")
            record("redis trusted_issuers key", bool(issuers), issuers or "")
            record(
                "redis razorpay_creds encrypted only",
                bool(creds) and "secret_demo" not in (creds or "") and "key_secret_encrypted" in (creds or ""),
                (creds or "")[:120],
            )
    finally:
        pass

    # Payment create + cancel
    invoice_id = str(uuid.uuid4())
    try:
        r = httpx.post(
            f"{PAY}/payment/create-link",
            json={
                "merchant_id": merchant_id,
                "invoice_id": invoice_id,
                "amount_paise": 5000,
                "customer_name": "Alex",
                "phone": "9999999999",
            },
            timeout=15,
        )
        body = r.json()
        record(
            "payment create-link",
            r.status_code == 200 and body.get("success") and body.get("payment_link_url", "").startswith("https://"),
            json.dumps(body)[:200],
        )
        record("payment create-link no secret leak", "secret_demo" not in r.text)
        record("payment create-link has expires_at", bool(body.get("expires_at")))
        link_key = await redis.get(f"payment_link:{invoice_id}")
        record("redis payment_link key set", bool(link_key), link_key or "")

        r2 = httpx.post(
            f"{PAY}/payment/cancel-link",
            json={"merchant_id": merchant_id, "invoice_id": invoice_id},
            timeout=15,
        )
        record("payment cancel-link", r2.status_code == 200 and r2.json().get("cancelled") is True)
        link_key2 = await redis.get(f"payment_link:{invoice_id}")
        record("redis payment_link removed after cancel", link_key2 is None)
    except Exception as exc:
        record("payment create-link", False, str(exc))

    # Reservation success + invoice redis TTL
    async with AsyncSessionLocal() as session:
        item = (
            await session.execute(
                select(Item).where(Item.is_active.is_(True), Item.quantity_available >= 2).limit(1)
            )
        ).scalar_one_or_none()
    if item is None:
        record("reservation submit-invoice", False, "no stocked item in DB")
    else:
        before_qty = int(item.quantity_available)
        inv_id = str(uuid.uuid4())
        invoice = {
            "order_id": inv_id,
            "session_id": str(uuid.uuid4()),
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "merchant_name": "Acme Mart",
            "customer_name": "Alex",
            "address": "Street 1",
            "phone_number": "9999999999",
            "line_items": [
                {
                    "item_id": str(item.id),
                    "name": item.name,
                    "brand": item.brand,
                    "qty": 1,
                    "unit_price_paise": int(item.price_paise),
                    "line_total_paise": int(item.price_paise),
                    "weight_per_unit": item.weight_per_unit,
                }
            ],
            "subtotal_paise": int(item.price_paise),
            "discount_paise": 0,
            "taxable_paise": int(item.price_paise),
            "cgst_paise": 0,
            "sgst_paise": 0,
            "tax_paise": 0,
            "shipping_paise": 0,
            "total_paise": int(item.price_paise),
            "accepted_offers": [],
        }
        r = httpx.post(f"{RES}/reservation/submit-invoice", json={"invoice": invoice}, timeout=30)
        body = r.json()
        record("reservation submit success", r.status_code == 200 and body.get("success") is True, json.dumps(body)[:180])

        async with AsyncSessionLocal() as session:
            fresh = (
                await session.execute(select(Item).where(Item.id == item.id))
            ).scalar_one()
            held = (
                await session.execute(
                    select(ReservedItem).where(
                        ReservedItem.invoice_id == uuid.UUID(inv_id),
                        ReservedItem.status == "HELD",
                    )
                )
            ).scalars().all()
        record("stock deducted in Postgres", int(fresh.quantity_available) == before_qty - 1, f"{before_qty} -> {fresh.quantity_available}")
        record("reserved_items HELD row created", len(held) == 1)

        inv_key = f"invoice:{inv_id}"
        inv_raw = await redis.get(inv_key)
        ttl = await redis.ttl(inv_key)
        record("invoice redis key exists", bool(inv_raw))
        record("invoice redis TTL ~480s (8 min)", ttl is not None and 400 <= int(ttl) <= 480, f"ttl={ttl}")

        # Insufficient stock edge: ask for huge qty
        invoice2 = dict(invoice)
        invoice2["order_id"] = str(uuid.uuid4())
        invoice2["line_items"] = [
            {**invoice["line_items"][0], "qty": 999999, "line_total_paise": int(item.price_paise) * 999999}
        ]
        r = httpx.post(f"{RES}/reservation/submit-invoice", json={"invoice": invoice2}, timeout=30)
        body = r.json()
        record(
            "reservation fails when not enough stock",
            r.status_code == 200 and body.get("success") is False and bool(body.get("unavailable_items")),
            json.dumps(body)[:180],
        )

        # Expire hold manually and rollback
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE reserved_items SET expires_at = now() - interval '1 minute' "
                    "WHERE invoice_id = :iid AND status = 'HELD'"
                ),
                {"iid": inv_id},
            )
            await session.commit()

        # Call rollback via service method directly
        from services.reservation_service.reservation_service import ReservationService

        svc = ReservationService(AsyncSessionLocal)
        released = await svc.rollback_expired_holds()
        record("rollback releases expired hold", inv_id in released, str(released))
        async with AsyncSessionLocal() as session:
            restored = (
                await session.execute(select(Item).where(Item.id == item.id))
            ).scalar_one()
        record(
            "stock restored after rollback",
            int(restored.quantity_available) == before_qty,
            f"now={restored.quantity_available} expected={before_qty}",
        )

    # Concurrent last-unit race against DB
    async with AsyncSessionLocal() as session:
        race_item = (
            await session.execute(
                select(Item).where(Item.is_active.is_(True), Item.quantity_available >= 1).limit(1)
            )
        ).scalar_one_or_none()
        if race_item is not None:
            # Force qty to 1 for race
            await session.execute(
                text("UPDATE items SET quantity_available = 1 WHERE id = :id"),
                {"id": str(race_item.id)},
            )
            await session.commit()
            race_item_id = str(race_item.id)
            unit_price = int(race_item.price_paise)
            name = race_item.name
            brand = race_item.brand
            weight = race_item.weight_per_unit
        else:
            race_item_id = ""

    if race_item_id:
        def build_inv():
            oid = str(uuid.uuid4())
            return {
                "order_id": oid,
                "session_id": str(uuid.uuid4()),
                "issued_at": datetime.now(timezone.utc).isoformat(),
                "merchant_name": "Acme Mart",
                "line_items": [
                    {
                        "item_id": race_item_id,
                        "name": name,
                        "brand": brand,
                        "qty": 1,
                        "unit_price_paise": unit_price,
                        "line_total_paise": unit_price,
                        "weight_per_unit": weight,
                    }
                ],
                "subtotal_paise": unit_price,
                "discount_paise": 0,
                "taxable_paise": unit_price,
                "cgst_paise": 0,
                "sgst_paise": 0,
                "tax_paise": 0,
                "shipping_paise": 0,
                "total_paise": unit_price,
                "accepted_offers": [],
            }

        async def race_one():
            return await asyncio.to_thread(
                lambda: httpx.post(
                    f"{RES}/reservation/submit-invoice",
                    json={"invoice": build_inv()},
                    timeout=30,
                ).json()
            )

        race_results = await asyncio.gather(race_one(), race_one())
        wins = sum(1 for r in race_results if r.get("success"))
        record("last-unit race: exactly one winner", wins == 1, json.dumps(race_results)[:300])

    # Merchant row encrypted at rest
    if merchant_id:
        async with AsyncSessionLocal() as session:
            m = (
                await session.execute(select(Merchant).where(Merchant.id == uuid.UUID(merchant_id)))
            ).scalar_one()
        enc = m.razorpay_key_secret_encrypted or ""
        record(
            "DB stores encrypted razorpay secret",
            bool(enc) and "secret_demo" not in enc and enc.startswith("gAAAA"),
            enc[:40] + "...",
        )

    await close_redis_client(redis)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print("\n==== SUMMARY ====")
    print(f"passed={passed} failed={failed} total={len(results)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
