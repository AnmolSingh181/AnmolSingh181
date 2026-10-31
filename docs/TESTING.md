# Testing

## Automated tests (backend)
```bash
createdb plastic_intel_test
```
```bash
cd backend && python -m pytest -q
```
`tests/conftest.py` rebuilds the `plastic_intel_test` schema from migrations (override with `TEST_DATABASE_URL`).
Fixtures in `tests/fixtures/` are **synthetic** (fictional names, `.example` domains, 555 numbers).

| Suite | Covers |
|---|---|
| `test_classifier.py` | LLDPE vs LDPE disambiguation, per-clause grade/application/intent, explicit-only specs, non-prime → review, converter ≠ resin manufacturer, price/quantity extraction, AI output validation (invented quotes/values dropped) |
| `test_normalize_dedupe.py` | name/domain/phone normalisation, domain/phone/registration matching, same-name-different-business not merged, history-preserving merge, trade-party exact-name rule |
| `test_pipeline.py` | full website crawl through a mock transport (robots.txt honoured, sitemap, JSON-LD, contacts, specs, prices, raw records, idempotent re-crawl), shipment CSV import (HS/description inference, party resolution, idempotency), company import merging with crawled record, failed jobs isolated (`NotConfigured`, `TermsNotConfirmed`), suppression list |
| `test_scoring_search_api.py` | score components and explanations, natural-language parser on the five example queries, API flow (create → filter → review → contact → lead → exports → NL search → dashboard → source gating), privacy opt-out, auth required |

Status at the time of writing: **28 passed**.

## Frontend checks
```bash
cd frontend && npx tsc --noEmit && npx eslint src && npm run build
```
End-to-end UI was exercised with Playwright against a demo database (login, dashboard, filters, profile tabs, save lead,
log activity, NL search, sources, quality, settings, mobile 390px without horizontal scroll, dark mode, no console errors).

## Acceptance criteria evaluation (real data)
`GET /quality` (Data quality page) or `python -m app.cli evaluate` computes from live rows:
relevant company profiles (target polymer evidence), % with website / business email / phone, pending duplicate rate,
source traceability (companies with ≥ 1 source record) and **classification accuracy** from manual reviews.

Accuracy procedure: on Data quality → *Classification review sample*, mark ≥ 50 random auto-classified rows
Correct/Wrong against their evidence (or confirm/reject on company profiles). Accuracy = correct / reviewed. The
target (≥ 80%) is only reported as met with ≥ 50 reviews.

## User acceptance checklist
- [ ] Import one real trade export and one company list; spot-check 20 records against the source files
- [ ] Crawl 20 known company websites in each of the six markets; review materials/contacts
- [ ] Review 50+ classification samples; record accuracy
- [ ] Resolve pending duplicates; confirm < 5%
- [ ] Run the five example AI-search questions; open each result's evidence
- [ ] Work 10 leads end-to-end in the CRM; export prospect list
- [ ] Submit an opt-out at `/privacy`; confirm the contact disappears and is not re-collected on re-crawl
