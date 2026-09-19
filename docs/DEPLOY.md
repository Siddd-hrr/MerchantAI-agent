# Production deploy (GitHub → VPS)

Deploy Merchant AI Agent from [GitHub](https://github.com/Siddd-hrr/MerchantAI-agent) to a Linux VPS using **Docker Compose** and **GitHub Actions** (SSH). App secrets stay on the server in `.env` (never in git). Actions only needs SSH deploy secrets.

## Architecture

```
GitHub main push → Actions deploy.yml → SSH → VPS
  → git pull
  → docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Server `.env` (mode `600`) holds `GOOGLE_API_KEY`, `JWT_SECRET`, `CREDENTIAL_ENCRYPTION_KEY`, DB passwords, Razorpay webhook secret, etc.

## 1. VPS prerequisites

Recommended: Ubuntu 22.04+, **4GB+ RAM** (Kafka + services).

1. Install [Docker Engine](https://docs.docker.com/engine/install/) and the Compose plugin.
2. Create deploy user with Docker access (or use root carefully).
3. Open firewall: `22` (SSH), `80` / `443` (HTTP/HTTPS). Prefer not exposing Postgres/Redis/Kafka publicly.
4. Clone the repo once:

```bash
sudo mkdir -p /opt/merchant-ai-agent
sudo chown "$USER:$USER" /opt/merchant-ai-agent
git clone https://github.com/Siddd-hrr/MerchantAI-agent.git /opt/merchant-ai-agent
cd /opt/merchant-ai-agent
```

## 2. Server `.env` (app secrets)

```bash
cp .env.production.example .env
chmod 600 .env
nano .env   # fill real secrets; use Docker service hostnames (postgres, redis, kafka)
```

Required sensitive fields (examples):

| Variable | Notes |
|----------|--------|
| `GOOGLE_API_KEY` | Gemini |
| `JWT_SECRET` | Strong random string |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key or strong secret |
| `POSTGRES_PASSWORD` | Also reflected in `DATABASE_URL` |
| `RAZORPAY_WEBHOOK_SECRET` | When using live webhooks |
| `LANGCHAIN_API_KEY` | Only if tracing enabled |

Set public frontend build URLs in `.env` (no secrets):

- `VITE_AUTH_SERVICE_URL`
- `VITE_ADMIN_SERVICE_URL`
- `VITE_GATEWAY_URL`
- `VITE_PAYMENT_LOG_SERVICE_URL`

First bring-up (manual, before Actions):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec gateway alembic upgrade head   # or run alembic from a one-off container
```

Adjust migration command to your usual process if services differ.

## 3. GitHub Secrets (deploy only)

In the repo: **Settings → Environments → New environment → `production`**.

Add these **Environment secrets** (Actions uses them; values never go in git):

| Secret | Purpose |
|--------|---------|
| `DEPLOY_HOST` | VPS IP or hostname |
| `DEPLOY_USER` | SSH user |
| `DEPLOY_SSH_KEY` | Private key (PEM) with access to the VPS |
| `DEPLOY_PATH` | Absolute path, e.g. `/opt/merchant-ai-agent` |
| `DEPLOY_PORT` | Optional; default `22` |

Do **not** put app API keys into Actions if the server already has `.env` (recommended). That avoids leaking secrets into workflow logs.

## 4. Deploy workflow

File: `.github/workflows/deploy.yml`

- Triggers on push to `main` and `workflow_dispatch`
- Uses environment `production`
- SSHs to the VPS, `git fetch` + `reset --hard origin/main`, then compose up with prod override

After setting secrets, push to `main` or run **Actions → Deploy production → Run workflow**.

## 5. TLS / DNS (you configure once)

Point your domain at the VPS. Terminate TLS with Caddy or nginx in front of:

- Frontend (Compose maps host `8080` → frontend nginx by default in prod override)
- Or a single reverse proxy to `frontend:80`, `gateway:8000`, `auth_service:8006`, etc.

Rebuild the frontend image after changing `VITE_*` URLs:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build frontend
```

## 6. Razorpay webhook

Point Razorpay webhooks to your public URL for payment log, e.g.:

`https://your-domain.example/webhook/razorpay`

(or whatever path/port you expose for `payment_log_service`). Keep `RAZORPAY_WEBHOOK_SECRET` only in server `.env`.

## Security checklist

- [ ] No `.env` committed to GitHub
- [ ] Server `.env` is `chmod 600` and owned by deploy user
- [ ] GitHub Environment `production` protects deploy
- [ ] SSH key is deploy-only (limited permissions)
- [ ] Postgres/Redis/Kafka not published to the public internet
- [ ] Rotate keys immediately if a secret is ever pushed by mistake
