# API reference

Interactive docs: `GET /docs` (Swagger UI) and `/redoc` on the backend. Machine-readable spec: [`openapi.json`](openapi.json).
All endpoints except `/health`, `/auth/login` and `POST /privacy/requests` require `Authorization: Bearer <token>`.
Roles: **admin** (sources, settings, users, privacy), **analyst** (edit data, CRM), **viewer** (read).

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login` · `GET /auth/me` · `GET/POST /auth/users` (admin) |
| Dashboard & meta | `GET /dashboard` · `GET /meta` (vocabularies, countries, materials, sources) · `PATCH /countries/{code}` |
| Company discovery | `GET /companies` (query filters below) · `POST /companies/search` (same filters as JSON) · `GET /companies/export.csv` |
| Company profile | `GET/PATCH /companies/{id}` · `POST /companies` (manual) · `POST /companies/{id}/notes` · `POST /companies/{id}/materials` · `POST /companies/{id}/classifications` · `POST /companies/{id}/recrawl` · `POST /companies/{id}/rescore` · `POST /company-materials/{id}/review` |
| Contacts | `GET /contacts` · `POST /companies/{id}/contacts` · `PATCH/DELETE /contacts/{id}` · `POST /contacts/{id}/verify` · `POST /contacts/{id}/manual-verify` |
| Trade | `GET /shipments` · `GET /shipments/relationships` · `GET /trade-stats` |
| CRM | `GET/POST /leads` · `PATCH/DELETE /leads/{id}` · `POST /leads/{id}/activities` · `GET /leads/export.csv` |
| AI search | `POST /search/nl` `{query}` → interpreted filters + database results with evidence |
| Sources & jobs | `GET /sources` · `PATCH /sources/{id}` (enable, config, `confirm_terms`) · `POST /sources/{key}/run` · `GET /jobs` · `POST /jobs/{id}/retry` · `POST /jobs/{id}/cancel` · `POST /imports` (multipart: file, kind, origin_source, mapping) |
| Quality | `GET /quality` (acceptance metrics) · `GET /quality/review-sample` · `GET /duplicates` · `POST /duplicates/{id}/merge` · `POST /duplicates/{id}/reject` |
| Settings | `GET/PUT /settings/{lead_scoring,refresh_schedule}` · `POST /admin/rescore` |
| Alerts | `GET /alerts` · `POST /alerts/read-all` |
| Privacy | `POST /privacy/requests` (public) · `GET /privacy/requests` · `POST /privacy/requests/{id}/resolve` |

### Company filters (`GET /companies`)
Repeat a parameter for multiple values (`?country=IN&country=VN`).

`q, country[], city, polymer[], polymer_match=any|all, grade[], application[], relationship[] (buyer|seller|both|manufacturer|historical_*),
company_type[], trade_role[] (importer|exporter), has_contacts, has_email, has_phone, has_website, has_decision_maker,
contact_title, contact_verification[], min_score, max_score, tier[], source[], sort=score|name|discovered|verified|country,
order=asc|desc, page, page_size`

Polymer, grade, application and relationship filters must all hold on the **same** material record. `relationship=buyer`
includes `both` and `historical_buyer`; `seller` includes `both`, `manufacturer`, `historical_seller`; `grade=recycled`
includes PCR, PIR and reprocessed.

### Example
```bash
curl -s -X POST localhost:8000/auth/login -H 'content-type: application/json' -d '{"email":"you@co.com","password":"..."}'
```
```bash
curl -s "localhost:8000/companies?polymer=LLDPE&grade=virgin_prime&application=film&relationship=seller&country=US" -H "Authorization: Bearer $TOKEN"
```
```bash
curl -s -X POST localhost:8000/search/nl -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"query":"recycled HDPE buyers in Vietnam"}'
```
