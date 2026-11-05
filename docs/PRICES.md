# Market prices: polymer price tracking (India, China, USA, …)

The **Market prices** page (`/prices`) tracks commodity polymer prices (LDPE, LLDPE, HDPE, PP, PVC, PET, PS) and
related feedstocks across markets. It shows them side by side in one display currency/unit and alerts you when they
move.

## What "real time" means here, honestly

There is **no free, official, real-time spot price feed for polymers** in India, the USA or China. Live physical
prices are sold by price-reporting agencies (ICIS, S&P Global Platts, Argus, ChemOrbis, Polymerupdate…). The platform
therefore combines:

| Market | Source in the platform | Freshness | Cost |
|---|---|---|---|
| China | **DCE futures** (LLDPE `l`, PP `pp`, PVC `v`): daily settlement of the most-traded contract, via DCE's official data API | Daily (end of trading day) | DCE API key + secret (register on dce.com.cn) |
| USA | **BLS producer price indices** via FRED: plastic resins (WPU066), thermoplastics (WPU0662), resin manufacturing (PCU325211325211), PE film (WPU072205011) | Monthly, ~2-week lag | Free, no key |
| Global | **Brent crude** (DCOILBRENTEU) and **Henry Hub gas** (DHHNGSP) via FRED: the cost drivers for naphtha-based (Asia) and ethane-based (US) polymers | Daily, few-day lag | Free, no key |
| FX | Federal Reserve H.10 daily rates via FRED (INR, CNY, EUR, GBP, JPY, KRW, THB, MYR, …) + official pegs (AED, SAR, OMR, QAR, BHD) | Daily, few-day lag | Free, no key |
| India | **Producer / distributor list prices** (Reliance, IOCL, GAIL, HPL…), **CFR India** import prices | As often as you enter them | Manual entry, CSV import, or a feed URL |
| USA / China physical | **FAS Houston**, **CFR China** assessments | As your subscription publishes | Your PRA subscription via import or feed URL |

The board refreshes itself every 60 seconds and the worker polls connectors every `price_tracking.refresh_hours`
(default 6 h), so a price appears within minutes of being published, entered or imported. To get genuinely
intraday physical prices, connect a paid feed (below).

## Seeded series

`python -m app.cli seed-reference` creates 18 default series (idempotent, by key): the FRED indices/feedstocks, three
DCE futures series, India producer list prices for LLDPE/HDPE/LDPE film, PP raffia and PVC (INR/kg), and import/export
assessments (CFR India, CFR China, FAS Houston). Series without data appear under **Awaiting data**; nothing is
estimated.

## Getting prices in

1. **Automatic, no key:** start the worker (`python -m app.workers.scheduler`) or click **Refresh now**. FRED series and
   FX rates backfill from `price_tracking.history_start` (default 2021-01-01).
2. **China futures:** set `DCE_API_KEY` and `DCE_SECRET`, then enable the *Dalian Commodity Exchange* source in
   **Data sources**. Review DCE's market-data terms for your use. Base URL / paths can be overridden in the source
   config (`base_url`, `token_path`, `quotes_path`).
3. **Manual entry:** open a series → *Add a price*. Put the basis in the note (e.g. "Reliance circular 41, ex-Mumbai,
   excl. GST").
4. **CSV / Excel import:** *Import CSV* or `python -m app.cli import-prices FILE`:
   ```csv
   series_key,date,price,low,high,note,source_url
   in_lldpe_film_list,2026-10-12,104.5,,,ex-Mumbai excl. GST,
   ```
   Header synonyms are accepted (`value`, `settle`, `close` for price; `observed_at`, `as_of` for date).
5. **Feed URL (CSV / JSON):** set the series' data source to *Feed URL* and its config, for example a Google Sheet your
   team keeps from price circulars (*File → Share → Publish to web → CSV*) or your PRA's API:
   ```json
   {
     "feed_url": "https://api.provider.example/v1/prices?symbol=LLDPE-IN&token=${ENV:PROVIDER_TOKEN}",
     "format": "json",
     "json_path": "data.prices",
     "date_field": "assessed_on",
     "price_field": "mid",
     "low_field": "low",
     "high_field": "high",
     "filter": {"field": "grade", "equals": "LLDPE film"},
     "scale": 1
   }
   ```
   Secrets are always written as `${ENV:NAME}` and read from the environment / `backend/.env`. The API refuses literal
   header values.

## Adding a market or polymer

*Add series* on the page (or `POST /prices/series`): pick material, country, location/basis, price type (futures,
spot, contract, producer_list, assessment, index, feedstock), currency, unit (t, kg, lb, index, bbl, mmbtu), frequency
and data source. Add a manual FX rate on the **FX rates** tab for currencies without an automatic feed (e.g. VND).

## Normalisation

Prices are stored exactly as published. The board and comparison convert at read time:
`price ÷ (source currency per USD) × (target currency per USD)`, using the FX rate in force **on the price date**
(latest rate on or before it), and convert between t / kg / lb. Indices and non-mass units (bbl, mmbtu) are never
converted into USD/t. Remember that bases differ: DCE futures include 13% Chinese VAT, Indian list prices are usually
quoted ex-works excluding GST, CFR prices exclude duties. Compare direction and spreads, not only levels.

## Alerts

Per series: *rises above X*, *falls below X* (on crossing), or *moves by ≥ X %* versus the previous point. Checked when
a new latest point arrives from any route; back-filled history never alerts. Alerts appear under the bell icon and
are POSTed to `ALERT_WEBHOOK_URL` (e.g. an n8n flow → email / WhatsApp / Slack).

## API

| Endpoint | Purpose |
|---|---|
| `GET /prices/board?currency=USD&unit=t&material=LLDPE&country=IN` | Latest price per series, moves (last point, 1W, 1M, 1Y), normalised value, staleness, sparkline, FX table |
| `GET /prices/compare?material=LLDPE&currency=INR&unit=kg&date_from=2026-01-01` | All priced series of one polymer, normalised, for the cross-market chart |
| `GET /prices/series` · `POST /prices/series` · `PATCH /prices/series/{id}` | Manage series |
| `GET /prices/series/{id}/history?date_from=&date_to=&currency=&unit=` | History (+ normalised value) |
| `POST /prices/series/{id}/points` · `DELETE /prices/points/{id}` | Manual price entry / removal (connector data cannot be deleted) |
| `POST /prices/import` (multipart: `file`, optional `series_key`) | CSV/XLSX import |
| `POST /prices/refresh?run_now=false` | Queue all enabled price connectors |
| `GET /prices/fx` · `POST /prices/fx` | FX rates in use / add a manual rate |
| `GET/POST /prices/alerts` · `DELETE /prices/alerts/{id}` | Price alert rules |
| `GET /prices/meta` | Vocabularies and market-data sources |

## Tables

`price_series` (benchmark definition) · `price_points` (observations, unique per series and timestamp, with origin
connector/manual/import, source URL, note, raw record) · `fx_rates` (currency per USD by date) · `price_alert_rules`.
The older `price_observations` table keeps company-specific offers extracted from websites.

## Verification status

The FRED and DCE connectors are built to the providers' documented formats (FRED `fredgraph.csv` / `series/observations`;
DCE token + `dayQuotes` endpoints) and tested against recorded-shape mock responses. Live calls could not be made from
the build environment (outbound network blocked), so check the first job log after deployment
(**Data sources → Jobs**). If DCE changes its API, adjust `base_url`/paths in the source config.
