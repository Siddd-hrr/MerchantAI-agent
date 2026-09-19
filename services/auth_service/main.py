from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.auth_service.router import router as auth_router

app = FastAPI(title="Auth Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "auth_service"}
