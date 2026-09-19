from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.db import AsyncSessionLocal
from shared.llm_client import get_llm_client
from shared.schemas.conversation import ConverseResponse

from services.merchant_agent.catalog_service import CatalogService
from services.merchant_agent.clients.payment_client import PaymentClient
from services.merchant_agent.clients.reservation_client import ReservationClient
from services.merchant_agent.graph.build_graph import build_graph
from services.merchant_agent.graph.nodes import NodeDependencies
from services.merchant_agent.invoice_service import InvoiceService
from services.merchant_agent.memory.personal import PersonalMemoryStore
from services.merchant_agent.memory_store import MemoryStore
from services.merchant_agent.tools.campaign_orchestrator_scan import CampaignOrchestratorScanTool
from services.merchant_agent.tools.cross_sell_lookup import CrossSellLookupTool
from services.merchant_agent.tools.offer_lookup import OfferLookupTool
from shared.config import get_settings

app = FastAPI(title="Merchant Agent Service")


class AgentTurnRequest(BaseModel):
    consumer_agent_id: str = Field(min_length=1)
    merchant_id: str | None = None
    session_id: str | None = None
    message: str = Field(min_length=1)
    mandate_verified: bool = False


memory_store = MemoryStore()
catalog_service = CatalogService()
invoice_service = InvoiceService(memory_store)
personal_memory_store = PersonalMemoryStore()
settings = get_settings()
reservation_client = ReservationClient(settings.reservation_service_url)
payment_client = PaymentClient(settings.payment_service_url)
offer_lookup_tool = OfferLookupTool()
cross_sell_lookup_tool = CrossSellLookupTool()
campaign_orchestrator_scan_tool = CampaignOrchestratorScanTool(offer_lookup_tool)
graph = build_graph(
    NodeDependencies(
        llm=get_llm_client(),
        session_factory=AsyncSessionLocal,
        catalog_service=catalog_service,
        memory_store=memory_store,
        invoice_service=invoice_service,
        personal_memory_store=personal_memory_store,
        reservation_client=reservation_client,
        payment_client=payment_client,
        offer_lookup_tool=offer_lookup_tool,
        cross_sell_lookup_tool=cross_sell_lookup_tool,
        campaign_orchestrator_scan_tool=campaign_orchestrator_scan_tool,
    )
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "merchant_agent"}


@app.post("/v1/agent/turn", response_model=ConverseResponse)
async def agent_turn(payload: AgentTurnRequest) -> ConverseResponse:
    session_id = payload.session_id or str(uuid4())
    initial_state = {
        "session_id": session_id,
        "consumer_agent_id": payload.consumer_agent_id,
        "merchant_id": payload.merchant_id,
        "message": payload.message,
        "mandate_verified": payload.mandate_verified,
    }
    try:
        result = await graph.ainvoke(initial_state)
        return ConverseResponse(
            session_id=session_id,
            status=result.get("status", "FAILED"),
            reply=result.get("reply", ""),
            missing_fields=result.get("missing_fields", []),
            catalog_suggestions=result.get("catalog_suggestions", []),
            invoice=result.get("invoice"),
            error=result.get("error"),
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        return ConverseResponse(
            session_id=session_id,
            status="FAILED",
            reply="Unable to process this turn.",
            missing_fields=[],
            catalog_suggestions=[],
            invoice=None,
            error={"code": "AGENT_ERROR", "message": str(exc)},
        )
