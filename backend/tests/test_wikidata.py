"""Wikidata producer discovery, using a synthetic response in the standard SPARQL JSON results format."""
from sqlalchemy import select

from app.connectors.wikidata import WikidataConnector, build_query, group_bindings
from app.models import Company, ScrapeJob, Source


def _b(qid, name, iso, kind, what, website=None, hq=None):
    d = {"company": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
         "companyLabel": {"type": "literal", "value": name}, "iso": {"type": "literal", "value": iso},
         "kind": {"type": "literal", "value": kind}, "what": {"type": "literal", "xml:lang": "en", "value": what}}
    if website:
        d["website"] = {"type": "uri", "value": website}
    if hq:
        d["hqLabel"] = {"type": "literal", "value": hq}
    return d


DATA = {"head": {"vars": ["company", "companyLabel", "website", "iso", "hqLabel", "kind", "what"]}, "results": {"bindings": [
    _b("Q900001", "Fixture Petrochemical Company", "SA", "produces", "high-density polyethylene", "https://fixture-petchem.example", "Jubail"),
    _b("Q900001", "Fixture Petrochemical Company", "SA", "produces", "linear low-density polyethylene", "https://fixture-petchem.example", "Jubail"),
    _b("Q900002", "Fixture Refining Group", "IN", "industry", "petrochemical industry", "https://fixture-refining.example"),
    _b("Q900003", "Q900003", "VN", "industry", "petrochemical industry"),  # no English label -> skipped
]}}


def test_query_contains_markets_and_properties():
    q = build_query(["US", "AE"])
    assert '"US" "AE"' in q and "wdt:P1056" in q and "wdt:P452" in q and "wdt:P856" in q


def test_grouping():
    g = group_bindings(DATA)
    assert set(g) == {"Q900001", "Q900002"}
    assert g["Q900001"]["products"] == {"high-density polyethylene", "linear low-density polyethylene"}


def test_process_creates_companies_and_queues_crawls(db):
    src = db.scalar(select(Source).where(Source.key == "wikidata"))
    stats = WikidataConnector(db, src).process(DATA)
    assert stats.created == 2 and stats.failed == 0
    pet = db.scalar(select(Company).where(Company.name == "Fixture Petrochemical Company"))
    assert pet.country_code == "SA" and pet.city == "Jubail" and pet.domain == "fixture-petchem.example"
    assert {(m.material.code, m.relationship_type) for m in pet.materials} == {("HDPE", "manufacturer"), ("LLDPE", "manufacturer")}
    assert {c.category for c in pet.classifications} == {"manufacturer"}
    ref = db.scalar(select(Company).where(Company.name == "Fixture Refining Group"))
    assert not ref.materials and not ref.classifications  # generic industry: no claims, website crawl decides
    jobs = db.scalars(select(ScrapeJob).where(ScrapeJob.job_type == "crawl_website")).all()
    assert {j.params["url"] for j in jobs} == {"https://fixture-petchem.example", "https://fixture-refining.example"}
    # re-run: no duplicates, no duplicate crawl jobs
    stats2 = WikidataConnector(db, src).process(DATA)
    assert stats2.created == 0
    assert len(db.scalars(select(ScrapeJob).where(ScrapeJob.job_type == "crawl_website")).all()) == 2
