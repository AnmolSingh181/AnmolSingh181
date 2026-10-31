from sqlalchemy import select

from app.models import Company, Source
from app.services.ingestion import CompanyInput, ContactInput, MaterialInput, ingest_company
from app.services.nl_search import parse_rules
from app.services.scoring import tier_for


def test_tiers():
    tiers = [{"min": 80, "label": "High priority"}, {"min": 60, "label": "Relevant"},
             {"min": 40, "label": "Needs verification"}, {"min": 0, "label": "Low priority"}]
    assert tier_for(85, tiers) == "High priority" and tier_for(60, tiers) == "Relevant" and tier_for(10, tiers) == "Low priority"


def test_score_components_explained(db):
    s = db.scalar(select(Source).where(Source.key == "manual"))
    out = ingest_company(db, s, CompanyInput(
        name="Score Test Co", country="IN", website="score-test.example",
        materials=[MaterialInput(polymer="LDPE", grade_category="off_grade", application="film", relationship="buyer",
                                 evidence="Buyer of off-grade LDPE film grade")],
        contacts=[ContactInput(full_name="A Tester", job_title="Procurement Manager", email="a@score-test.example"),
                  ContactInput(email="info@score-test.example"), ContactInput(phone="+91 22 5555 0101")]))
    c = db.get(Company, out.company_id)
    comp = c.lead_score_breakdown["components"]
    assert set(comp) == {"material_relevance", "trading_activity", "international_trade", "contact_completeness", "data_recency"}
    assert comp["material_relevance"]["max"] == 30 and comp["material_relevance"]["points"] > 20
    assert comp["data_recency"]["points"] == 10
    assert comp["international_trade"]["points"] == 0
    assert all(v["reasons"] for v in comp.values())
    assert "not a conversion probability" in c.lead_score_breakdown["note"]
    empty = ingest_company(db, s, CompanyInput(name="No Evidence Co", country="IN"))
    assert db.get(Company, empty.company_id).lead_score < c.lead_score


def test_nl_parser(db):
    f, _ = parse_rules(db, "Find virgin LLDPE film grade suppliers in the USA.")
    assert f.polymers == ["LLDPE"] and f.grades == ["virgin_prime"] and f.applications == ["film"]
    assert f.relationships == ["seller"] and f.countries == ["US"]
    f, _ = parse_rules(db, "Find companies importing off-grade LDPE into India.")
    assert f.polymers == ["LDPE"] and f.grades == ["off_grade"] and f.countries == ["IN"] and "importer" in f.trade_roles
    f, _ = parse_rules(db, "Find recycled HDPE buyers in Vietnam.")
    assert f.grades == ["recycled"] and f.relationships == ["buyer"] and f.countries == ["VN"]
    f, _ = parse_rules(db, "Find plastic traders in UAE dealing in both LDPE and LLDPE.")
    assert f.company_types == ["trader"] and f.polymer_match == "all" and set(f.polymers) == {"LDPE", "LLDPE"}
    assert f.countries == ["AE"]
    f, _ = parse_rules(db, "Show companies that have public procurement manager contact information.")
    assert f.contact_title == "procurement"


def test_api_flow(client, db):
    r = client.post("/companies", json={"name": "Api Test Polymers", "country": "Vietnam", "website": "api-test.example",
                                        "description": "We supply recycled LDPE granules and HDPE regrind for export.",
                                        "company_types": ["recycler"]})
    assert r.status_code == 201, r.text
    cid = r.json()["company_id"]
    lst = client.get("/companies", params={"country": "VN", "polymer": "LDPE", "relationship": "seller"}).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == cid
    assert client.get("/companies", params={"country": "IN"}).json()["total"] == 0
    detail = client.get(f"/companies/{cid}").json()
    assert detail["materials"] and detail["source_records"]
    mid = detail["materials"][0]["id"]
    assert client.post(f"/company-materials/{mid}/review", json={"status": "confirmed"}).json()["review_status"] == "confirmed"
    q = client.get("/quality").json()
    assert q["classification_reviews"] == 1 and q["classification_accuracy"] == 100.0 and q["source_traceability"] == 100.0
    r = client.post(f"/companies/{cid}/contacts", json={"full_name": "Test Buyer", "job_title": "Purchase Manager",
                                                        "email": "buyer@api-test.example"})
    assert r.status_code == 201
    contacts = client.get("/contacts", params={"title": "purchase"}).json()
    assert contacts["total"] == 1
    lead = client.post("/leads", json={"company_id": cid, "lead_type": "potential_supplier", "interested_materials": ["LDPE"]})
    assert lead.status_code == 201
    lid = lead.json()["id"]
    client.patch(f"/leads/{lid}", json={"stage": "interested"})
    client.post(f"/leads/{lid}/activities", json={"activity_type": "call", "summary": "Discussed 2 x 40ft"})
    leads = client.get("/leads").json()
    assert leads["stage_counts"]["interested"] == 1 and leads["items"][0]["last_contacted_at"]
    assert "Api Test Polymers" in client.get("/leads/export.csv").text
    assert "Api Test Polymers" in client.get("/companies/export.csv", params={"country": "VN"}).text
    nl = client.post("/search/nl", json={"query": "recycled LDPE suppliers in Vietnam"}).json()
    assert nl["parser"] == "rules" and nl["total"] == 1
    dash = client.get("/dashboard").json()
    assert dash["totals"]["companies"] == 1 and dash["totals"]["recyclers"] == 1
    srcs = client.get("/sources").json()
    assert any(s["key"] == "importyeti" and not s["readiness"]["ready"] for s in srcs["sources"])
    enf = next(s for s in srcs["sources"] if s["key"] == "enf_plastic")
    assert client.patch(f"/sources/{enf['id']}", json={"enabled": True}).status_code == 400


def test_privacy_opt_out(client, db):
    r = client.post("/companies", json={"name": "Privacy Test Co", "country": "US", "email": "person@privacy.example"})
    cid = r.json()["company_id"]
    anon = client.__class__(client.app)
    assert anon.post("/privacy/requests", json={"request_type": "opt_out", "email": "person@privacy.example"}).status_code == 201
    assert client.get("/contacts", params={"company_id": cid}).json()["total"] == 0


def test_auth_required(db):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/companies").status_code == 401
