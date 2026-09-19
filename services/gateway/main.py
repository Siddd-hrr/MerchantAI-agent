from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.gateway.routers import converse_router

app = FastAPI(title="Merchant Gateway Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(converse_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}
