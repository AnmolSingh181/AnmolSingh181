# PROJECT_STATUS

_Last updated: 2026-10-31_

## Completed modules
| Phase | Module | Location |
|---|---|---|
| 1 | Project structure, config via env, Docker, Render blueprint | `backend/`, `frontend/`, `docker-compose.yml`, `render.yaml` |
| 1 | PostgreSQL schema (29 tables) + Alembic migration + generated SQL | `backend/app/models.py`, `backend/migrations/`, `db/schema.sql` |
| 1 | Auth (local JWT + Supabase JWT/JWKS), roles, activity log | `backend/app/auth.py` |
| 1 | FastAPI backend (48 endpoints) | `backend/app/api/` |
| 1/4 | Next.js UI: dashboard, discovery, profile, AI search, contacts, trade, CRM, sources, quality, settings, privacy | `frontend/src/app/` |
| 2 | Connector framework, polite HTTP client, raw storage | `backend/app/connectors/base.py`, `services/http.py` |
| 2 | Website crawler, search-API discovery, US Census, UN Comtrade, CSV/XLSX import | `backend/app/connectors/` |
| 2 | Key-free producer discovery from Wikidata (auto-scheduled) | `connectors/wikidata.py` |
| 2 | Gated connectors: ImportYeti/Volza/Panjiva/TradeData.Pro API, directories, Kompass, Apollo | `connectors/gated.py` |
| 3 | Rule classifier + YAML dictionary; OpenAI extraction with evidence validation | `services/classifier.py`, `services/ai_classifier.py` |
| 3 | Entity resolution, duplicate review, merge | `services/dedupe.py` |
| 3 | Contact extraction + verification ladder + suppression | `services/contacts.py` |
| 3 | Configurable explainable lead scoring | `services/scoring.py` |
| 4 | Combined search filters, NL query parsing | `services/search.py`, `services/nl_search.py` |
| 5 | Job queue (SKIP LOCKED, retries, isolation), scheduler, alerts + webhook | `workers/`, `services/alerts.py` |
| 6 | 31 backend tests, Playwright UI walkthrough, acceptance metrics endpoint | `backend/tests/`, `services/metrics.py` |

## Pending / requires owner action
- Provide credentials: search API (Brave/Serper), OpenAI (optional), Apollo, ZeroBounce, trade-data contracts.
- Review terms for ENF, Plasticker, Plastics Markets, EPDA; configure selectors if permitted.
- First live runs of Census/Comtrade/search connectors after deployment (untested live: build sandbox blocked egress).
- Deploy: Supabase project, Render services, Vercel project (see `docs/DEPLOYMENT.md`).
- Collect and review real data toward acceptance targets (`docs/TESTING.md`).

## Current architecture
Next.js (Vercel) → `/api` rewrite → FastAPI (Render) → PostgreSQL (Supabase). Scheduler/worker (Render worker) enqueues
refresh workflows and executes jobs from `scrape_jobs`. See `docs/ARCHITECTURE.md`.

## Database structure
See the table list in `docs/ARCHITECTURE.md#database-structure-29-tables`.

## Known issues
- Scheduler intervals require a worker restart after change.
- CSV import is synchronous (≤ 20 MB per file).
- Bundled login is local-auth only (Supabase Auth requires a sign-in screen to be added).

## Next development tasks
1. Deploy and run first live collection; fix any provider response-shape differences found in job logs.
2. Async large-file imports via Supabase Storage.
3. Multilingual dictionary terms and per-country query terms for CN/VN/AE/SA.
4. Price/trade trend charts; Metabase dashboards.
5. Supabase Auth sign-in UI; shared team pipelines.
