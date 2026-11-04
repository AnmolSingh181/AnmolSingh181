import os
from pathlib import Path

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/plastic_intel_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["OPENAI_API_KEY"] = ""
os.environ["CRAWLER_MIN_DELAY_SECONDS"] = "0"
os.environ["ALERT_WEBHOOK_URL"] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import SessionLocal, get_engine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
KEEP = {"countries", "materials", "sources", "app_settings", "alembic_version"}


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(cfg, "head")
    from app.cli import seed_reference

    db = SessionLocal()
    seed_reference(db)
    db.close()
    yield


@pytest.fixture()
def db():
    from app.services.ingestion import reset_country_cache

    reset_country_cache()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
    eng = get_engine()
    with eng.begin() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))]
        wipe = [t for t in tables if t not in KEEP]
        c.execute(text(f"TRUNCATE {', '.join(wipe)} RESTART IDENTITY CASCADE"))
        c.execute(text("UPDATE sources SET config='{}', total_records=0, last_run_at=NULL, last_success_at=NULL, last_error=NULL"))


def site_transport():
    """Serves tests/fixtures/site as https://fixture-polymers.example plus two linked sites."""
    routes = {"/": "index.html", "/about-us": "about.html", "/products": "products.html", "/contact": "contact.html",
              "/distributors": "distributors.html", "/robots.txt": "robots.txt", "/sitemap.xml": "sitemap.xml"}
    other_hosts = {"fixture-trader.example": "trader.html", "fixture-bank.example": "bank.html"}

    def handler(request: httpx.Request):
        path = request.url.path.rstrip("/") or "/"
        host = request.url.host.removeprefix("www.")
        if host in other_hosts:
            if path == "/robots.txt":
                return httpx.Response(404)
            f = other_hosts[host] if path == "/" else None
        elif host == "fixture-polymers.example":
            if path.startswith("/private"):
                raise AssertionError("crawler fetched a robots-disallowed URL")
            f = routes.get(path)
        else:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        if not f:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        ctype = "text/plain" if f.endswith(".txt") else "application/xml" if f.endswith(".xml") else "text/html; charset=utf-8"
        return httpx.Response(200, text=(FIXTURES / "site" / f).read_text(), headers={"content-type": ctype})

    return httpx.MockTransport(handler)


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.cli import create_admin
    from app.main import app

    create_admin(db, "admin@test.example", "test-password-123")
    c = TestClient(app)
    tok = c.post("/auth/login", json={"email": "admin@test.example", "password": "test-password-123"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c
