"""Reference data seeded by `python -m app.cli seed-reference`. Edit here (or in the DB) to add
countries, materials or sources - no code changes elsewhere are required."""

# ISO2, name, region, active, priority, UN M49 (Comtrade reporter code), phone prefix, aliases, local search terms
COUNTRIES = [
    ("US", "United States", "North America", True, 1, 842, "1", ["USA", "U.S.", "U.S.A.", "United States of America", "America"], {}),
    ("CN", "China", "East Asia", True, 2, 156, "86", ["PRC", "People's Republic of China", "Mainland China"],
     {"LDPE": ["低密度聚乙烯"], "LLDPE": ["线性低密度聚乙烯"], "HDPE": ["高密度聚乙烯"], "recycled": ["再生料", "回收料"]}),
    ("VN", "Vietnam", "Southeast Asia", True, 3, 704, "84", ["Viet Nam"],
     {"recycled": ["hạt nhựa tái chế"], "LDPE": ["hạt nhựa LDPE"]}),
    ("AE", "United Arab Emirates", "Middle East", True, 4, 784, "971", ["UAE", "U.A.E.", "Emirates", "Dubai", "Sharjah", "Abu Dhabi"], {}),
    ("SA", "Saudi Arabia", "Middle East", True, 5, 682, "966", ["KSA", "Kingdom of Saudi Arabia", "Saudi"], {}),
    ("IN", "India", "South Asia", True, 6, 699, "91", ["Bharat"], {}),
    # Expansion markets (activate in the Sources/Countries admin when ready)
    ("TR", "Turkey", "Europe/Middle East", False, 10, 792, "90", ["Türkiye", "Turkiye"], {}),
    ("TH", "Thailand", "Southeast Asia", False, 11, 764, "66", [], {}),
    ("MY", "Malaysia", "Southeast Asia", False, 12, 458, "60", [], {}),
    ("ID", "Indonesia", "Southeast Asia", False, 13, 360, "62", [], {}),
    ("KR", "South Korea", "East Asia", False, 14, 410, "82", ["Korea", "Republic of Korea"], {}),
    ("DE", "Germany", "Europe", False, 15, 276, "49", ["Deutschland"], {"recycled": ["Regranulat", "Mahlgut"]}),
    ("NL", "Netherlands", "Europe", False, 16, 528, "31", ["Holland", "The Netherlands"], {}),
    ("OM", "Oman", "Middle East", False, 20, 512, "968", [], {}),
    ("QA", "Qatar", "Middle East", False, 21, 634, "974", [], {}),
    ("KW", "Kuwait", "Middle East", False, 22, 414, "965", [], {}),
    ("BH", "Bahrain", "Middle East", False, 23, 48, "973", [], {}),
    ("PK", "Pakistan", "South Asia", False, 24, 586, "92", [], {}),
    ("BD", "Bangladesh", "South Asia", False, 25, 50, "880", [], {}),
    ("EG", "Egypt", "Africa", False, 26, 818, "20", [], {}),
    ("GB", "United Kingdom", "Europe", False, 27, 826, "44", ["UK", "U.K.", "Britain", "England"], {}),
    ("BE", "Belgium", "Europe", False, 28, 56, "32", [], {}),
    ("IT", "Italy", "Europe", False, 29, 380, "39", [], {}),
    ("ES", "Spain", "Europe", False, 30, 724, "34", [], {}),
    ("PL", "Poland", "Europe", False, 31, 616, "48", [], {}),
    ("FR", "France", "Europe", False, 32, 251, "33", [], {}),
    ("SG", "Singapore", "Southeast Asia", False, 33, 702, "65", [], {}),
    ("TW", "Taiwan", "East Asia", False, 34, 490, "886", [], {}),
    ("JP", "Japan", "East Asia", False, 35, 392, "81", [], {}),
    ("MX", "Mexico", "North America", False, 36, 484, "52", [], {}),
    ("CA", "Canada", "North America", False, 37, 124, "1", [], {}),
    ("BR", "Brazil", "South America", False, 38, 76, "55", [], {}),
]

# HS 2022 headings. LDPE and LLDPE share 3901.10 at HS6 (specific gravity < 0.94);
# 3901.40 (ethylene-alpha-olefin copolymers, SG < 0.94) is predominantly LLDPE.
# National tariff lines are listed as "verify" hints - confirm against the current national schedule.
MATERIALS = [
    {
        "code": "LDPE", "name": "Low-Density Polyethylene", "family": "polyethylene", "is_target": True,
        "hs_codes": ["390110"],
        "synonyms": ["low density polyethylene", "PE-LD", "LD-PE", "LDPE"],
        "notes": "HS 3901.10 also covers LLDPE homopolymer-like grades. India ITC-HS 39011020 (LDPE) - verify.",
    },
    {
        "code": "LLDPE", "name": "Linear Low-Density Polyethylene", "family": "polyethylene", "is_target": True,
        "hs_codes": ["390140", "390110"],
        "synonyms": ["linear low density polyethylene", "PE-LLD", "LLDPE", "mLLDPE", "metallocene LLDPE"],
        "notes": "Mostly HS 3901.40 (ethylene-alpha-olefin copolymers SG<0.94). India ITC-HS 39011010 / 39014010 (LLDPE) - verify.",
    },
    {
        "code": "HDPE", "name": "High-Density Polyethylene", "family": "polyethylene", "is_target": True,
        "hs_codes": ["390120"],
        "synonyms": ["high density polyethylene", "PE-HD", "HD-PE", "HDPE", "HMWPE"],
        "notes": "HS 3901.20: polyethylene having a specific gravity of 0.94 or more.",
    },
    {
        "code": "PE_SCRAP", "name": "Polyethylene waste, parings and scrap", "family": "polyethylene", "is_target": True,
        "hs_codes": ["391510"],
        "synonyms": ["PE scrap", "polyethylene scrap", "PE waste"],
        "notes": "HS 3915.10 covers scrap of all ethylene polymers (LDPE/LLDPE/HDPE not separated).",
    },
    {
        "code": "PE_OTHER", "name": "Other polyethylene / ethylene polymers", "family": "polyethylene", "is_target": False,
        "hs_codes": ["390130", "390190"],
        "synonyms": ["EVA", "ethylene vinyl acetate", "MDPE", "medium density polyethylene", "UHMWPE"],
        "notes": "3901.30 EVA copolymers, 3901.90 other ethylene polymers.",
    },
    # Other commodity polymers - tracked for market prices only (not lead-scoring targets).
    {
        "code": "PP", "name": "Polypropylene", "family": "polypropylene", "is_target": False,
        "hs_codes": ["390210"], "synonyms": ["polypropylene", "PP homopolymer", "PP raffia", "PP copolymer"],
        "notes": "HS 3902.10 polypropylene; 3902.30 propylene copolymers. Tracked for market prices.",
    },
    {
        "code": "PVC", "name": "Polyvinyl Chloride", "family": "vinyl", "is_target": False,
        "hs_codes": ["390410"], "synonyms": ["polyvinyl chloride", "PVC resin", "S-PVC", "suspension PVC"],
        "notes": "HS 3904.10 PVC not mixed with other substances. Tracked for market prices.",
    },
    {
        "code": "PET", "name": "Polyethylene Terephthalate", "family": "polyester", "is_target": False,
        "hs_codes": ["390761"], "synonyms": ["PET resin", "bottle grade PET", "polyethylene terephthalate"],
        "notes": "HS 3907.61 PET, viscosity number >= 78 ml/g (bottle grade). Tracked for market prices.",
    },
    {
        "code": "PS", "name": "Polystyrene", "family": "styrenic", "is_target": False,
        "hs_codes": ["390311", "390319"], "synonyms": ["polystyrene", "GPPS", "HIPS", "EPS"],
        "notes": "HS 3903.11 expansible PS, 3903.19 other PS. Tracked for market prices.",
    },
]

# HS6 -> material code + whether the mapping is ambiguous. Description-based classification wins.
HS_MATERIAL_MAP = {
    "390110": ("LDPE", True),   # LDPE or LLDPE
    "390140": ("LLDPE", False),
    "390120": ("HDPE", False),
    "391510": ("PE_SCRAP", False),
    "390130": ("PE_OTHER", False),
    "390190": ("PE_OTHER", False),
}

# Source registry. Status reflects what the platform can honestly do today:
#  active                - works with no credentials (subject to network/terms)
#  awaiting_credentials  - connector implemented, needs API key / contract
#  requires_terms_review - site terms not yet confirmed to permit automated collection; disabled until an admin confirms
#  manual_only           - use permitted exports via CSV import
SOURCES = [
    # --- discovery / websites
    dict(key="web_search", name="Search API discovery (Brave / Serper / SerpAPI / Google CSE)", source_type="search_api",
         access_method="api", base_url=None, status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["BRAVE_SEARCH_API_KEY", "SERPER_API_KEY", "SERPAPI_API_KEY", "GOOGLE_CSE_API_KEY"],
         refresh_interval_days=7,
         terms_notes="Uses official search APIs only (no scraping of search result pages).",
         pricing_notes="Brave Search API, Serper.dev and SerpAPI offer free/low-cost tiers; check current pricing before enabling."),
    dict(key="company_website", name="Company website crawler", source_type="website", access_method="scrape",
         base_url=None, status="active", requires_credentials=False, credential_env_vars=[], refresh_interval_days=45,
         terms_notes="Respects robots.txt, rate-limited (CRAWLER_MIN_DELAY_SECONDS), identifies itself via CRAWLER_USER_AGENT, "
                     "stops on CAPTCHA / login / anti-bot challenge pages. Only public business pages are fetched."),
    dict(key="wikidata", name="Wikidata: PE & petrochemical producers (open data)", source_type="directory",
         access_method="api", base_url="https://www.wikidata.org/", status="active", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=30,
         terms_notes="CC0 open data via the official Wikidata Query Service (identifying User-Agent, rate-limited). "
                     "Finds polyethylene / petrochemical producers in active markets and queues their official websites "
                     "for crawling. No key needed."),
    dict(key="gleif", name="GLEIF legal entity register (open data)", source_type="government",
         access_method="api", base_url="https://www.gleif.org/", status="active", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=30,
         terms_notes="Official Global LEI register, CC0 open data via the public GLEIF API (no key, ~60 requests/min). "
                     "Finds active companies in active markets whose legal names contain plastics keywords. Provides legal "
                     "name, registered address and registration number; no websites or contacts."),
    # --- trade databases
    dict(key="importyeti", name="ImportYeti", source_type="trade_database", access_method="export_import",
         base_url="https://www.importyeti.com/", status="manual_only", requires_credentials=True,
         credential_env_vars=["IMPORTYETI_API_KEY"], refresh_interval_days=7,
         terms_notes="US Customs bill-of-lading data. No public self-serve API was confirmed; automated scraping of the site is not "
                     "performed. Import permitted CSV exports via Data Sources > Import. API connector activates if a key/contract is obtained.",
         pricing_notes="Free web search; paid plans for bulk/export - verify current terms."),
    dict(key="volza", name="Volza", source_type="trade_database", access_method="export_import",
         base_url="https://www.volza.com/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["VOLZA_API_KEY"], refresh_interval_days=30,
         terms_notes="Commercial subscription with API add-on. Import Excel/CSV exports or configure API key.",
         pricing_notes="Paid. Validate data quality with a trial before purchasing."),
    dict(key="panjiva", name="Panjiva (S&P Global)", source_type="trade_database", access_method="export_import",
         base_url="https://panjiva.com/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["PANJIVA_API_KEY"], refresh_interval_days=30,
         terms_notes="Enterprise subscription; API via S&P Global Market Intelligence. Import permitted exports.",
         pricing_notes="Enterprise pricing - not recommended for the MVP budget without a trial."),
    dict(key="tradedata_pro", name="TradeData.Pro", source_type="trade_database", access_method="export_import",
         base_url="https://tradedata.pro/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["TRADEDATA_PRO_API_KEY"], refresh_interval_days=30,
         terms_notes="Paid plans; import permitted exports or configure API access per their documentation.",
         pricing_notes="Paid - verify current plans."),
    # --- government / official
    dict(key="us_census", name="US Census Bureau International Trade API", source_type="government", access_method="api",
         base_url="https://api.census.gov/data/timeseries/intltrade", status="active", requires_credentials=False,
         credential_env_vars=["CENSUS_API_KEY"], refresh_interval_days=30,
         terms_notes="Official public API. Country-level monthly import/export values by HS code (no company names). Key optional.",
         pricing_notes="Free."),
    dict(key="un_comtrade", name="UN Comtrade", source_type="government", access_method="api",
         base_url="https://comtradeapi.un.org/", status="active", requires_credentials=False,
         credential_env_vars=["COMTRADE_API_KEY"], refresh_interval_days=30,
         terms_notes="Official API. Without a key the public preview endpoint (max 500 rows) is used; free key raises limits.",
         pricing_notes="Free tier available; premium tiers for bulk."),
    # --- directories
    dict(key="enf_plastic", name="ENF Plastic", source_type="directory", access_method="scrape",
         base_url="https://www.enfplastic.com/", status="requires_terms_review", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=60,
         terms_notes="Directory of plastic recyclers/processors. Terms of use must be reviewed and permission confirmed before enabling "
                     "automated collection. Until then use manual research + CSV import."),
    dict(key="plasticker", name="Plasticker", source_type="directory", access_method="scrape",
         base_url="https://plasticker.de/", status="requires_terms_review", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=30,
         terms_notes="German plastics marketplace/directory (uses PE-LD/PE-LLD/PE-HD notation). Review terms before enabling."),
    dict(key="plastics_markets", name="Recycled Plastics Markets Database", source_type="directory", access_method="scrape",
         base_url="https://www.plasticsmarkets.org/", status="requires_terms_review", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=60,
         terms_notes="North American recycled-plastics buyers database. Review terms before enabling."),
    dict(key="epda", name="EPDA - European Plastics Distributors Association", source_type="directory", access_method="scrape",
         base_url="https://www.epda.com/", status="requires_terms_review", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=90,
         terms_notes="Member distributor list. Review terms before enabling."),
    dict(key="kompass", name="Kompass", source_type="directory", access_method="api",
         base_url="https://www.kompass.com/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["KOMPASS_API_KEY"], refresh_interval_days=60,
         terms_notes="B2B directory. Site scraping is not performed; use Kompass data products/API under contract or permitted exports.",
         pricing_notes="Paid data products."),
    # --- enrichment
    dict(key="apollo", name="Apollo.io", source_type="enrichment", access_method="api",
         base_url="https://api.apollo.io/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["APOLLO_API_KEY"], refresh_interval_days=30,
         terms_notes="People/organisation search via official API under your Apollo plan. Results stored with source=apollo and "
                     "decision_role=likely_decision_maker (title-based), never confirmed automatically.",
         pricing_notes="Free tier with limited credits; paid tiers for API volume."),
    dict(key="linkedin", name="LinkedIn", source_type="enrichment", access_method="manual",
         base_url="https://www.linkedin.com/", status="manual_only", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="LinkedIn prohibits scraping. Only URLs published on company websites or added manually are stored."),
    dict(key="zerobounce", name="ZeroBounce email verification", source_type="enrichment", access_method="api",
         base_url="https://api.zerobounce.net/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["ZEROBOUNCE_API_KEY"], refresh_interval_days=30,
         terms_notes="Authorised email verification provider. Only this provider can set 'email_verified'.",
         pricing_notes="Pay-per-credit; small free allowance."),
    # --- market prices
    dict(key="fred", name="FRED (St. Louis Fed): US resin price indices, crude oil, natural gas, FX",
         source_type="market_data", access_method="api", base_url="https://fred.stlouisfed.org/", status="active",
         requires_credentials=False, credential_env_vars=["FRED_API_KEY"], refresh_interval_days=1,
         terms_notes="Official public data (BLS producer price indices, EIA energy prices, Federal Reserve H.10 exchange "
                     "rates) via FRED. Works without a key using the public CSV download; a free FRED_API_KEY uses the "
                     "official JSON API. PPI series are monthly indices (not USD/t prices); FX rates are published "
                     "with a few days' lag.",
         pricing_notes="Free."),
    dict(key="dce", name="Dalian Commodity Exchange (DCE) API: LLDPE / PP / PVC futures", source_type="market_data",
         access_method="api", base_url="http://www.dce.com.cn/", status="awaiting_credentials",
         requires_credentials=True, credential_env_vars=["DCE_API_KEY", "DCE_SECRET"], refresh_interval_days=1,
         terms_notes="Official DCE data API (key + secret issued by DCE after registration on dce.com.cn). Daily "
                     "settlement prices of the most-traded (highest open interest) contract for LLDPE (l), PP (pp) "
                     "and PVC (v) in CNY/t. Review DCE's market-data terms for your intended use (internal analysis vs. "
                     "redistribution) before enabling.",
         pricing_notes="Verify current DCE API access conditions."),
    dict(key="price_feed", name="Price feed URL (CSV / JSON)", source_type="market_data", access_method="api",
         base_url=None, status="active", requires_credentials=False, credential_env_vars=[], refresh_interval_days=1,
         terms_notes="Polls the feed URL configured on each price series (series config: feed_url, format, field names). "
                     "Use for a price-reporting agency's API/export under your subscription, or a sheet your team "
                     "maintains from producer price circulars (e.g. a published Google Sheet CSV). Secrets are referenced "
                     "as ${ENV:VAR_NAME} and read from the environment, never stored in the database."),
    dict(key="plastemart", name="Plastemart: Indian producer polymer price lists (PE / PP / PVC)",
         source_type="market_data", access_method="scrape",
         base_url="https://www.plastemart.com/polymer-price-list-pe-pp-pvc", status="requires_terms_review",
         requires_credentials=False, credential_env_vars=[], refresh_interval_days=1,
         terms_notes="Public price-list page of Indian producer prices (Reliance, IOCL, GAIL, HPL, ...). Disabled until an "
                     "admin reviews plastemart.com's terms of use and confirms automated collection is permitted. "
                     "Respects robots.txt, rate-limited, identifies itself. Table rows are mapped to the India "
                     "producer-list series by config.rules (default: Reliance film / raffia / PVC grades); unmatched "
                     "rows are logged, not stored. Rows need a price and an effective date (date column or "
                     "'w.e.f.' near the table). Revision notices (e.g. '+INR 2000/MT') are not converted into prices."),
    dict(key="price_import", name="Price CSV / Excel import & manual entry", source_type="manual_import",
         access_method="export_import", base_url=None, status="active", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Upload price histories (series_key, date, price[, low, high, note, source_url]) from permitted "
                     "exports, or type in prices from producer/distributor price circulars on the Market prices page."),
    dict(key="icis", name="ICIS (LSEG)", source_type="market_data", access_method="export_import",
         base_url="https://www.icis.com/", status="manual_only", requires_credentials=True, credential_env_vars=[],
         refresh_interval_days=None,
         terms_notes="Price-reporting agency: polyolefin, PVC, PET assessments for Asia, India, US, Europe. Subscription "
                     "data - import permitted exports, or configure a price_feed series if your contract includes an API.",
         pricing_notes="Paid subscription."),
    dict(key="platts", name="S&P Global Commodity Insights (Platts)", source_type="market_data",
         access_method="export_import", base_url="https://www.spglobal.com/commodityinsights/", status="manual_only",
         requires_credentials=True, credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Price-reporting agency (polymer assessments incl. CFR India, CFR China, FAS Houston). Subscription "
                     "data - import permitted exports or configure a price_feed series under your API contract.",
         pricing_notes="Paid subscription."),
    dict(key="argus", name="Argus Media", source_type="market_data", access_method="export_import",
         base_url="https://www.argusmedia.com/", status="manual_only", requires_credentials=True,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Price-reporting agency (petrochemicals/polymers). Import permitted exports or configure a price_feed "
                     "series under your contract.", pricing_notes="Paid subscription."),
    dict(key="chemorbis", name="ChemOrbis", source_type="market_data", access_method="export_import",
         base_url="https://www.chemorbis.com/", status="manual_only", requires_credentials=True,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Weekly/daily polymer prices for China, India, SE Asia, Turkey, Europe. Import permitted exports.",
         pricing_notes="Paid subscription."),
    dict(key="polymerupdate", name="Polymerupdate (India)", source_type="market_data", access_method="export_import",
         base_url="https://www.polymerupdate.com/", status="manual_only", requires_credentials=True,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Indian domestic polymer prices (producer list prices, distributor prices). Import permitted "
                     "exports or configure a price_feed series if your plan includes data access.",
         pricing_notes="Paid subscription."),
    dict(key="sunsirs", name="SunSirs / 100ppi (China spot)", source_type="market_data", access_method="export_import",
         base_url="https://www.sunsirs.com/", status="manual_only", requires_credentials=False,
         credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Chinese domestic spot benchmark prices (LLDPE, HDPE, LDPE, PP, PVC). Automated collection is not "
                     "performed; enter prices manually or import permitted exports.",
         pricing_notes="Free web pages; data services paid - verify terms."),
    # --- manual / AI
    dict(key="csv_import", name="CSV / Excel import", source_type="manual_import", access_method="export_import",
         base_url=None, status="active", requires_credentials=False, credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Upload permitted exports (trade databases, directories, trade-fair lists, your own CRM)."),
    dict(key="manual", name="Manual entry", source_type="manual_import", access_method="manual",
         base_url=None, status="active", requires_credentials=False, credential_env_vars=[], refresh_interval_days=None),
    dict(key="openai", name="OpenAI classification", source_type="ai", access_method="api",
         base_url="https://api.openai.com/", status="awaiting_credentials", requires_credentials=True,
         credential_env_vars=["OPENAI_API_KEY"], refresh_interval_days=None,
         terms_notes="Used only for structured extraction from collected text; outputs are validated against source evidence.",
         pricing_notes="Pay per token. Monthly budget cap: AI_MONTHLY_BUDGET_USD."),
    dict(key="demo", name="Demo data (synthetic)", source_type="manual_import", access_method="manual",
         base_url=None, status="disabled", requires_credentials=False, credential_env_vars=[], refresh_interval_days=None,
         terms_notes="Synthetic records for APP_ENV=demo only. Never shown in production."),
]

# Default market price series. Seeded idempotently by key; admins can add more on the Market prices page.
# Series with source "price_import" have no automatic feed: fill them by manual entry / import or attach a feed URL.
PRICE_SERIES = [
    # USA - official indices and energy (FRED, key-free)
    dict(key="us_ppi_plastic_resins", name="US PPI: Plastic resins & materials", material=None, country_code="US",
         location="United States", price_type="index", currency=None, unit="index", frequency="monthly", source="fred",
         external_code="WPU066", notes="BLS producer price index, 1982=100, not seasonally adjusted."),
    dict(key="us_ppi_thermoplastic", name="US PPI: Thermoplastic resins & plastics materials", material=None,
         country_code="US", location="United States", price_type="index", currency=None, unit="index",
         frequency="monthly", source="fred", external_code="WPU0662",
         notes="BLS producer price index, 1982=100. Covers PE, PP, PVC, PS, PET and other thermoplastics."),
    dict(key="us_ppi_resin_mfg", name="US PPI: Plastics material & resin manufacturing (industry)", material=None,
         country_code="US", location="United States", price_type="index", currency=None, unit="index",
         frequency="monthly", source="fred", external_code="PCU325211325211",
         notes="BLS PPI by industry, NAICS 325211."),
    dict(key="us_ppi_pe_film", name="US PPI: Unlaminated polyethylene film & sheet", material=None, country_code="US",
         location="United States", price_type="index", currency=None, unit="index", frequency="monthly", source="fred",
         external_code="WPU072205011", notes="Converted-product index (PE film), a demand-side signal for PE resin."),
    dict(key="brent_spot", name="Brent crude oil spot (FOB Europe)", material=None, country_code=None,
         location="Europe (Brent)", price_type="feedstock", currency="USD", unit="bbl", frequency="daily", source="fred",
         external_code="DCOILBRENTEU", notes="EIA via FRED. Naphtha-based Asian polymer costs track crude."),
    dict(key="henry_hub_gas", name="Henry Hub natural gas spot", material=None, country_code="US",
         location="Henry Hub, Louisiana", price_type="feedstock", currency="USD", unit="mmbtu", frequency="daily",
         source="fred", external_code="DHHNGSP", notes="EIA via FRED. US ethane-based PE costs track natural gas."),
    # China - exchange futures (DCE API, needs DCE key/secret)
    dict(key="dce_lldpe", name="China LLDPE futures, DCE main contract", material="LLDPE", country_code="CN",
         location="Dalian Commodity Exchange", price_type="futures", currency="CNY", unit="t", frequency="daily",
         source="dce", external_code="l", grade="LLDPE film (exchange deliverable)",
         notes="Daily settlement price of the highest open-interest contract. Prices include 13% VAT."),
    dict(key="dce_pp", name="China PP futures, DCE main contract", material="PP", country_code="CN",
         location="Dalian Commodity Exchange", price_type="futures", currency="CNY", unit="t", frequency="daily",
         source="dce", external_code="pp", grade="PP raffia (exchange deliverable)",
         notes="Daily settlement price of the highest open-interest contract. Prices include 13% VAT."),
    dict(key="dce_pvc", name="China PVC futures, DCE main contract", material="PVC", country_code="CN",
         location="Dalian Commodity Exchange", price_type="futures", currency="CNY", unit="t", frequency="daily",
         source="dce", external_code="v", grade="S-PVC (exchange deliverable)",
         notes="Daily settlement price of the highest open-interest contract. Prices include 13% VAT."),
    # India - producer list prices (no free official feed: manual entry, import, or a price_feed URL)
    dict(key="in_lldpe_film_list", name="India LLDPE film, producer list price", material="LLDPE", country_code="IN",
         location="ex-Mumbai", price_type="producer_list", currency="INR", unit="kg", frequency="weekly",
         source="price_import", grade="LLDPE film (butene)",
         notes="Reliance benchmark grade. Filled by the Plastemart connector once enabled, or enter from "
               "producer/distributor price circulars (Reliance, IOCL, GAIL, HPL...). State basis (ex-works / "
               "delivered, incl. or excl. GST) in the note of each price."),
    dict(key="in_hdpe_film_list", name="India HDPE film, producer list price", material="HDPE", country_code="IN",
         location="ex-Mumbai", price_type="producer_list", currency="INR", unit="kg", frequency="weekly",
         source="price_import", grade="HDPE film", notes="Enter from producer/distributor price circulars."),
    dict(key="in_ldpe_film_list", name="India LDPE film, producer list price", material="LDPE", country_code="IN",
         location="ex-Mumbai", price_type="producer_list", currency="INR", unit="kg", frequency="weekly",
         source="price_import", grade="LDPE film", notes="Enter from producer/distributor price circulars."),
    dict(key="in_pp_raffia_list", name="India PP raffia, producer list price", material="PP", country_code="IN",
         location="ex-Mumbai", price_type="producer_list", currency="INR", unit="kg", frequency="weekly",
         source="price_import", grade="PP raffia homopolymer", notes="Enter from producer/distributor price circulars."),
    dict(key="in_pvc_list", name="India PVC suspension, producer list price", material="PVC", country_code="IN",
         location="ex-works", price_type="producer_list", currency="INR", unit="kg", frequency="weekly",
         source="price_import", grade="S-PVC K67", notes="Enter from producer/distributor price circulars."),
    # USA - physical market (subscription data: manual entry / import / price_feed)
    dict(key="us_lldpe_export", name="US LLDPE film export price, FAS Houston", material="LLDPE", country_code="US",
         location="FAS Houston", price_type="assessment", currency="USD", unit="t", incoterm="FAS", frequency="weekly",
         source="price_import", grade="LLDPE butene film",
         notes="Enter from your price-reporting subscription (ICIS / Platts / Argus / CDI) or connect a price feed."),
    dict(key="us_hdpe_export", name="US HDPE blow moulding export price, FAS Houston", material="HDPE",
         country_code="US", location="FAS Houston", price_type="assessment", currency="USD", unit="t", incoterm="FAS",
         frequency="weekly", source="price_import", grade="HDPE blow moulding",
         notes="Enter from your price-reporting subscription or connect a price feed."),
    # China - physical import market
    dict(key="cn_lldpe_cfr", name="China LLDPE film import price, CFR China", material="LLDPE", country_code="CN",
         location="CFR China main ports", price_type="assessment", currency="USD", unit="t", incoterm="CFR",
         frequency="weekly", source="price_import", grade="LLDPE butene film",
         notes="Enter from your price-reporting subscription or connect a price feed."),
    dict(key="in_lldpe_cfr", name="India LLDPE film import price, CFR India", material="LLDPE", country_code="IN",
         location="CFR Nhava Sheva", price_type="assessment", currency="USD", unit="t", incoterm="CFR",
         frequency="weekly", source="price_import", grade="LLDPE butene film",
         notes="Enter from your price-reporting subscription or connect a price feed."),
]

# FRED H.10 exchange-rate series used to normalise prices. invert=True: series is USD per unit of currency.
FX_SERIES = {
    "INR": ("DEXINUS", False), "CNY": ("DEXCHUS", False), "EUR": ("DEXUSEU", True), "GBP": ("DEXUSUK", True),
    "JPY": ("DEXJPUS", False), "KRW": ("DEXKOUS", False), "THB": ("DEXTHUS", False), "MYR": ("DEXMAUS", False),
    "MXN": ("DEXMXUS", False), "BRL": ("DEXBZUS", False), "CAD": ("DEXCAUS", False), "TWD": ("DEXTAUS", False),
    "SGD": ("DEXSIUS", False),
}

DEFAULT_SETTINGS = {
    "lead_scoring": {
        "weights": {
            "material_relevance": 30,
            "trading_activity": 25,
            "international_trade": 20,
            "contact_completeness": 15,
            "data_recency": 10,
        },
        "tiers": [
            {"min": 80, "label": "High priority"},
            {"min": 60, "label": "Relevant"},
            {"min": 40, "label": "Needs verification"},
            {"min": 0, "label": "Low priority"},
        ],
        "target_polymers": ["LDPE", "LLDPE", "HDPE", "PE_SCRAP"],
        "target_grade_categories": ["virgin_prime", "near_prime", "off_grade", "off_spec", "non_prime_unspecified",
                                    "recycled", "reprocessed", "pcr", "pir"],
        "target_applications": ["film", "extrusion", "blow_moulding", "injection_moulding"],
        "decision_maker_titles": ["procurement", "purchas", "buyer", "sourcing", "sales", "export", "import",
                                  "commercial", "managing director", "business development", "ceo", "owner", "director"],
    },
    "discovery": {
        "follow_partner_links": True,   # crawl companies linked from distributor / agent / partner pages
        "max_link_depth": 2,            # manufacturer -> distributor -> distributor's partners
        "max_links_per_site": 40,
    },
    "price_tracking": {
        "refresh_hours": 6,             # how often the worker polls price connectors (FRED, DCE, feed URLs)
        "history_start": "2021-01-01",  # first-run backfill start for connectors that support history
        # Fixed official pegs used when no market rate is stored (units per USD).
        "fx_pegs": {"AED": 3.6725, "SAR": 3.75, "OMR": 0.3845, "QAR": 3.64, "BHD": 0.376},
        # A series is flagged stale when its latest point is older than this many days, by frequency.
        "stale_after_days": {"intraday": 1, "daily": 5, "weekly": 12, "monthly": 50},
    },
    "refresh_schedule": {
        "discovery_days": 7,
        "website_days": 45,
        "contact_days": 30,
        "trade_days": 7,
        "rescore_hours": 24,
    },
}
