"""Key-free company discovery from GLEIF, the official Global Legal Entity Identifier register (open data, CC0).

Searches active legal entities in each active market whose legal name contains plastics keywords (polymer,
polyethylene, plastic, petrochem, resin, recycling). Stores legal name, registered address, local registration number
and LEI, with the registry record as the source. GLEIF carries no websites or contacts, so these start as
low-priority "needs verification" leads; name-based classification is kept modest and marked as such.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.connectors.base import BaseConnector, JobStats
from app.models import Country
from app.services.classifier import find_polymers
from app.services.http import PoliteClient
from app.services.ingestion import CompanyInput, MaterialInput, ingest_company, store_raw

ENDPOINT = "https://api.gleif.org/api/v1/lei-records"
KEYWORDS = ["polymer", "polyethylene", "plastic", "petrochem", "resin", "recycl", "polyolefin", "masterbatch"]
NAME_TYPES = [
    ("trader", re.compile(r"\b(trading|traders?|trade|impex|exim|import|export|commodit\w*)\b", re.I)),
    ("recycler", re.compile(r"recycl", re.I)),
    ("converter", re.compile(r"\b(packaging|packers|bags?|sacks?|films?|pipes?|bottles?|containers?|moulding|molding|extrusions?)\b", re.I)),
    ("processor", re.compile(r"\b(compound\w*|masterbatch\w*)\b", re.I)),
]


def name_matches(name: str, keywords: list[str]) -> bool:
    n = name.lower()
    return any(k in n for k in keywords)


def parse_record(rec: dict) -> dict | None:
    a = rec.get("attributes") or {}
    ent = a.get("entity") or {}
    name = ((ent.get("legalName") or {}).get("name") or "").strip()
    if not name or (ent.get("status") or "ACTIVE") != "ACTIVE":
        return None
    addr = ent.get("legalAddress") or {}
    hq = ent.get("headquartersAddress") or {}
    use = hq if hq.get("country") == addr.get("country") and hq.get("city") else addr
    lines = [l for l in (use.get("addressLines") or []) if l]
    return {
        "lei": a.get("lei") or rec.get("id"),
        "name": name,
        "other_names": [o.get("name") for o in (ent.get("otherNames") or []) if isinstance(o, dict) and o.get("name")],
        "country": use.get("country") or addr.get("country"),
        "city": use.get("city"),
        "region": use.get("region"),
        "postal_code": use.get("postalCode"),
        "address": ", ".join(lines + [x for x in (use.get("city"), use.get("postalCode")) if x]) or None,
        "registration_number": ent.get("registeredAs"),
        "registration_authority": (ent.get("registeredAt") or {}).get("id"),
    }


class GleifConnector(BaseConnector):
    key = "gleif"
    job_types = ("discover_registry",)

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self._client = client

    def run(self, job_type: str, params: dict) -> JobStats:
        client = self._client or PoliteClient(min_delay=1.2, timeout=60)  # GLEIF allows ~60 requests/minute
        countries = params.get("countries") or [c.code for c in self.db.scalars(select(Country).where(Country.is_active)).all()]
        keywords = params.get("keywords") or KEYWORDS
        max_pages, size = int(params.get("max_pages", 2)), int(params.get("page_size", 100))
        for cc in countries:
            for kw in keywords:
                for page in range(1, max_pages + 1):
                    try:
                        r = client.api("GET", ENDPOINT, headers={"Accept": "application/vnd.api+json"}, params={
                            "filter[fulltext]": kw, "filter[entity.legalAddress.country]": cc,
                            "filter[entity.status]": "ACTIVE", "page[size]": size, "page[number]": page})
                        r.raise_for_status()
                        data = r.json()
                    except Exception as exc:
                        self.stats.failed += 1
                        self.log(f"{cc}/{kw} page {page}: {exc}", "warning")
                        break
                    records = data.get("data") or []
                    self.process(records, [kw])
                    last = ((data.get("meta") or {}).get("pagination") or {}).get("lastPage") or page
                    if not records or page >= last:
                        break
        self.log(f"GLEIF: {self.stats.created} new, {self.stats.updated} existing/updated companies")
        return self.stats

    def process(self, records: list[dict], keywords: list[str]) -> JobStats:
        db = self.db
        for rec in records:
            e = parse_record(rec)
            if not e or not name_matches(" ".join([e["name"]] + e["other_names"]), keywords or KEYWORDS):
                continue  # fulltext also matches addresses etc. - keep only plastics-named entities
            self.stats.found += 1
            sp = db.begin_nested()
            try:
                url = f"https://search.gleif.org/#/record/{e['lei']}"
                raw, _ = store_raw(db, self.source, "lei_record", rec, source_url=url, external_id=e["lei"], job=self.job)
                evidence = f"Registered legal name '{e['name']}' (GLEIF LEI {e['lei']})"
                types = [t for t, rx in NAME_TYPES if rx.search(e["name"])]
                mats = [MaterialInput(polymer=p, evidence=evidence) for p in sorted({p for p, _, _ in find_polymers(e["name"])} - {"PE_OTHER"})]
                out = ingest_company(db, self.source, CompanyInput(
                    name=e["name"], aliases=e["other_names"], country=e["country"], city=e["city"], state=e["region"],
                    postal_code=e["postal_code"], address=e["address"], registration_number=e["registration_number"],
                    registration_authority=e["registration_authority"], company_types=types,
                    company_type_evidence=f"{evidence} - inferred from the name only, verify", materials=mats,
                    description=f"Found in the GLEIF legal entity register (LEI {e['lei']}).", source_url=url,
                    external_id=e["lei"]), raw=raw, use_ai=False, explicit_method="import")
                sp.commit()
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created)
            except Exception as exc:
                sp.rollback()
                self.stats.failed += 1
                self.log(f"{e['lei']}: {exc}", "warning")
        db.commit()
        return self.stats
