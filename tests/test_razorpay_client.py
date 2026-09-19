from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.payment_service.credential_store import MerchantCredentials
import services.payment_service.razorpay_client as razorpay_client
from services.payment_service.razorpay_client import RealRazorpayClient, get_razorpay_client


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return dict(self._payload)


class _FakeAsyncClient:
    def __init__(self, *, auth, timeout: float) -> None:  # noqa: ANN001
        self.auth = auth
        self.timeout = timeout
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def post(self, url: str, json: dict) -> _FakeResponse:
        self.calls.append((url, json))
        return _FakeResponse({"id": "plink_real_1", "short_url": "https://rzp.io/i/real-1"})


@pytest.mark.asyncio
async def test_real_client_create_link_sends_notes_expiry_and_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _build_async_client(*, auth, timeout: float):  # noqa: ANN001
        client = _FakeAsyncClient(auth=auth, timeout=timeout)
        captured["client"] = client
        return client

    monkeypatch.setattr(razorpay_client.httpx, "AsyncClient", _build_async_client)
    monkeypatch.setattr(
        razorpay_client,
        "get_settings",
        lambda: SimpleNamespace(payment_link_ttl_seconds=300),
    )

    client = RealRazorpayClient(
        MerchantCredentials(
            merchant_id="merchant-1",
            key_id="rzp_test_key_1",
            key_secret="rzp_test_secret_1",
        )
    )

    result = await client.create_link(
        merchant_id="merchant-1",
        invoice_id="inv-42",
        session_id="sess-42",
        amount_paise=5600,
        customer_name="Priya",
        customer_phone="+919999000111",
        description="Invoice inv-42 payment",
    )

    assert result.payment_link_id == "plink_real_1"
    assert result.payment_link_url == "https://rzp.io/i/real-1"
    fake_client = captured["client"]
    assert isinstance(fake_client, _FakeAsyncClient)
    assert fake_client.auth == ("rzp_test_key_1", "rzp_test_secret_1")
    assert fake_client.calls
    _, payload = fake_client.calls[0]
    assert payload["reference_id"] == "inv-42"
    assert payload["description"] == "Invoice inv-42 payment"
    assert payload["notes"] == {
        "invoice_id": "inv-42",
        "session_id": "sess-42",
        "merchant_id": "merchant-1",
    }
    assert isinstance(payload["expire_by"], int)
    assert payload["customer"] == {"name": "Priya", "contact": "+919999000111"}


def test_get_razorpay_client_test_mode_rejects_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(razorpay_client, "get_settings", lambda: SimpleNamespace(razorpay_mode="test"))
    with pytest.raises(razorpay_client.RazorpayClientError) as exc:
        get_razorpay_client(
            MerchantCredentials(
                merchant_id="merchant-1",
                key_id="rzp_live_bad",
                key_secret="live_secret_bad",
            )
        )
    assert exc.value.code == "RAZORPAY_CREDENTIALS_INVALID"
