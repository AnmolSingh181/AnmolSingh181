# Data sources: connected vs pending

Status reflects what the platform can honestly do **today**. The Data sources page shows live readiness.
In the build environment outbound access to these sites was blocked by network policy, so live API calls
(US Census, UN Comtrade, search APIs, Apollo, ZeroBounce, OpenAI) are implemented to the providers' documented
interfaces but **were not executed against the live services**; run them once after deployment and check the job log.

| Source | Status | Method | What is needed / notes |
|---|---|---|---|
| Company website crawler | **Active** | robots.txt-respecting crawl of home/about/products/contact pages + sitemap | Set `CRAWLER_USER_AGENT` with your contact. Optional Playwright for JS sites |
| Wikidata: PE & petrochemical producers | **Active** (no key) | Official Wikidata Query Service (CC0 open data): companies in active markets producing polyethylene/HDPE/LDPE/LLDPE or in the petrochemical industry; their official websites are queued for crawling | Runs automatically ~1 min after the worker starts, then monthly; also "Start automatic discovery" on the empty dashboard. Covers mainly larger manufacturers; traders/distributors need search discovery. Unverified live in build env |
| GLEIF legal entity register | **Active** (no key) | Official GLEIF API (CC0): active entities in active markets whose legal names contain polymer / polyethylene / plastic / petrochem / resin / recycling / polyolefin / masterbatch | Runs automatically ~3 min after the worker starts, then monthly. Gives legal name, registered address, registration number; no websites/contacts, so these start as low-priority leads. Name-based type (trader/recycler/converter) marked "verify". Unverified live in build env |
| Distributor / partner link following | **Active** (no key) | After each website crawl, links on distributor / dealer / agent / partner pages (or links labelled so) are queued for crawling, up to depth 2 | Linked sites are kept only if they are plastics-related. Settings key `discovery` (`follow_partner_links`, `max_link_depth`, `max_links_per_site`) |
| CSV / Excel import | **Active** | Upload permitted exports; auto column mapping | Use for ImportYeti, Volza, Panjiva, TradeData.Pro, Kompass, directory and trade-fair lists |
| Manual entry | **Active** | UI forms | Entries are attributed to the user and marked confirmed |
| US Census International Trade API | **Active** (key optional) | Official API, HS 390110/390120/390140/391510, monthly, imports & exports by partner | Country-level only (no company names). Unverified live in build env |
| UN Comtrade | **Active** (key optional) | Public preview endpoint (≤ 500 rows) or `COMTRADE_API_KEY` | Country-level only. Reporter codes from `countries.m49_code` (India = 699) |
| Search API discovery | Awaiting credentials | Brave / Serper.dev / SerpAPI / Google Programmable Search | One key. Search result pages are never scraped. Google CSE availability for new customers may be restricted; prefer Brave or Serper |
| ImportYeti | Manual import only | CSV export import | No public self-serve API confirmed; the site is not scraped. API connector activates if a key + endpoint config are obtained |
| Volza | Awaiting credentials | Export import or contract API | Paid. Trial first to validate quality for PE/HS 3901 |
| Panjiva (S&P Global) | Awaiting credentials | Export import or enterprise API | Enterprise pricing, not recommended for MVP budget without a trial |
| TradeData.Pro | Awaiting credentials | Export import or API | Paid. Verify plans |
| Kompass | Awaiting credentials | Data products / API contract | Site is not scraped |
| ENF Plastic | Terms review required | Config-driven directory collector (disabled) | Review terms; if permitted, confirm in UI and configure `list_urls`, `item_selector`, `fields` |
| Plasticker | Terms review required | as above | German marketplace (PE-LD / PE-LLD / PE-HD notation supported) |
| Recycled Plastics Markets Database | Terms review required | as above | North American recycled-plastics buyers |
| EPDA | Terms review required | as above | European distributor members |
| Apollo.io | Awaiting credentials | People API Search (`/api/v1/mixed_people/api_search`, no credits; results masked) + People Enrichment (`/api/v1/people/match`, uses credits) | `APOLLO_API_KEY` created with **Set as master key** (or with those two endpoints). Run params `limit` (companies) and `max_enrich` (credit cap per run, default 25); each person is enriched at most once. Contacts are stored as *likely* decision-makers (title-based). Endpoints overridable via `sources.config.search_url` / `enrich_url`. Unverified live in build env |
| LinkedIn | Manual only | — | Scraping prohibited. Only URLs published on company sites or added by users |
| ZeroBounce | Awaiting credentials | Email verification API | The only path to `email_verified` status |
| OpenAI | Awaiting credentials | Structured extraction (`OPENAI_MODEL`, default gpt-5-mini) | Optional; rules work without it. Budget cap `AI_MONTHLY_BUDGET_USD` |

### Market prices (see [PRICES.md](PRICES.md))

| Source | Status | Method | What is needed / notes |
|---|---|---|---|
| FRED (St. Louis Fed) | **Active** (no key) | Public `fredgraph.csv` download, or official JSON API with `FRED_API_KEY` | US PPI resin indices (monthly), Brent and Henry Hub (daily), Federal Reserve H.10 FX rates used for normalisation. Unverified live in build env |
| Dalian Commodity Exchange (DCE) API | Awaiting credentials | Official DCE data API: token (`apikey` + secret) then `dayQuotes` | `DCE_API_KEY`, `DCE_SECRET`; enable the source. Daily settlement of the highest-open-interest LLDPE / PP / PVC contract (CNY/t, incl. VAT). Review DCE data terms. Unverified live in build env |
| Plastemart (India producer price lists) | Terms review required | Config-driven HTML table reader (robots.txt, rate limit), rows mapped to India series by `config.rules` | Review plastemart.com terms, confirm, enable. Default rules use Reliance grades. Unverified live (site blocked in build env) |
| Price feed URL | **Active** | Polls `config.feed_url` per series (CSV/JSON, field mapping, `${ENV:VAR}` secrets) | For subscription APIs or a sheet your team maintains from producer price circulars |
| Price import & manual entry | **Active** | Market prices page / `POST /prices/import` / `app.cli import-prices` | India producer list prices, PRA exports |
| ICIS, S&P Global Platts, Argus, ChemOrbis, Polymerupdate, SunSirs | Manual import only | Permitted exports, or a feed URL under your contract | Paid price-reporting agencies; not scraped |

## Configuring a trade-database API (when you have a contract)
`PATCH /sources/{id}` with
```json
{"config": {"api": {"url": "https://provider/api/shipments", "auth_header": "Authorization", "auth_prefix": "Bearer ",
  "default_params": {"hs_code": "3901"}, "results_path": "data.items",
  "fields": {"external_id": "id", "shipment_date": "date", "importer_name": "consignee.name",
             "exporter_name": "shipper.name", "hs_code": "hs", "product_description": "description",
             "weight_kg": "weight", "importer_country": "consignee.country", "exporter_country": "shipper.country"}}}}
```
and set the key env var (e.g. `VOLZA_API_KEY`). Field paths come from the provider's documentation.

## Configuring a directory (only after confirming its terms)
Data sources → *Confirm terms* (records who/when/note), then:
```json
{"config": {"list_urls": ["https://directory/category/ldpe?page=1"], "item_selector": ".company",
  "fields": {"name": ".name", "country": ".country", "description": ".desc", "website": "a.web@href"},
  "company_types": ["recycler"], "crawl_websites": true}}
```
The collector stops at the first block/CAPTCHA and never attempts to bypass it.

## HS codes used
| HS | Meaning | Platform mapping |
|---|---|---|
| 3901.10 | PE, specific gravity < 0.94 | LDPE (**ambiguous**: includes some LLDPE) |
| 3901.40 | Ethylene-alpha-olefin copolymers, SG < 0.94 | LLDPE |
| 3901.20 | PE, SG ≥ 0.94 | HDPE |
| 3915.10 | Waste, parings and scrap of ethylene polymers | PE scrap |
| 3901.30 / 3901.90 | EVA / other ethylene polymers | Other PE |

Off-grade and near-prime have **no customs classification**; they are detected from product descriptions only.
National tariff lines (e.g. India ITC-HS 39011010/39011020/39014010) are noted in `materials.notes` as hints: verify
against current schedules.
