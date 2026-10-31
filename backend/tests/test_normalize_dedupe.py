from app.models import Company, Source
from app.services.dedupe import CompanyCandidate, find_match, merge_companies
from app.services.ingestion import CompanyInput, ContactInput, ingest_company
from app.services.normalize import company_domain, extract_domain, normalize_company_name, normalize_phone
from sqlalchemy import select


def test_normalize_names():
    assert normalize_company_name("ACME Polymers Pvt. Ltd.") == "acme polymers"
    assert normalize_company_name("Acme Polymers Private Limited") == "acme polymers"
    assert normalize_company_name("Gulf Resins FZE") == "gulf resins"
    assert normalize_company_name("Công ty TNHH Nhựa Test") == "nhua test"
    assert normalize_company_name("Al Test Trading Co. LLC") == "al test trading"


def test_domains_and_phones():
    assert extract_domain("https://www.shop.acme.co.in/x") == "acme.co.in"
    assert company_domain("https://www.alibaba.com/acme", "sales@gmail.com") is None
    assert company_domain(None, "info@acme-test.com") == "acme-test.com"
    assert normalize_phone("+971 (4) 555-0100") == "97145550100"
    assert normalize_phone("04 555 0100", "971") == "97145550100"
    assert normalize_phone("0091 22 5555 0100") == "912255550100"


def _src(db):
    return db.scalar(select(Source).where(Source.key == "manual"))


def test_domain_match_merges_but_similar_name_alone_does_not(db):
    s = _src(db)
    a = ingest_company(db, s, CompanyInput(name="Fixture Polymers FZE", country="AE", city="Dubai",
                                           website="https://fixture-polymers.example"))
    b = ingest_company(db, s, CompanyInput(name="Fixture Polymers Free Zone Establishment", country="AE",
                                           website="www.fixture-polymers.example/contact"))
    assert a.company_id == b.company_id and b.match_method == "domain"
    # same name, same country, no city/identifier -> NOT merged, flagged for review
    c = ingest_company(db, s, CompanyInput(name="Fixture Polymers FZE", country="AE"))
    assert c.created and c.duplicates_flagged >= 1
    # different country -> separate company
    d = ingest_company(db, s, CompanyInput(name="Fixture Polymers FZE", country="IN"))
    assert d.created
    db.commit()


def test_same_domain_different_business_flagged_not_merged(db):
    s = _src(db)
    a = ingest_company(db, s, CompanyInput(name="Testgroup Petrochemicals", country="IN", website="testgroup.example"))
    b = ingest_company(db, s, CompanyInput(name="Zeta Retail Stores", country="IN", website="testgroup.example"))
    assert a.company_id != b.company_id and b.duplicates_flagged == 1


def test_phone_and_registration_match(db):
    s = _src(db)
    a = ingest_company(db, s, CompanyInput(name="Fixture Resins Trading LLC", country="AE", phone="+971 4 555 0111",
                                           registration_number="CR-555"))
    b = ingest_company(db, s, CompanyInput(name="Fixture Resins Trading", country="AE", phone="04 555 0111"))
    assert b.match_method == "phone+name" and a.company_id == b.company_id
    c = ingest_company(db, s, CompanyInput(name="Totally Different Name", country="AE", registration_number="CR-555"))
    assert c.match_method == "registration" and c.company_id == a.company_id


def test_merge_keeps_history(db):
    s = _src(db)
    a = ingest_company(db, s, CompanyInput(name="Merge Test A", country="US", city="Austin",
                                           contacts=[ContactInput(email="a@merge-a.example")]))
    b = ingest_company(db, s, CompanyInput(name="MergeTest Alpha Incorporated", country="US", website="merge-a.example",
                                           contacts=[ContactInput(email="b@merge-a.example")]))
    ca, cb = db.get(Company, a.company_id), db.get(Company, b.company_id)
    merge_companies(db, ca, cb)
    db.commit()
    db.refresh(ca)
    assert cb.status == "merged" and cb.merged_into_id == ca.id
    assert {c.email for c in ca.contacts} == {"a@merge-a.example", "b@merge-a.example"}
    assert ca.website == "https://merge-a.example"
    assert any(al.alias == "MergeTest Alpha Incorporated" for al in ca.aliases)
    assert len(ca.source_records) == 2


def test_trade_party_exact_name_rule(db):
    from app.services.ingestion import ShipmentInput, ingest_shipment

    s = _src(db)
    a = ingest_company(db, s, CompanyInput(name="Fixture Film Converters Inc", country="US", city="Houston",
                                           website="ffc.example"))
    ts = db.scalar(select(Source).where(Source.key == "csv_import"))
    sh, _ = ingest_shipment(db, ts, ShipmentInput(external_id="X1", importer_name="FIXTURE FILM CONVERTERS, INC.",
                                                  importer_country="USA", hs_code="390140"))
    assert str(sh.importer_company_id) == a.company_id
    # two same-named companies in the country -> ambiguous -> new record + review flag, never a guess
    ingest_company(db, s, CompanyInput(name="Twin Name Plastics", country="US", city="Austin"))
    ingest_company(db, s, CompanyInput(name="Twin Name Plastics", country="US", city="Dallas"))
    sh2, _ = ingest_shipment(db, ts, ShipmentInput(external_id="X2", importer_name="Twin Name Plastics", importer_country="US"))
    assert db.get(Company, sh2.importer_company_id).city is None
