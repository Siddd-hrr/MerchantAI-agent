from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.offer_engine.routers import (
    catalog_router,
    combos_router,
    coupons_router,
    cross_sell_router,
    discounts_router,
    festival_campaigns_router,
    offers_router,
)

app = FastAPI(title="Offer Engine Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(discounts_router)
app.include_router(combos_router)
app.include_router(coupons_router)
app.include_router(festival_campaigns_router)
app.include_router(cross_sell_router)
app.include_router(offers_router)
app.include_router(catalog_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "offer_engine"}
