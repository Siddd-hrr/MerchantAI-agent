from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.merchant_admin.routers import internal_inventory_router, upload_router

app = FastAPI(title="Merchant Admin Service")
# No auth this phase (demo/internal only) — known gap, not a silent omission.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(upload_router)
app.include_router(internal_inventory_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "merchant_admin"}
