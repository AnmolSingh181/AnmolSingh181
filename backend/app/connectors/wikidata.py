"""Key-free automatic discovery of polyethylene / petrochemical producers from Wikidata (CC0 open data).

Wikidata is the open database behind Wikipedia; its query service is free to use with an identifying User-Agent.
For each active market it finds companies that
  - produce polyethylene / HDPE / LDPE / LLDPE (property P1056 "product or material produced"), or
  - belong to the petrochemical industry (P452 "industry"),
then stores them with the Wikidata statement as evidence and queues a crawl of their official website (P856), where
the regular classifier extracts grades, buyer/seller role and contacts.

Only what Wikidata states is recorded. Generic "polyethylene" or "petrochemical industry" produce no polymer-specific
material rows; those come from the website crawl.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.connectors.base import BaseConnector, JobStats
from app.models import Company, Country, ScrapeJob, Source
from app.services.http import PoliteClient
from app.services.ingestion import CompanyInput, MaterialInput, ingest_company, store_raw
from app.services.normalize import company_domain

ENDPOINT = "https://query.wikidata.org/sparql"
PRODUCT_LABELS = {
    "polyethylene": None,  # generic: no specific polymer claimed
    "high-density polyethylene": "HDPE",
    "low-density polyethylene": "LDPE",
    "linear low-density polyethylene": "LLDPE",
}
INDUSTRY_LABELS = ["petrochemical industry"]


def build_queries(limit: int = 3000) -> list[str]:
    """Two small queries that start from the product/industry items (a handful) rather than from countries
    (millions of entities), with the optimizer pinned to the written order so they finish well inside the
    query service's 60-second limit. Country filtering happens in Python."""
    products = " ".join(f'"{p}"@en' for p in PRODUCT_LABELS)
    industries = " ".join(f'"{i}"@en' for i in INDUSTRY_LABELS)
    tail = """
  OPTIONAL { ?company wdt:P17 ?country . ?country wdt:P297 ?iso . }
  OPTIONAL { ?company wdt:P856 ?website . }
  OPTIONAL { ?company wdt:P159 ?hq . }
  FILTER NOT EXISTS { ?company wdt:P576 ?dissolved . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT %d""" % limit
    head = "SELECT DISTINCT ?company ?companyLabel ?website ?iso ?hqLabel ?kind ?what WHERE {\n  hint:Query hint:optimizer \"None\" .\n"
    q_products = head + f"""  VALUES ?what {{ {products} }}
  ?product rdfs:label ?what .
  ?company wdt:P1056 ?product .
  BIND("produces" AS ?kind)""" + tail
    q_industry = head + f"""  VALUES ?what {{ {industries} }}
  ?industry rdfs:label ?what .
  ?company wdt:P452 ?industry .
  BIND("industry" AS ?kind)""" + tail
    return [q_products, q_industry]


def group_bindings(data: dict) -> dict[str, dict]:
    """SPARQL JSON results -> one entry per company (QID)."""
    out: dict[str, dict] = {}
    for b in (data.get("results") or {}).get("bindings", []):
        uri = (b.get("company") or {}).get("value")
        name = (b.get("companyLabel") or {}).get("value")
        if not uri or not name:
            continue
        qid = uri.rsplit("/", 1)[-1]
        if name == qid:  # no English label
            continue
        e = out.setdefault(qid, {"qid": qid, "uri": uri, "name": name, "iso": None, "hq": None,
                                 "websites": [], "products": set(), "industries": set()})
        e["iso"] = e["iso"] or (b.get("iso") or {}).get("value")
        hq = (b.get("hqLabel") or {}).get("value")
        if hq and not hq.startswith("Q"):
            e["hq"] = e["hq"] or hq
        w = (b.get("website") or {}).get("value")
        if w and w not in e["websites"]:
            e["websites"].append(w)
        what = (b.get("what") or {}).get("value")
        kind = (b.get("kind") or {}).get("value")
        if what:
            (e["products"] if kind == "produces" else e["industries"]).add(what)
    return out


class WikidataConnector(BaseConnector):
    key = "wikidata"
    job_types = ("discover_producers",)

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self._client = client

    def run(self, job_type: str, params: dict) -> JobStats:
        db = self.db
        isos = set(params.get("countries") or [c.code for c in db.scalars(select(Country).where(Country.is_active)).all()])
        client = self._client or PoliteClient(min_delay=2.0, timeout=90)
        bindings: list = []
        for q in build_queries(int(params.get("limit", 3000))):
            for attempt in (1, 2):  # the public endpoint occasionally times out under load: one retry
                try:
                    r = client.api("GET", ENDPOINT, params={"query": q, "format": "json"},
                                   headers={"Accept": "application/sparql-results+json"})
                    r.raise_for_status()
                    bindings += (r.json().get("results") or {}).get("bindings", [])
                    break
                except Exception as exc:
                    self.log(f"Wikidata query attempt {attempt} failed: {exc}", "warning")
                    if attempt == 2:
                        self.stats.failed += 1
        if not bindings and self.stats.failed:
            raise RuntimeError("Wikidata queries failed (see log); will retry later")
        data = {"results": {"bindings": [b for b in bindings if (b.get("iso") or {}).get("value") in isos]}}
        self.log(f"{len(bindings)} rows from Wikidata, {len(data['results']['bindings'])} in active markets {sorted(isos)}")
        return self.process(data, crawl=params.get("crawl_websites", True))

    def process(self, data: dict, crawl: bool = True) -> JobStats:
        db = self.db
        crawl_src = db.scalar(select(Source).where(Source.key == "company_website"))
        recent = datetime.now(timezone.utc) - timedelta(days=30)
        companies = group_bindings(data)
        self.log(f"Wikidata returned {len(companies)} companies")
        for e in companies.values():
            self.stats.found += 1
            sp = db.begin_nested()
            try:
                raw, _ = store_raw(db, self.source, "wikidata_entity",
                                   {k: (sorted(v) if isinstance(v, set) else v) for k, v in e.items()},
                                   source_url=e["uri"], external_id=e["qid"], job=self.job)
                specific = sorted(p for p in e["products"] if PRODUCT_LABELS.get(p))
                materials = [MaterialInput(polymer=PRODUCT_LABELS[p], relationship="manufacturer",
                                           evidence=f"Wikidata {e['qid']}: product or material produced (P1056) = {p}")
                             for p in specific]
                types, evidence = [], []
                if e["products"]:
                    types = ["manufacturer"]
                    evidence.append(f"Wikidata {e['qid']}: product or material produced = {', '.join(sorted(e['products']))}")
                if e["industries"]:
                    evidence.append(f"Wikidata {e['qid']}: industry = {', '.join(sorted(e['industries']))}")
                website = e["websites"][0] if e["websites"] else None
                out = ingest_company(db, self.source, CompanyInput(
                    name=e["name"], country=e["iso"], city=e["hq"], website=website,
                    description="; ".join(evidence), company_types=types,
                    company_type_evidence="; ".join(evidence), materials=materials, source_url=e["uri"],
                    external_id=e["qid"]), raw=raw, use_ai=False, explicit_method="import")
                sp.commit()
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created)
                if crawl and website and crawl_src and company_domain(website):
                    c = db.get(Company, out.company_id)
                    queued = db.scalar(select(ScrapeJob.id).where(
                        ScrapeJob.source_id == crawl_src.id, ScrapeJob.status.in_(["queued", "running"]),
                        ScrapeJob.params["url"].astext == website))
                    fresh = c.website_last_crawled_at and c.website_last_crawled_at > recent
                    if not queued and not fresh:
                        db.add(ScrapeJob(source_id=crawl_src.id, job_type="crawl_website", priority=60,
                                         params={"url": website, "country": e["iso"], "query": f"wikidata {e['qid']}"}))
            except Exception as exc:
                sp.rollback()
                self.stats.failed += 1
                self.log(f"{e['qid']} {e['name']}: {exc}", "warning")
            db.commit()
        self.log(f"{self.stats.created} new, {self.stats.updated} updated; official websites queued for crawling")
        return self.stats
