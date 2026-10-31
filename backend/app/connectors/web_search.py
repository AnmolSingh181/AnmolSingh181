"""Discovery via official search APIs.

Builds queries from MATERIAL + GRADE + COUNTRY + BUSINESS TYPE + BUYER/SELLER, calls a configured search API
(Brave, Serper.dev, SerpAPI or Google Programmable Search), filters out marketplaces/social/news, and queues a
crawl_website job for every new company domain. Search result pages are never scraped directly.
"""
from __future__ import annotations

import itertools
import random

from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import BaseConnector, JobStats, NotConfigured
from app.models import ApiUsage, Company, Country, RawRecord, ScrapeJob, Source
from app.services.http import PoliteClient
from app.services.ingestion import store_raw
from app.services.normalize import extract_domain, is_generic_domain

POLYMER_TERMS = {"LDPE": ["LDPE"], "LLDPE": ["LLDPE"], "HDPE": ["HDPE"]}
GRADE_TERMS = {
    "virgin_prime": ["virgin", "prime"], "near_prime": ["near prime", "wide spec"], "off_grade": ["off grade"],
    "off_spec": ["off spec"], "recycled": ["recycled", "reprocessed granules"], "pcr": ["PCR post consumer"],
    "pir": ["post industrial"], "scrap": ["scrap"],
}
APP_TERMS = {"film": ["film grade"], "extrusion": ["extrusion grade"], "blow_moulding": ["blow moulding grade"],
             "injection_moulding": ["injection moulding grade"]}
BUSINESS_TERMS = {
    "seller": ["supplier", "exporter", "manufacturer", "distributor", "trader", "stockist"],
    "buyer": ["buyer", "importer", "purchaser", "we buy"],
    "recycler": ["recycler", "recycling company"],
}
EXCLUDE_HOST_PARTS = ("alibaba", "made-in-china", "indiamart", "tradeindia", "exportersindia", "globalsources", "ec21",
                      "tradekey", "linkedin", "facebook", "instagram", "youtube", "twitter", "wikipedia", "amazon",
                      "ebay", "reddit", "quora", "pinterest", "scribd", "researchgate", "sciencedirect", "news",
                      "medium.com", "blogspot", "statista", "marketsandmarkets", "grandviewresearch", "mordorintelligence",
                      "chemanalyst", "icis.com", "argusmedia", "platts", "plasticstoday", "plasticsnews", "volza",
                      "importyeti", "panjiva", "tradedata", "kompass", "zauba", "seair", "eximpedia", "made-in-",
                      "google.", "bing.", "yahoo.", "baidu.", "duckduckgo")


def build_queries(polymers: list[str], grades: list[str], countries: list[str], intents: list[str],
                  applications: list[str] | None = None, limit: int = 30, seed: int | None = None) -> list[dict]:
    """Deterministic (seeded) combinatorial query plan."""
    combos = []
    for poly, grade, cname, intent in itertools.product(polymers, grades or [None], countries, intents):
        for app in (applications or [None]):
            for bterm in BUSINESS_TERMS.get(intent, [intent])[:2]:
                parts = []
                if grade:
                    parts.append(GRADE_TERMS.get(grade, [grade.replace("_", " ")])[0])
                parts.append(POLYMER_TERMS.get(poly, [poly])[0])
                if app:
                    parts.append(APP_TERMS.get(app, [app.replace("_", " ")])[0])
                parts += [bterm, cname]
                combos.append({"q": " ".join(parts), "polymer": poly, "grade": grade, "application": app,
                               "country": cname, "intent": intent})
    rnd = random.Random(seed)
    rnd.shuffle(combos)
    return combos[:limit]


class SearchProvider:
    name = ""
    cost_per_query = 0.0

    def __init__(self, client: PoliteClient):
        self.client = client

    def search(self, q: str, country_code: str | None, count: int = 10) -> list[dict]:
        raise NotImplementedError


class BraveProvider(SearchProvider):
    name, cost_per_query = "brave", 0.005

    def search(self, q, country_code, count=10):
        r = self.client.api("GET", "https://api.search.brave.com/res/v1/web/search",
                            params={"q": q, "count": count, **({"country": country_code} if country_code else {})},
                            headers={"X-Subscription-Token": get_settings().brave_search_api_key,
                                     "Accept": "application/json"})
        r.raise_for_status()
        return [{"url": x.get("url"), "title": x.get("title"), "snippet": x.get("description")}
                for x in (r.json().get("web", {}) or {}).get("results", [])]


class SerperProvider(SearchProvider):
    name, cost_per_query = "serper", 0.001

    def search(self, q, country_code, count=10):
        r = self.client.api("POST", "https://google.serper.dev/search",
                            json={"q": q, "num": count, **({"gl": country_code.lower()} if country_code else {})},
                            headers={"X-API-KEY": get_settings().serper_api_key})
        r.raise_for_status()
        return [{"url": x.get("link"), "title": x.get("title"), "snippet": x.get("snippet")}
                for x in r.json().get("organic", [])]


class SerpApiProvider(SearchProvider):
    name, cost_per_query = "serpapi", 0.01

    def search(self, q, country_code, count=10):
        r = self.client.api("GET", "https://serpapi.com/search.json",
                            params={"q": q, "num": count, "engine": "google", "api_key": get_settings().serpapi_api_key,
                                    **({"gl": country_code.lower()} if country_code else {})})
        r.raise_for_status()
        return [{"url": x.get("link"), "title": x.get("title"), "snippet": x.get("snippet")}
                for x in r.json().get("organic_results", [])]


class GoogleCseProvider(SearchProvider):
    name, cost_per_query = "google_cse", 0.005

    def search(self, q, country_code, count=10):
        s = get_settings()
        r = self.client.api("GET", "https://www.googleapis.com/customsearch/v1",
                            params={"key": s.google_cse_api_key, "cx": s.google_cse_cx, "q": q, "num": min(count, 10),
                                    **({"gl": country_code.lower()} if country_code else {})})
        r.raise_for_status()
        return [{"url": x.get("link"), "title": x.get("title"), "snippet": x.get("snippet")} for x in r.json().get("items", [])]


def configured_provider(client: PoliteClient) -> SearchProvider | None:
    s = get_settings()
    if s.brave_search_api_key:
        return BraveProvider(client)
    if s.serper_api_key:
        return SerperProvider(client)
    if s.serpapi_api_key:
        return SerpApiProvider(client)
    if s.google_cse_api_key and s.google_cse_cx:
        return GoogleCseProvider(client)
    return None


def keep_result(url: str | None) -> bool:
    if not url:
        return False
    d = extract_domain(url) or ""
    return bool(d) and not is_generic_domain(d) and not any(p in d for p in EXCLUDE_HOST_PARTS) and not url.lower().endswith(".pdf")


class WebSearchConnector(BaseConnector):
    key = "web_search"
    job_types = ("discover",)

    def __init__(self, *a, provider: SearchProvider | None = None, **kw):
        super().__init__(*a, **kw)
        self._provider = provider

    def status(self):
        p = configured_provider(PoliteClient(min_delay=0)) if self._provider is None else self._provider
        return {"ready": p is not None, "message": f"provider: {p.name}" if p else
                "Set BRAVE_SEARCH_API_KEY, SERPER_API_KEY, SERPAPI_API_KEY or GOOGLE_CSE_API_KEY+GOOGLE_CSE_CX"}

    def run(self, job_type: str, params: dict) -> JobStats:
        provider = self._provider or configured_provider(PoliteClient(min_delay=1.0))
        if provider is None:
            raise NotConfigured(self.status()["message"])
        db = self.db
        countries = params.get("countries") or [c.code for c in db.scalars(select(Country).where(Country.is_active)).all()]
        cmap = {c.code: c.name for c in db.scalars(select(Country)).all()}
        queries = params.get("queries") or build_queries(
            params.get("polymers", ["LDPE", "LLDPE", "HDPE"]),
            params.get("grades", ["virgin_prime", "off_grade", "near_prime", "recycled"]),
            [cmap.get(c, c) for c in countries], params.get("intents", ["seller", "buyer"]),
            params.get("applications"), limit=int(params.get("max_queries", 20)), seed=params.get("seed"))
        if queries and isinstance(queries[0], str):
            queries = [{"q": q} for q in queries]
        name_to_code = {v: k for k, v in cmap.items()}
        crawl_source = db.scalar(select(Source).where(Source.key == "company_website"))
        known = {d for (d,) in db.execute(select(Company.domain).where(Company.domain.is_not(None))).all()}
        queued = set()
        for qd in queries:
            cc = name_to_code.get(qd.get("country"))
            try:
                results = provider.search(qd["q"], cc, int(params.get("results_per_query", 10)))
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"query failed '{qd['q']}': {exc}", "warning")
                continue
            db.add(ApiUsage(provider=provider.name, operation="search", units=1, estimated_cost_usd=provider.cost_per_query))
            store_raw(db, self.source, "search_results", {"query": qd, "results": results}, job=self.job)
            self.stats.found += len(results)
            for res in results:
                if not keep_result(res.get("url")):
                    continue
                d = extract_domain(res["url"])
                if d in known or d in queued:
                    continue
                queued.add(d)
                db.add(ScrapeJob(source_id=crawl_source.id, job_type="crawl_website", priority=50,
                                 params={"url": f"https://{d}", "country": cc, "query": qd["q"],
                                         "search_title": res.get("title"), "search_snippet": res.get("snippet")},
                                 created_by=self.job.created_by if self.job else None))
                self.stats.created += 1
            db.commit()
        self.log(f"{len(queries)} queries, {self.stats.found} results, {self.stats.created} new domains queued for crawling")
        return self.stats
