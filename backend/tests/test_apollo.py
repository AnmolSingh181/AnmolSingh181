"""Apollo connector against a mock Apollo API (synthetic data)."""
import json

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import NotConfigured
from app.connectors.gated import ApolloConnector
from app.models import Company, Contact, Source
from app.services.http import PoliteClient
from app.services.ingestion import CompanyInput, ingest_company


@pytest.fixture()
def apollo_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "apollo_api_key", "test-key")


def _company(db):
    s = db.scalar(select(Source).where(Source.key == "manual"))
    out = ingest_company(db, s, CompanyInput(name="Apollo Test Polymers", country="AE", website="apollo-test.example"))
    db.commit()
    return db.get(Company, out.company_id)


def test_search_then_enrich_once(db, apollo_key):
    _company(db)
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        assert req.headers["X-Api-Key"] == "test-key"
        if req.url.path.endswith("/mixed_people/api_search"):
            assert json.loads(req.content)["q_organization_domains_list"] == ["apollo-test.example"]
            return httpx.Response(200, json={"people": [{"id": "p1", "first_name": "Sam", "name": "Sam T.", "title": "Purchase Manager"}]})
        if req.url.path.endswith("/people/match"):
            return httpx.Response(200, json={"person": {"id": "p1", "name": "Sam Tester", "title": "Purchase Manager",
                                                        "email": "sam@apollo-test.example",
                                                        "linkedin_url": "https://www.linkedin.com/in/sam-tester-example"}})
        return httpx.Response(404)

    src = db.scalar(select(Source).where(Source.key == "apollo"))
    client = PoliteClient(min_delay=0, transport=httpx.MockTransport(handler))
    stats = ApolloConnector(db, src, client=client).run("enrich_contacts", {})
    assert stats.created == 1
    c = db.scalar(select(Contact).where(Contact.email_normalized == "sam@apollo-test.example"))
    assert c.full_name == "Sam Tester" and c.decision_role == "likely_decision_maker"
    # second run: the person is not enriched again (no second credit spent)
    ApolloConnector(db, src, client=client).run("enrich_contacts", {})
    assert calls.count("/api/v1/people/match") == 1


def test_forbidden_key_gives_clear_error(db, apollo_key):
    _company(db)
    src = db.scalar(select(Source).where(Source.key == "apollo"))
    client = PoliteClient(min_delay=0, transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "API_INACCESSIBLE"})))
    with pytest.raises(NotConfigured, match="master key"):
        ApolloConnector(db, src, client=client).run("enrich_contacts", {})
