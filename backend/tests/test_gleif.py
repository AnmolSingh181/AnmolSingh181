"""GLEIF registry discovery with a synthetic response in the GLEIF JSON:API format."""
from sqlalchemy import select

from app.connectors.gleif import GleifConnector, parse_record
from app.models import Company, Source


def rec(lei, name, country="AE", city="Dubai", reg="CN-555", status="ACTIVE"):
    return {"type": "lei-records", "id": lei, "attributes": {"lei": lei, "entity": {
        "legalName": {"name": name, "language": "en"}, "otherNames": [], "status": status,
        "registeredAs": reg, "registeredAt": {"id": "RA000999"},
        "legalAddress": {"addressLines": ["Office 1, Test Tower"], "city": city, "region": None, "country": country,
                         "postalCode": "00000"},
        "headquartersAddress": {"addressLines": ["Office 1, Test Tower"], "city": city, "country": country}}}}


def test_parse_and_ingest(db):
    src = db.scalar(select(Source).where(Source.key == "gleif"))
    records = [rec("LEITEST0000000000001", "Fixture Polymers Trading L.L.C"),
               rec("LEITEST0000000000002", "Fixture HDPE Recycling Industries", reg="CN-556"),
               rec("LEITEST0000000000003", "Fixture Holdings LLC", reg="CN-557"),  # no plastics word in name -> ignored
               rec("LEITEST0000000000004", "Fixture Plastic Bags LLC", status="INACTIVE", reg="CN-558")]
    assert parse_record(records[0])["registration_number"] == "CN-555"
    stats = GleifConnector(db, src).process(records, ["polymer", "plastic", "recycl"])
    assert stats.created == 2
    t = db.scalar(select(Company).where(Company.name.like("Fixture Polymers Trading%")))
    assert t.country_code == "AE" and t.city == "Dubai" and t.registration_number == "CN-555"
    assert {c.category for c in t.classifications} == {"trader"} and not t.materials
    r = db.scalar(select(Company).where(Company.name.like("Fixture HDPE Recycling%")))
    assert {c.category for c in r.classifications} == {"recycler"}
    assert {m.material.code for m in r.materials} == {"HDPE"}
    assert r.lead_score < 60  # registry-only evidence stays a low-priority lead
    # idempotent: same registration number matches the same company
    assert GleifConnector(db, src).process(records, ["polymer", "plastic", "recycl"]).created == 0
