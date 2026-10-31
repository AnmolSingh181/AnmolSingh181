# Architecture

```
            Browser (Next.js UI)                      Scheduler + worker (python -m app.workers.scheduler)
                  │  /api/* (rewrite, same origin)           │ enqueue on schedule      │ claim jobs (SKIP LOCKED)
                  ▼                                          ▼                          ▼
          FastAPI (app/main.py) ──── services ──── PostgreSQL / Supabase ◄──── connectors (app/connectors)
             auth · search · CRM      classifier · AI validation · dedupe · scoring · contacts · ingestion
```

Data acquisition is fully independent of the frontend: connectors write through `services/ingestion.py`, the UI only
reads/edits via the API. A failing connector fails its own job only.

## Pipeline (every source)

1. **Discovery**: search APIs (`web_search`), directory listings, trade data, imports, manual entry.
2. **Collection**: `PoliteClient` (robots.txt, per-host delay, identifying User-Agent, stops on CAPTCHA/login/anti-bot pages).
3. **Raw storage**: `raw_records` keeps the original text/JSON/CSV row with a content hash (idempotent re-runs).
4. **Extraction**: JSON-LD Organization/Person, mailto/tel links, contact-page lines pairing a name with a job title
   *and* a channel, LinkedIn company URLs, addresses.
5. **Material classification**: `services/classifier.py` using the YAML dictionary
   (`app/data/material_dictionary.yaml`): polymers (LLDPE matched before LDPE; PE-LD/PE-LLD/PE-HD notation), grade
   categories, applications, forms, business types, buyer/seller intent per clause; specs (MFI, density, brand/grade
   no., colour, origin, packaging), quantities and prices only when literally present.
6. **AI (optional)**: `services/ai_classifier.py` with OpenAI strict JSON schema. Every item must quote the source
   verbatim; numbers and grade numbers must appear in the quote; intent without an explicit cue → `needs_review`.
   Modes: `off`, `fallback` (only when rules are inconclusive; default), `always`. Monthly budget cap.
7. **Entity resolution**: `services/dedupe.py` (see rules below).
8. **Contacts**: suppression-list aware upsert; title-based `likely_decision_maker` only.
9. **Insert/merge**: fill empty fields, never overwrite confirmed/rejected reviews; material rows are closed, not deleted.
10. **Lead scoring**: `services/scoring.py`, configurable and explained per component.

### Entity resolution rules
Automatic match requires a strong identifier:
1. registration number + country
2. non-generic company domain (webmail/marketplaces/social excluded) + name not contradictory (token-set ≥ 50)
3. normalised phone + name similarity ≥ 60
4. identical normalised name (or alias) + same country + same city or same address, with no conflicting domain
5. trade-data parties only: identical normalised name + same country when exactly **one** non-conflicting candidate exists

Similar names alone **never** merge; they create `duplicate_candidates` for review (Data quality page). Merging keeps the
merged record (`status='merged'`, `merged_into_id`), moves children, adds aliases and keeps all source records.

## Database structure (29 tables)

| Table | Purpose |
|---|---|
| `countries` | ISO2, M49 (Comtrade), phone prefix, aliases, local-language search terms, `is_active` market flag |
| `materials` | LDPE, LLDPE, HDPE, PE_SCRAP, PE_OTHER with HS codes and synonyms |
| `users`, `user_activity` | accounts/roles (admin, analyst, viewer) and audit log |
| `sources` | registry of every connector: type, access method, status, enabled, terms/pricing notes, config |
| `scrape_jobs` | job queue + history: params, status, attempts, counts, log |
| `raw_records` | untouched collected payloads (hash-unique per source), processing status |
| `companies` | master record: `public_ref` (CMP-0000001), names, location, website/domain, email/phone, registration, lead score + breakdown, status/merge pointer, timestamps, `is_demo` |
| `company_aliases` | alternative/trade/merged names |
| `company_locations` | HQ, plants, warehouses |
| `company_classifications` | manufacturer/producer/trader/distributor/importer/exporter/recycler/processor/converter/scrap_aggregator with evidence + review status |
| `company_materials` | company × polymer × grade × application × relationship, quantities, method, confidence, evidence, review status, `is_current` history |
| `material_specifications` | MFI, density, colour, brand, grade number, form, origin, packaging, each with evidence |
| `price_observations` | price, currency, unit, incoterm, evidence |
| `shipments` | trade records: parties (raw + resolved company), countries, ports, HS, description, inferred material (+ how), quantity/weight/value |
| `trade_statistics` | country-level official flows by HS code and period |
| `company_source_records` | every sighting of a company: source, raw record, URL, extracted data, match method/score |
| `duplicate_candidates` | pairs for human review |
| `contacts` | general vs individual, title, department, decision role, email/phone/LinkedIn, source, verification status, opt-out |
| `contact_verification` | each check (syntax, MX, provider, phone, manual) with result |
| `suppression_list` | SHA-256 of opted-out/deleted emails/phones, never re-collected |
| `privacy_requests` | opt-out / correction / deletion requests |
| `leads`, `lead_activities` | CRM per user: type, stage, priority, interested materials, follow-ups, communication log |
| `company_notes` | internal notes |
| `alerts` | new company, material change, new shipment, job failed (+ webhook delivery flag) |
| `api_usage` | calls/tokens/estimated cost per provider |
| `classification_reviews` | manual QA sample for accuracy measurement |
| `app_settings` | lead-scoring weights/tiers, refresh schedule |

Controlled vocabularies are `text` + `CHECK` constraints (see `app/enums.py`), so adding a value is one migration.
Full DDL: `db/schema.sql` (generated) or `backend/migrations/versions/`.

## Extending
- **New country**: add a row to `COUNTRIES` in `app/data/reference.py`, run `seed-reference`, toggle it active in Settings.
- **New material**: add to `MATERIALS` (+ HS map) and patterns to `material_dictionary.yaml`.
- **New terminology**: edit `material_dictionary.yaml` (no code change).
- **New source**: add to `SOURCES`; if it needs bespoke logic, subclass `BaseConnector` and register it in `connectors/registry.py`.

## Lead scoring (default weights, editable in Settings)
| Component | Weight | Evidence used |
|---|---:|---|
| Material relevance | 30 | target polymers, target grades/applications, multiple polymers, published specs |
| Verified buying/selling activity | 25 | manual confirmation, shipments, trade data, stated intent (lower if unconfirmed) |
| International trade activity | 20 | shipment count (24-month recency), importer/exporter classification |
| Contact completeness | 15 | website, email, phone, relevant individual, LinkedIn |
| Data recency | 10 | days since last seen/verified |

Tiers: 80–100 High priority · 60–79 Relevant · 40–59 Needs verification · <40 Low priority. The score is a research
prioritisation aid, **not** a probability of conversion; each component's reasons are shown on the profile.
