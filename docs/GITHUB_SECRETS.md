# GitHub Secrets checklist (fill in GitHub UI — never commit values)

## Environment: `production` (Settings → Environments)

### Deploy (required for Actions)

| Secret | Example shape | Notes |
|--------|---------------|--------|
| `DEPLOY_HOST` | `203.0.113.10` | VPS IP or hostname |
| `DEPLOY_USER` | `deploy` | SSH user with Docker rights |
| `DEPLOY_SSH_KEY` | `-----BEGIN OPENSSH PRIVATE KEY-----...` | Deploy-only key |
| `DEPLOY_PATH` | `/opt/merchant-ai-agent` | Absolute clone path |
| `DEPLOY_PORT` | `22` | Optional |

### App secrets — **server `.env` only** (recommended)

Do not put these in Actions logs. Keep them in `/opt/merchant-ai-agent/.env` (`chmod 600`):

- `GOOGLE_API_KEY`
- `JWT_SECRET`
- `CREDENTIAL_ENCRYPTION_KEY`
- `POSTGRES_PASSWORD` (+ matching `DATABASE_URL`)
- `RAZORPAY_WEBHOOK_SECRET`
- `LANGCHAIN_API_KEY` (if tracing)

Public (OK in `.env` / compose build args, still not secrets):

- `VITE_AUTH_SERVICE_URL`
- `VITE_ADMIN_SERVICE_URL`
- `VITE_GATEWAY_URL`
- `VITE_PAYMENT_LOG_SERVICE_URL`

See [DEPLOY.md](DEPLOY.md) for full steps.
