# Merchant AI Agent (Phase 1 Demo)

**Project root:** `Merchant-AI-Agent/` (this folder)

For a plain-English explanation of how the AI built this system, the conversation logic, and every edge case tested, read:

**[`HOW_THE_AGENT_BUILT_THIS.md`](HOW_THE_AGENT_BUILT_THIS.md)**

This repository contains a Phase 1 demo stack for a merchant assistant system:
- Backend services: `gateway`, `async_worker`, `merchant_agent` (LangGraph), `merchant_admin`
- Frontend: Vite app in `frontend/`
- Shared models/schemas, migrations, and test fixtures

The steps below are written for a new contributor to get a working demo quickly.

## Prerequisites

Install these first:
- Python `3.11+`
- [`uv`](https://docs.astral.sh/uv/)
- Docker Desktop (daemon running)
- Node.js `18+`

## 10-Minute Quick Start (Docker Compose)

From repo root:

1. Copy environment template and configure key:
   - Copy `.env.example` to `.env`
   - Set `GOOGLE_API_KEY` in `.env` manually (do **not** commit real keys)
   - Host Postgres is mapped to **port 5433** and Redis to **port 16379** (`DATABASE_URL=...@localhost:5433/...`, `REDIS_URL=redis://localhost:16379/0`) so they do not clash with local services. Inside Docker Compose, services still use `postgres:5432` and `redis:6379`.

2. Install Python dependencies:
   - `uv sync`

3. Start infra and services:
   - `docker compose up --build -d`

4. Apply DB migrations:
   - `alembic upgrade head`

5. Seed catalog data:
   - `python -m scripts.seed_catalog`

6. Optional scaling demo:
   - `docker compose up --scale async_worker=2 --scale merchant_agent=2 -d`

## Run Without Full Compose (Local Service Processes)

If you do not want to run the full compose stack, run services manually in separate terminals:

- `uvicorn services.gateway.main:app --host 0.0.0.0 --port 8000 --reload`
- `uvicorn services.async_worker.main:app --host 0.0.0.0 --port 8001 --reload`
- `uvicorn services.merchant_agent.main:app --host 0.0.0.0 --port 8002 --reload`
- `uvicorn services.merchant_admin.main:app --host 0.0.0.0 --port 8003 --reload`

You still need:
- `uv sync`
- `alembic upgrade head`
- `python -m scripts.seed_catalog`

## Demo Flows

From repo root:

- Happy path conversation:
  - `python scripts/demo_converse.py`

- Mandate-failure conversation:
  - `python scripts/demo_converse.py --invalid-mandate`

## Frontend

Start the frontend Vite app:

- `cd frontend`
- `npm install`
- `npm run dev`

## Secrets and environment

- Copy `.env.example` → `.env` for local development. **Never commit `.env`.**
- For production on a VPS, use `.env.production.example` as a template → server `.env` (`chmod 600`).
- Frontend: copy `frontend/.env.example` → `frontend/.env` locally. Vite `VITE_*` values are public URLs only — do not put API keys there.
- Production deploy secrets (SSH) and app secrets stay in **GitHub Environments / server `.env`**, not in the repository. See [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Production deploy from GitHub

This stack deploys to a Linux VPS with Docker Compose via GitHub Actions. Full steps: [`docs/DEPLOY.md`](docs/DEPLOY.md). Secrets checklist: [`docs/GITHUB_SECRETS.md`](docs/GITHUB_SECRETS.md).

## Test Suite

Run tests from repo root:

- `.\.venv\Scripts\python -m pytest -q`

## Phase 2

See [`PHASE2_BUILD_NOTES.md`](PHASE2_BUILD_NOTES.md). Free-tier Gemini is unchanged (`gemini-3.6-flash`).

Offer Engine UI: `cd frontend/offer-engine && npm run dev` → http://localhost:5174  
Offer Engine API: http://localhost:8004  
Reservation worker health: http://localhost:8005/healthz

Current Phase 1 behavior intentionally includes stubs/constraints:
- Mandate cryptographic verification is mocked for demo behavior.
- Discounts model/table exists but runtime paths do not currently read discount data.
- Razorpay payment APIs are not integrated in this phase.
