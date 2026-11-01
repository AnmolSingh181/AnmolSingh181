# Global Plastic Trading Intelligence Platform

B2B intelligence and lead management for international trading of **LDPE, LLDPE and HDPE**, whether virgin/prime,
near-prime, off-grade, off-spec, recycled, reprocessed, PCR or PIR. The platform discovers companies, classifies **who
deals in which material, where, whether they buy or sell it, and how to contact them**, deduplicates them into master
records, scores them, and gives you a CRM to work the leads.

**Nothing is fabricated.** Every company, material claim, specification, contact and shipment is stored with the
source URL, collection time and the verbatim evidence it was derived from. Unknowns stay `unknown` / `needs_review`.

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router) + TypeScript + Tailwind CSS 4 + shadcn/ui-style components |
| Backend | Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic |
| Database | PostgreSQL 16 (Supabase-compatible; uses `pg_trgm`) |
| Collection | httpx + BeautifulSoup crawler (robots.txt, rate limits, sitemaps), optional Playwright rendering |
| Intelligence | Rule-based dictionary classifier + evidence-validated OpenAI structured extraction |
| Jobs | DB-backed queue (`FOR UPDATE SKIP LOCKED`) + APScheduler refresh workflows; optional n8n webhook alerts |

## Run it in your browser (GitHub Codespaces, nothing to install)

1. On GitHub open the repository, switch to the branch with this code, click **Code → Codespaces → Create codespace**.
2. When the editor opens, run in its terminal:
   ```bash
   bash scripts/start.sh
   ```
   It creates the settings file, starts database + API + worker + web app with Docker (5–10 min the first time),
   asks for your login email/password and prints the link to open (also under the **PORTS** tab, port 3000).
3. The codespace sleeps after ~30 minutes idle; data is kept. Reopen it from github.com/codespaces and run
   `bash scripts/start.sh` again. Codespaces includes free monthly usage for personal accounts; heavier use is billed by GitHub.

For a permanent, always-on site use the cloud deployment in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start (local)

Requirements: Python 3.11+, Node 20+, PostgreSQL 14+.

```bash
createdb plastic_intel
```

```bash
cd backend && pip install -r requirements-dev.txt && cp .env.example .env
```

```bash
alembic upgrade head && python -m app.cli seed-reference
```

```bash
python -m app.cli create-admin you@yourcompany.com 'a-strong-password'
```

```bash
uvicorn app.main:app --reload --port 8000
```

In a second terminal (scheduler + job worker):

```bash
cd backend && python -m app.workers.scheduler
```

In a third terminal (web UI on http://localhost:3000):

```bash
cd frontend && npm install && npm run dev
```

Or everything with Docker: `docker compose up --build` (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).

### First data

The database starts empty on purpose. To start filling it:
1. **Data sources → Import**: upload a permitted CSV/XLSX export (ImportYeti/Volza/Panjiva/TradeData.Pro shipments,
   Kompass/directory/trade-fair company lists, your own CRM).
2. **Data sources → Crawl a company website**: paste any company URL.
3. Add a search API key (Brave / Serper / SerpAPI / Google CSE) and run **Search API discovery**, which builds
   MATERIAL × GRADE × COUNTRY × BUSINESS TYPE × BUYER/SELLER queries and queues every new company website for crawling.
4. Run **UN Comtrade** / **US Census** for official country-level HS 3901/3915 trade statistics (free).

### Demo environment (synthetic data only)

To evaluate the UI without real data, use a **separate database** and `APP_ENV=demo`:

```bash
APP_ENV=demo DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/plastic_intel_demo python -m app.cli seed-demo
```

Demo records are flagged `is_demo`, prefixed `[DEMO]`, use reserved `.example` domains and are invisible unless `APP_ENV=demo`.

## Repository layout

```
backend/   FastAPI app, connectors, services, Alembic migrations, tests
frontend/  Next.js web application
db/        schema.sql (generated from migrations, for the Supabase SQL editor)
docs/      architecture, API, deployment, testing, data sources, limitations, openapi.json
PROJECT_STATUS.md   completed / pending modules and next tasks
```

## Documentation
- [Architecture & database structure](docs/ARCHITECTURE.md)
- [API reference](docs/API.md) (live Swagger at `http://localhost:8000/docs`)
- [Deployment (Supabase + Render + Vercel, or Docker)](docs/DEPLOYMENT.md)
- [Testing & acceptance evaluation](docs/TESTING.md)
- [Data sources: connected vs pending](docs/DATA_SOURCES.md)
- [Known limitations & future improvements](docs/LIMITATIONS.md)
