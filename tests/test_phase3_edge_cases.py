"""Phase 3 edge-case tests mapped to the master-prompt Definition of Done."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from services.auth_service.main import app as auth_app
import services.auth_service.router as auth_router
from services.auth_service.merchant_cache import sync_merchant_cache
from services.auth_service.password import hash_password, verify_password
from services.async_worker import mandate_verifier
from services.merchant_agent.graph.nodes import (
    NodeDependencies,
    dispatch_invoice_processing,
    resolve_invoice_outcome,
)
from services.payment_service.credential_store import MerchantCredentials
from services.payment_service.router import build_router as build_payment_router
from services.reservation_service.invoice_store import InvoiceStore
from services.reservation_service.reservation_service import ReservationService
from shared.crypto import decrypt_secret, encrypt_secret
from shared.models.merchant import Merchant
from shared.schemas.invoice import Invoice, InvoiceLineItem
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.stream: list[dict[str, str]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> int:
        existed = 1 if key in self.store else 0
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return existed

    async def xadd(self, _stream: str, fields: dict[str, str]) -> str:
        self.stream.append(fields)
        return "1-0"


class FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, _obj: object) -> None:
        return None

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self


class FakeMemoryStore:
    def __init__(self) -> None:
        self.audit_events: list[dict] = []

    async def append_audit(self, _db, *, session_id: str, actor: str, action: str, detail: dict) -> None:
        self.audit_events.append({"session_id": session_id, "actor": actor, "action": action, "detail": detail})


def _encode_mandate(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _invoice(*, order_id: str | None = None, item_id: str | None = None, qty: int = 1) -> Invoice:
    oid = order_id or str(uuid4())
    iid = item_id or str(uuid4())
    return Invoice(
        order_id=oid,
        session_id=str(uuid4()),
        issued_at=datetime.now(UTC).isoformat(),
        merchant_name="Acme Mart",
        customer_name="Alex",
        address="Street 1",
        phone_number="9999999999",
        line_items=[
            InvoiceLineItem(
                item_id=iid,
                name="Milk",
                brand="DairyGold",
                qty=qty,
                unit_price_paise=6200,
                line_total_paise=6200 * qty,
                weight_per_unit="L",
            )
        ],
        subtotal_paise=6200 * qty,
        discount_paise=0,
        taxable_paise=6200 * qty,
        cgst_paise=0,
        sgst_paise=0,
        tax_paise=0,
        shipping_paise=0,
        total_paise=6200 * qty,
        accepted_offers=[],
    )


# ---------------------------------------------------------------------------
# DoD 1 + 2 — Auth signup/login + secret never leaked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dod1_signup_login_jwt_and_trusted_issuer_required(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    fake_redis = FakeRedis()
    merchants: dict[str, Merchant] = {}

    async def fake_db():
        yield FakeSession()

    async def fake_redis_dep():
        yield fake_redis

    async def get_by_email(_s, email: str):
        return merchants.get(email.lower())

    async def get_by_id(_s, merchant_id):
        return next((m for m in merchants.values() if str(m.id) == str(merchant_id)), None)

    async def create(_s, payload):
        merchant = Merchant(
            id=uuid4(),
            email=payload.email.lower(),
            password_hash=hash_password(payload.password),
            display_name=payload.resolved_display_name(),
            trusted_issuers=payload.resolved_trusted_issuers(),
            razorpay_key_id=payload.razorpay_key_id,
            razorpay_key_secret_encrypted=encrypt_secret(payload.razorpay_key_secret)
            if payload.razorpay_key_secret
            else None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        merchants[merchant.email] = merchant
        return merchant

    async def update(_s, merchant, payload):
        return merchant

    monkeypatch.setattr(auth_router, "_get_merchant_by_email", get_by_email)
    monkeypatch.setattr(auth_router, "_get_merchant_by_id", get_by_id)
    monkeypatch.setattr(auth_router, "_create_merchant", create)
    monkeypatch.setattr(auth_router, "_apply_profile_update", update)
    auth_app.dependency_overrides[auth_router.get_db_dependency] = fake_db
    auth_app.dependency_overrides[auth_router.get_redis_dependency] = fake_redis_dep

    transport = ASGITransport(app=auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad = await client.post(
            "/auth/signup",
            json={
                "email": "kid@test.com",
                "password": "password123",
                "trusted_issuers": [],
                "razorpay_key_id": "rzp_test_x",
                "razorpay_key_secret": "super-secret-never-leak",
            },
        )
        assert bad.status_code == 422

        signup = await client.post(
            "/auth/signup",
            json={
                "email": "kid@test.com",
                "password": "password123",
                "display_name": "Kid Mart",
                "trusted_issuers": ["issuer-a"],
                "razorpay_key_id": "rzp_test_x",
                "razorpay_key_secret": "super-secret-never-leak",
            },
        )
        assert signup.status_code == 201
        body = signup.json()
        assert body["access_token"]
        blob = json.dumps(body)
        assert "super-secret-never-leak" not in blob
        assert "razorpay_key_secret" not in blob

        mid = body["profile"]["id"]
        creds = json.loads(fake_redis.store[f"merchant:{mid}:razorpay_creds"])
        assert creds["key_id"] == "rzp_test_x"
        assert "key_secret_encrypted" in creds
        assert creds["key_secret_encrypted"] != "super-secret-never-leak"
        assert decrypt_secret(creds["key_secret_encrypted"]) == "super-secret-never-leak"
        assert json.loads(fake_redis.store[f"merchant:{mid}:trusted_issuers"]) == ["issuer-a"]

        login = await client.post(
            "/auth/login",
            json={"email": "kid@test.com", "password": "password123"},
        )
        assert login.status_code == 200
        assert login.json()["access_token"]
        assert "super-secret-never-leak" not in login.text

    auth_app.dependency_overrides.clear()


def test_dod2_password_hash_and_fernet_roundtrip() -> None:
    hashed = hash_password("password123")
    assert hashed != "password123"
    assert verify_password("password123", hashed)
    assert not verify_password("wrong", hashed)
    token = encrypt_secret("plain-secret")
    assert token != "plain-secret"
    assert decrypt_secret(token) == "plain-secret"


# ---------------------------------------------------------------------------
# DoD 3 — Per-merchant mandate issuers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dod3_merchant_issuers_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    merchant_id = str(uuid4())
    await fake_redis.set(f"merchant:{merchant_id}:trusted_issuers", json.dumps(["shop-issuer-only"]))

    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(
        mandate_verifier,
        "get_settings",
        lambda: SimpleNamespace(
            trusted_mandate_issuers_list=["issuer-a", "issuer-b"],
            allow_global_trusted_issuers_fallback=False,
            mandate_max_age_seconds=300,
        ),
    )

    async def no_audit(**_kwargs):
        return None

    monkeypatch.setattr(mandate_verifier, "_write_mandate_failure_audit", no_audit)

    now = int(datetime.now(UTC).timestamp())
    good = _encode_mandate(
        {"issuer": "shop-issuer-only", "subject": "c1", "issued_at": now, "signature": "sig-good-1"}
    )
    claims = await mandate_verifier.verify_mandate(
        session_id="s1",
        consumer_agent_id="c1",
        human_sign_mandate=good,
        merchant_id=merchant_id,
    )
    assert claims.issuer == "shop-issuer-only"

    # env issuer-a is NOT enough when merchant list is set
    bad = _encode_mandate(
        {"issuer": "issuer-a", "subject": "c1", "issued_at": now, "signature": "sig-bad-env"}
    )
    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s2",
            consumer_agent_id="c1",
            human_sign_mandate=bad,
            merchant_id=merchant_id,
        )


@pytest.mark.asyncio
async def test_dod3_mandate_edge_cases_stale_replay_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(
        mandate_verifier,
        "get_settings",
        lambda: SimpleNamespace(
            trusted_mandate_issuers_list=["issuer-a"],
            allow_global_trusted_issuers_fallback=False,
            mandate_max_age_seconds=300,
        ),
    )

    async def no_audit(**_kwargs):
        return None

    monkeypatch.setattr(mandate_verifier, "_write_mandate_failure_audit", no_audit)

    now = int(datetime.now(UTC).timestamp())
    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s",
            consumer_agent_id="c",
            human_sign_mandate=_encode_mandate(
                {"issuer": "issuer-a", "subject": "c", "issued_at": now - 9999, "signature": "old"}
            ),
        )

    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s",
            consumer_agent_id="c",
            human_sign_mandate=_encode_mandate(
                {"issuer": "issuer-a", "subject": "c", "issued_at": now, "signature": "   "}
            ),
        )

    ok = _encode_mandate(
        {"issuer": "issuer-a", "subject": "c", "issued_at": now, "signature": "same-sig"}
    )
    await mandate_verifier.verify_mandate(
        session_id="s", consumer_agent_id="c", human_sign_mandate=ok
    )
    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s", consumer_agent_id="c", human_sign_mandate=ok
        )


@pytest.mark.asyncio
async def test_dod3_missing_merchant_issuers_fail_without_global_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis()
    merchant_id = str(uuid4())
    monkeypatch.setattr(mandate_verifier, "get_redis_client", lambda: fake_redis)
    async def no_merchant_issuers(**_kwargs):
        return None

    monkeypatch.setattr(mandate_verifier, "_load_merchant_trusted_issuers", no_merchant_issuers)
    monkeypatch.setattr(
        mandate_verifier,
        "get_settings",
        lambda: SimpleNamespace(
            trusted_mandate_issuers_list=["issuer-a"],
            allow_global_trusted_issuers_fallback=False,
            mandate_max_age_seconds=300,
        ),
    )

    now = int(datetime.now(UTC).timestamp())
    with pytest.raises(mandate_verifier.MandateVerificationError):
        await mandate_verifier.verify_mandate(
            session_id="s-no-fallback",
            consumer_agent_id="c1",
            human_sign_mandate=_encode_mandate(
                {"issuer": "issuer-a", "subject": "c1", "issued_at": now, "signature": "sig-1"}
            ),
            merchant_id=merchant_id,
        )


# ---------------------------------------------------------------------------
# DoD 4 + 5 + audits — dispatch / resolve matrix
# ---------------------------------------------------------------------------


class _ResClient:
    def __init__(self, result=None, err=None):
        self.result = result
        self.err = err
        self.calls = []

    async def submit_invoice(self, invoice):
        self.calls.append(invoice)
        if self.err:
            raise self.err
        return dict(self.result or {})


class _PayClient:
    def __init__(self, result=None, err=None):
        self.result = result
        self.err = err
        self.create_calls = []
        self.cancel_calls = []

    async def create_payment_link(self, **payload):
        self.create_calls.append(payload)
        if self.err:
            raise self.err
        return dict(self.result or {})

    async def cancel_payment_link(self, *, merchant_id, invoice_id):
        self.cancel_calls.append({"merchant_id": merchant_id, "invoice_id": invoice_id})
        return {"success": True, "cancelled": True, "invoice_id": invoice_id}


def _node_deps(memory, res, pay) -> NodeDependencies:
    class _SF:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *a):
            return None

    return NodeDependencies(
        llm=None,
        session_factory=lambda: _SF(),
        catalog_service=None,  # type: ignore[arg-type]
        memory_store=memory,  # type: ignore[arg-type]
        invoice_service=None,  # type: ignore[arg-type]
        personal_memory_store=None,  # type: ignore[arg-type]
        reservation_client=res,
        payment_client=pay,
        offer_lookup_tool=None,
        cross_sell_lookup_tool=None,
        campaign_orchestrator_scan_tool=None,
    )


@pytest.mark.asyncio
async def test_dod4_both_success_one_reply_with_payment_link() -> None:
    memory = FakeMemoryStore()
    invoice = _invoice().model_dump()
    res = _ResClient(
        result={"success": True, "reserved_at": "t0", "expires_at": "t1", "unavailable_items": []}
    )
    pay = _PayClient(
        result={
            "success": True,
            "payment_link_url": "https://rzp.io/i/fake-1",
            "expires_at": "tpay",
            "payment_link_id": "plink_1",
        }
    )
    deps = _node_deps(memory, res, pay)
    state = {
        "session_id": "s",
        "merchant_id": str(uuid4()),
        "invoice": invoice,
        "customer_name": "Alex",
        "phone": "9999999999",
    }
    dispatched = await dispatch_invoice_processing(state, deps)
    merged = {**state, **dispatched}
    outcome = await resolve_invoice_outcome(merged, deps)
    assert outcome["status"] == "INVOICED"
    assert "https://rzp.io/i/fake-1" in outcome["reply"]
    assert outcome["payment_link_url"] == "https://rzp.io/i/fake-1"
    assert outcome["invoice"]["payment_link_url"] == "https://rzp.io/i/fake-1"
    assert any(e["action"] == "INVOICE_FULFILLED" for e in memory.audit_events)
    assert pay.cancel_calls == []


@pytest.mark.asyncio
async def test_dod5_reservation_fail_cancels_payment_link() -> None:
    memory = FakeMemoryStore()
    invoice = _invoice().model_dump()
    res = _ResClient(
        result={
            "success": False,
            "unavailable_items": [
                {
                    "item_id": invoice["line_items"][0]["item_id"],
                    "requested_qty": 1,
                    "available_qty": 0,
                }
            ],
        }
    )
    pay = _PayClient(
        result={
            "success": True,
            "payment_link_url": "https://rzp.io/i/orphan-risk",
            "expires_at": "tpay",
            "payment_link_id": "plink_x",
        }
    )
    deps = _node_deps(memory, res, pay)
    state = {"session_id": "s", "merchant_id": "m1", "invoice": invoice}
    dispatched = await dispatch_invoice_processing(state, deps)
    outcome = await resolve_invoice_outcome({**state, **dispatched}, deps)
    assert outcome["status"] == "AWAITING_FIELDS"
    assert pay.cancel_calls == [{"merchant_id": "m1", "invoice_id": invoice["order_id"]}]
    assert any(e["action"] == "RESERVATION_FAILED_PAYMENT_VOIDED" for e in memory.audit_events)


@pytest.mark.asyncio
async def test_payment_fail_while_reservation_held_audited() -> None:
    memory = FakeMemoryStore()
    invoice = _invoice().model_dump()
    res = _ResClient(result={"success": True, "expires_at": "thold", "unavailable_items": []})
    pay = _PayClient(err=RuntimeError("razorpay down"))
    deps = _node_deps(memory, res, pay)
    state = {"session_id": "s", "merchant_id": "m1", "invoice": invoice}
    dispatched = await dispatch_invoice_processing(state, deps)
    outcome = await resolve_invoice_outcome({**state, **dispatched}, deps)
    assert outcome["status"] == "INVOICED"
    assert "payment" in outcome["reply"].lower() or "Payment" in outcome["reply"]
    assert any(e["action"] == "PAYMENT_LINK_FAILED" for e in memory.audit_events)


@pytest.mark.asyncio
async def test_both_fail_audited() -> None:
    memory = FakeMemoryStore()
    invoice = _invoice().model_dump()
    res = _ResClient(
        result={"success": False, "unavailable_items": [{"item_id": "x", "requested_qty": 1, "available_qty": 0}]}
    )
    pay = _PayClient(err=RuntimeError("pay fail"))
    deps = _node_deps(memory, res, pay)
    state = {"session_id": "s", "merchant_id": "m1", "invoice": invoice}
    dispatched = await dispatch_invoice_processing(state, deps)
    outcome = await resolve_invoice_outcome({**state, **dispatched}, deps)
    assert outcome["status"] == "AWAITING_FIELDS"
    assert any(e["action"] == "RESERVATION_FAILED" for e in memory.audit_events)


# ---------------------------------------------------------------------------
# DoD 6 — last-unit race (atomic conditional update semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dod6_last_unit_only_one_succeeds() -> None:
    """Simulate two racers: first decrement wins, second sees qty gone."""
    stock = {"qty": 1}
    lock = asyncio.Lock()

    async def atomic_decrement(_db, *, item_id, qty) -> bool:
        _ = item_id
        async with lock:
            if stock["qty"] >= qty:
                stock["qty"] -= qty
                await asyncio.sleep(0)  # yield to other waiter
                return True
            return False

    async def noop_insert(*_a, **_k):
        return None

    async def noop_refresh(*_a, **_k):
        return None

    async def available_qty(*_a, **_k) -> int:
        return int(stock["qty"])

    class Store:
        calls = []

        async def store_invoice(self, invoice_id, payload):
            self.calls.append(invoice_id)

    item_id = str(uuid4())

    def make_service():
        svc = ReservationService(
            session_factory=lambda: FakeSession(),  # type: ignore[arg-type]
            redis_client=FakeRedis(),  # type: ignore[arg-type]
            invoice_store=Store(),  # type: ignore[arg-type]
        )
        svc._decrement_stock_if_available = atomic_decrement  # type: ignore[method-assign]
        svc._insert_held_rows = noop_insert  # type: ignore[method-assign]
        svc._refresh_catalog_cache = noop_refresh  # type: ignore[method-assign]
        svc._fetch_available_qty = available_qty  # type: ignore[method-assign]
        return svc

    inv_a = _invoice(item_id=item_id, qty=1)
    inv_b = _invoice(item_id=item_id, qty=1)
    results = await asyncio.gather(make_service().reserve(inv_a), make_service().reserve(inv_b))
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    assert len(successes) == 1
    assert len(failures) == 1
    assert stock["qty"] == 0


# ---------------------------------------------------------------------------
# DoD 7 + 8 — expiry rollback + invoice Redis TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dod8_invoice_redis_ttl_matches_reservation_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "services.reservation_service.invoice_store.get_settings",
        lambda: SimpleNamespace(reservation_ttl_seconds=480),
    )
    store = InvoiceStore(redis_client=fake_redis)  # type: ignore[arg-type]
    await store.store_invoice("inv-1", {"order_id": "inv-1", "total_paise": 100})
    assert fake_redis.store["invoice:inv-1"]
    assert fake_redis.ttls["invoice:inv-1"] == 480


@pytest.mark.asyncio
async def test_dod7_expired_hold_restores_stock() -> None:
    item_id = uuid4()
    invoice_id = uuid4()
    now = datetime.now(UTC)

    class Row:
        def __init__(self):
            self.id = uuid4()
            self.invoice_id = invoice_id
            self.item_id = item_id
            self.reserved_qty = 2
            self.expires_at = now - timedelta(seconds=5)
            self.status = "HELD"

    row = Row()
    stock = {item_id: 3}
    released: list[str] = []
    added_audit_actions: list[str] = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        def begin(self):
            return self

        async def execute(self, stmt):
            sql = str(stmt)
            if "SELECT reserved_items" in sql or "FROM reserved_items" in sql:
                class R:
                    def scalars(self_inner):
                        return SimpleNamespace(all=lambda: [row])

                return R()
            if "UPDATE reserved_items" in sql:
                row.status = "RELEASED"
                return SimpleNamespace(rowcount=1)
            # stock restore update
            stock[item_id] = stock[item_id] + 2
            return SimpleNamespace(rowcount=1)

        def add(self, obj) -> None:
            added_audit_actions.append(getattr(obj, "action", ""))

    class Factory:
        def __call__(self):
            return Session()

    svc = ReservationService(
        session_factory=Factory(),  # type: ignore[arg-type]
        redis_client=FakeRedis(),  # type: ignore[arg-type]
        invoice_store=SimpleNamespace(store_invoice=lambda *a, **k: None),  # type: ignore[arg-type]
    )

    async def refresh(ids):
        released.extend(str(i) for i in ids)

    svc._refresh_catalog_cache = refresh  # type: ignore[method-assign]
    out = await svc.rollback_expired_holds()
    assert str(invoice_id) in out
    assert row.status == "RELEASED"
    assert stock[item_id] == 5
    assert str(item_id) in released
    assert "RESERVATION_EXPIRED_ROLLED_BACK" in added_audit_actions


# ---------------------------------------------------------------------------
# Crypto fail-closed outside tests
# ---------------------------------------------------------------------------


def test_crypto_requires_credential_encryption_key_outside_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shared.crypto as crypto_mod
    from shared.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(crypto_mod, "get_settings", get_settings)

    with pytest.raises(RuntimeError, match="CREDENTIAL_ENCRYPTION_KEY"):
        crypto_mod.encrypt_secret("must-fail")

    get_settings.cache_clear()
    monkeypatch.setenv("TESTING", "1")


# ---------------------------------------------------------------------------
# Payment secret never in API response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_api_never_returns_decrypted_secret() -> None:
    class Redis:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, value, ex=None):
            self.store[key] = value

        async def delete(self, key):
            self.store.pop(key, None)
            return 1

    class Creds:
        async def get_credentials(self, merchant_id):
            return MerchantCredentials(
                merchant_id=merchant_id,
                key_id="rzp_test_demo",
                key_secret="TOP-SECRET-VALUE",
            )

    app = FastAPI()
    app.include_router(build_payment_router(Creds(), Redis()))  # type: ignore[arg-type]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        create = await client.post(
            "/payment/create-link",
            json={"merchant_id": "m1", "invoice_id": "i1", "amount_paise": 100},
        )
        cancel = await client.post(
            "/payment/cancel-link",
            json={"merchant_id": "m1", "invoice_id": "i1"},
        )
    assert create.status_code == 200
    assert create.json()["success"] is True
    assert "expires_at" in create.json()
    assert "TOP-SECRET-VALUE" not in create.text
    assert "TOP-SECRET-VALUE" not in cancel.text


# ---------------------------------------------------------------------------
# Merchant cache sync helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merchant_cache_stores_encrypted_only() -> None:
    merchant = Merchant(
        id=uuid4(),
        email="a@b.com",
        password_hash="x",
        display_name="A",
        trusted_issuers=["issuer-a"],
        razorpay_key_id="rzp_test_demo",
        razorpay_key_secret_encrypted=encrypt_secret("live-secret"),
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    redis = FakeRedis()
    await sync_merchant_cache(redis, merchant)  # type: ignore[arg-type]
    creds = json.loads(redis.store[f"merchant:{merchant.id}:razorpay_creds"])
    assert creds["key_secret_encrypted"] == merchant.razorpay_key_secret_encrypted
    assert "live-secret" not in redis.store[f"merchant:{merchant.id}:razorpay_creds"]
