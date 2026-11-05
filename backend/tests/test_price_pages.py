"""HTML price-list connector (used for Plastemart). The page below is a SYNTHETIC fixture written for these tests:
it is not a copy of plastemart.com's layout, which could not be fetched from the build environment."""
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.connectors.base import TermsNotConfirmed
from app.connectors.price_pages import (PlastemartConnector, extract_rows, parse_effective_date, parse_price_cell)
from app.models import PricePoint, PriceSeries, ScrapeJob, Source
from app.services.http import PoliteClient

PAGE = """<html><body>
<h2>Reliance Industries Ltd - Domestic Polymer Prices w.e.f. 1st Nov 2026</h2>
<table>
  <tr><th>Polymer</th><th>Grade</th><th>Application</th><th>Price (Rs/MT)</th></tr>
  <tr><td>LLDPE</td><td>F18010</td><td>Film (Butene)</td><td>1,04,500</td></tr>
  <tr><td>HDPE</td><td>F46003</td><td>Film</td><td>1,02,000 - 1,03,000</td></tr>
  <tr><td>PP</td><td>H030SG</td><td>Raffia</td><td>98,750</td></tr>
  <tr><td>PVC</td><td>K67</td><td>Suspension, pipe</td><td>9,999,999</td></tr>
  <tr><td>EVA</td><td>1802</td><td>Footwear</td><td>1,50,000</td></tr>
</table>
<h2>Indian Oil Corporation price list</h2>
<table>
  <tr><th>Product</th><th>Date</th><th>Basic Price (INR/MT)</th></tr>
  <tr><td>LLDPE film butene</td><td>01.11.2026</td><td>1,04,000</td></tr>
</table>
<table><tr><td>Unrelated</td><td>layout table</td></tr></table>
</body></html>"""


def _client(page=PAGE, robots="User-agent: *\nAllow: /\n"):
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"})
    return PoliteClient(min_delay=0, transport=httpx.MockTransport(handler))


def _job(db, cfg):
    src = db.scalar(select(Source).where(Source.key == "plastemart"))
    src.config = cfg
    job = ScrapeJob(source_id=src.id, job_type="refresh", params={}, status="running")
    db.add(job)
    db.flush()
    return src, job


def _points(db, key):
    return db.scalars(select(PricePoint).join(PriceSeries).where(PriceSeries.key == key)).all()


def test_helpers():
    assert parse_effective_date("Prices w.e.f. 1st Nov 2026") == date(2026, 11, 1)
    assert parse_effective_date("with effect from 15 November 2026") == date(2026, 11, 15)
    assert parse_effective_date("effective from 01.11.2026") == date(2026, 11, 1)
    assert parse_effective_date("no date here") is None
    assert parse_price_cell("1,04,500") == (104500, None, None)
    assert parse_price_cell("Rs 1,02,000 - 1,03,000 /MT") == (102500, 102000, 103000)
    assert parse_price_cell("on request") == (None, None, None)
    rows = extract_rows(PAGE)
    assert len(rows) == 6 and rows[0]["price_header"] == "Price (Rs/MT)"
    assert "w.e.f. 1st Nov 2026" in rows[0]["context"]


def test_disabled_until_terms_confirmed(db):
    src, job = _job(db, {})
    with pytest.raises(TermsNotConfirmed):
        PlastemartConnector(db, src, job, client=_client()).run("refresh", {})


def test_maps_rows_to_india_series(db):
    src, job = _job(db, {"terms_confirmed": True})
    stats = PlastemartConnector(db, src, job, client=_client()).run("refresh", {})
    db.commit()
    lldpe = _points(db, "in_lldpe_film_list")
    assert len(lldpe) == 1  # Reliance benchmark only; the IOCL row does not match the default producer rule
    p = lldpe[0]
    assert float(p.price) == 104.5 and p.observed_at.date() == date(2026, 11, 1)  # INR/MT -> INR/kg
    assert p.origin == "connector" and "F18010" in p.note and p.source_url.endswith("polymer-price-list-pe-pp-pvc")
    hdpe = _points(db, "in_hdpe_film_list")[0]
    assert float(hdpe.price) == 102.5 and float(hdpe.price_low) == 102 and float(hdpe.price_high) == 103
    assert float(_points(db, "in_pp_raffia_list")[0].price) == 98.75
    assert _points(db, "in_pvc_list") == []  # 9,999.999/kg rejected as implausible
    msgs = " ".join(e["msg"] for e in stats.log)
    assert "implausible" in msgs and "EVA" in msgs  # unmatched rows are logged, not stored
    assert stats.created == 3


def test_custom_rules_and_robots(db):
    rules = [{"series_key": "in_lldpe_film_list", "polymer": "LLDPE", "grade": "film", "producer": "indian oil|iocl"}]
    src, job = _job(db, {"terms_confirmed": True, "rules": rules})
    PlastemartConnector(db, src, job, client=_client()).run("refresh", {})
    db.commit()
    assert [float(p.price) for p in _points(db, "in_lldpe_film_list")] == [104.0]

    src, job = _job(db, {"terms_confirmed": True})
    stats = PlastemartConnector(db, src, job, client=_client(robots="User-agent: *\nDisallow: /\n")).run("refresh", {})
    assert stats.failed == 1 and "robots" in stats.log[0]["msg"]
