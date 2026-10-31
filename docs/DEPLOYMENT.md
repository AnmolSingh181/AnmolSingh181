# Deployment

Recommended low-cost production setup (roughly ₹3,000–8,000/month depending on plan choices; check current pricing):

| Component | Service | Notes |
|---|---|---|
| Database + (optional) auth | **Supabase** | Postgres with `pg_trgm`. Free tier for testing; Pro for production backups |
| API | **Render** web service (Docker, `backend/`) | `render.yaml` blueprint included |
| Scheduler/worker | **Render** background worker (same image) | `python -m app.workers.scheduler` |
| Web UI | **Vercel** (`frontend/`) | set `BACKEND_URL` to the Render API URL |
| Automation | **n8n** (optional, self-hosted) | receives alert webhooks |

## 1. Database (Supabase)
1. Create a project; copy the **Session pooler** connection string (port 5432).
2. Set `DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
3. Apply the schema, either with `alembic upgrade head` from your machine/Render shell (preferred, versioned) or by
   pasting `db/schema.sql` into the Supabase SQL editor.
4. `python -m app.cli seed-reference`, then `python -m app.cli create-admin you@company.com '<strong password>'`.

## 2. API + worker (Render)
1. New → Blueprint → point to this repo (`render.yaml`).
2. Fill env vars from `backend/.env.example`: at least `DATABASE_URL`, `JWT_SECRET` (auto-generated on the web
   service; copy the same value to the worker), `CORS_ORIGINS=https://<your-vercel-domain>`, `APP_ENV=production`.
3. The web container runs migrations + reference seed on start, then uvicorn. Health check: `/health`.
4. Optional keys (OpenAI, search API, Apollo, ZeroBounce, trade data) can be added at any time; each source becomes
   ready automatically (Data sources page shows readiness).

## 3. Frontend (Vercel)
1. Import the repo, root directory `frontend`.
2. Environment variable `BACKEND_URL=https://plastic-intel-api.onrender.com` (used at build time by the `/api` rewrite).
3. Deploy. The browser talks only to Vercel; API keys never reach the client.

## Supabase Auth instead of local passwords (optional)
Set `AUTH_MODE=supabase` and `SUPABASE_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` (or legacy
`SUPABASE_JWT_SECRET`). Users signing in via Supabase are created as `viewer` until an admin promotes them. The bundled
login page uses local auth. For Supabase mode, add a Supabase sign-in on the frontend that stores the access token
under `localStorage['pti_token']`.

## Single server (Docker Compose)
```bash
cp backend/.env.example backend/.env
```
```bash
docker compose up --build -d
```
```bash
docker compose exec backend python -m app.cli create-admin you@company.com 'a-strong-password'
```
UI at `http://<server>:3000`, API at `:8000`. Put a reverse proxy (Caddy/Nginx) with TLS in front for production.

## Alerts → n8n
Set `ALERT_WEBHOOK_URL` to an n8n Webhook node URL. The API/worker POSTs JSON:
```json
{"type": "job_failed|material_change|new_shipment", "severity": "info|warning", "message": "...",
 "entity_type": "company|scrape_job", "entity_id": "...", "payload": {}}
```
New-company alerts are stored in-app only (to avoid floods during imports). Route the rest in n8n to email/Slack/WhatsApp.

## Production checklist
- Strong `JWT_SECRET` (≥ 32 chars), `APP_ENV=production`, `CORS_ORIGINS` set to the real UI origin.
- Set `CRAWLER_USER_AGENT` with a real contact address.
- Enable Supabase daily backups.
- Only enable directory connectors after reviewing and recording their terms (Data sources → Confirm terms).
- Never run `seed-demo` against the production database (it refuses unless `APP_ENV=demo`).
