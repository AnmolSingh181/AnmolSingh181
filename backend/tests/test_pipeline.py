"""End-to-end ingestion with synthetic fixtures: crawler (robots + sitemap), CSV imports, scoring, search."""
from sqlalchemy import func, select

from app.connectors.imports import CsvImportConnector, read_table
from app.connectors.website import WebsiteConnector
from app.models import Company, CompanySourceRecord, Contact, PriceObservation, RawRecord, ScrapeJob, Shipment, Source
from app.services.http import PoliteClient
from app.services.search import CompanyFilters, search_companies
from app.workers.runner import enqueue, execute
from tests.conftest import FIXTURES, site_transport


def _src(db, key):
    return db.scalar(select(Source).where(Source.key == key))


def crawl_fixture(db):
    client = PoliteClient(min_delay=0, transport=site_transport())
    job = enqueue(db, "company_website", "crawl_website", {"url": "https://fixture-polymers.example"})
    db.commit()
    return execute(db, job, {"client": client})


def test_website_crawl_end_to_end(db):
    job = crawl_fixture(db)
    assert job.status == "succeeded", job.error_message
    c = db.scalar(select(Company))
    assert c.name == "Fixture Polymers FZE" and c.country_code == "AE" and c.city == "Dubai"
    assert c.domain == "fixture-polymers.example" and c.linkedin_url.endswith("fixture-polymers-test")
    assert c.email == "info@fixture-polymers.example"
    types = {x.category for x in c.classifications}
    assert {"trader", "exporter", "distributor"} <= types and "manufacturer" not in types
    mats = {(m.material.code, m.grade_category, m.application, m.relationship_type) for m in c.materials}
    assert ("LLDPE", "virgin_prime", "film", "seller") in mats
    assert ("HDPE", "pcr", "unknown", "buyer") in mats
    lldpe = next(m for m in c.materials if m.material.code == "LLDPE" and m.grade_category == "virgin_prime")
    assert lldpe.specifications and lldpe.specifications[0].mfi == 2.0 and lldpe.specifications[0].density == 0.918
    assert lldpe.evidence_url and lldpe.evidence_text
    people = {x.full_name: x for x in c.contacts if x.contact_type == "individual"}
    assert people["Jane Testperson"].job_title == "Purchasing Manager"
    assert people["Jane Testperson"].decision_role == "likely_decision_maker"  # never auto-confirmed
    assert people["Omar Fixture"].phone
    assert not any("logo@2x" in (x.email or "") for x in c.contacts)
    assert db.scalar(select(func.count()).select_from(PriceObservation)) >= 1
    # traceability: every page stored raw, the company linked to a source record
    assert db.scalar(select(func.count()).select_from(RawRecord)) == 4
    assert db.scalar(select(func.count()).select_from(CompanySourceRecord).where(CompanySourceRecord.company_id == c.id)) == 1
    assert c.lead_score and c.lead_score_breakdown["components"]["material_relevance"]["points"] > 0
    # re-crawl: no duplicate company, raw pages deduplicated by hash
    crawl_fixture(db)
    assert db.scalar(select(func.count()).select_from(Company)) == 1


def test_crawler_respects_robots(db):
    client = PoliteClient(min_delay=0, transport=site_transport())
    assert not client.allowed("https://fixture-polymers.example/private/ldpe-price-list")
    assert client.allowed("https://fixture-polymers.example/products")


def test_shipment_import(db):
    headers, rows = read_table((FIXTURES / "shipments.csv").read_bytes(), "shipments.csv")
    stats = CsvImportConnector(db, _src(db, "csv_import")).import_rows("shipments", headers, rows,
                                                                       origin_source=_src(db, "importyeti"))
    assert stats.created == 4 and stats.failed == 0
    ships = db.scalars(select(Shipment).order_by(Shipment.external_id)).all()
    assert ships[0].material.code == "LLDPE" and ships[0].material_inference == "description"
    assert ships[2].material.code == "PE_SCRAP"
    assert ships[3].material.code == "HDPE" and ships[3].importer_company_id is None  # no party names -> no company
    importer = db.get(Company, ships[0].importer_company_id)
    assert importer.country_code == "US"
    assert {m.relationship_type for m in importer.materials} == {"historical_buyer"}
    assert ships[0].importer_company_id == ships[1].importer_company_id  # same consignee resolved to one company
    # re-import is idempotent
    stats2 = CsvImportConnector(db, _src(db, "csv_import")).import_rows("shipments", headers, rows,
                                                                        origin_source=_src(db, "importyeti"))
    assert stats2.created == 0 and db.scalar(select(func.count()).select_from(Shipment)) == 4
    f = CompanyFilters(trade_roles=["importer"], polymers=["LLDPE"], relationships=["buyer"])
    total, res = search_companies(db, f)
    assert total == 1 and res[0].name == "Fixture Film Converters Inc"


def test_company_import_merges_with_crawled_record(db):
    crawl_fixture(db)
    headers, rows = read_table((FIXTURES / "companies.csv").read_bytes(), "companies.csv")
    stats = CsvImportConnector(db, _src(db, "csv_import")).import_rows("companies", headers, rows)
    assert stats.failed == 0
    assert db.scalar(select(func.count()).select_from(Company)) == 2  # Fixture Polymers matched by domain
    rec = db.scalar(select(Company).where(Company.name.like("Fixture Recyclers%")))
    assert {x.category for x in rec.classifications} >= {"recycler"}
    ravi = next(x for x in rec.contacts if x.full_name == "Ravi Testkumar")
    assert ravi.decision_role == "likely_decision_maker" and ravi.verification_status == "discovered"
    fp = db.scalar(select(Company).where(Company.domain == "fixture-polymers.example"))
    assert len(fp.source_records) == 2


def test_failed_job_isolated_and_reported(db):
    job = enqueue(db, "web_search", "discover", {})
    db.commit()
    job = execute(db, job)
    assert job.status == "failed" and "NotConfigured" in job.error_message
    assert _src(db, "web_search").status == "awaiting_credentials"
    job2 = enqueue(db, "enf_plastic", "collect_directory", {})
    db.commit()
    job2 = execute(db, job2)
    assert job2.status == "failed" and "TermsNotConfirmed" in job2.error_message
    ok = crawl_fixture(db)
    assert ok.status == "succeeded"


def test_suppressed_contact_not_recollected(db):
    from app.models import SuppressionEntry
    from app.services.normalize import sha256

    db.add(SuppressionEntry(value_hash=sha256("jane.testperson@fixture-polymers.example"), value_type="email", reason="opt_out"))
    db.commit()
    crawl_fixture(db)
    assert not db.scalar(select(Contact).where(Contact.email_normalized == "jane.testperson@fixture-polymers.example"))
