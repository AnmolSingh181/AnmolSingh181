"""Market price tracking: connectors (mocked HTTP), normalisation, board/compare, manual entry, import, alerts."""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.connectors.prices import DceConnector, FredConnector, PriceFeedConnector
from app.models import Alert, FxRate, PriceAlertRule, PricePoint, PriceSeries, ScrapeJob, Source
from app.services import prices as P
from app.services.http import PoliteClient


def _client(handler) -> PoliteClient:
    return PoliteClient(min_delay=0, transport=httpx.MockTransport(handler))


def _job(db, key, job_type="refresh"):
    src = db.scalar(select(Source).where(Source.key == key))
    job = ScrapeJob(source_id=src.id, job_type=job_type, params={}, status="running")
    db.add(job)
    db.flush()
    return src, job


def _series(db, key) -> PriceSeries:
    return db.scalar(select(PriceSeries).where(PriceSeries.key == key))


def test_default_series_seeded(db):
    keys = {s.key for s in db.scalars(select(PriceSeries)).all()}
    assert {"us_ppi_plastic_resins", "dce_lldpe", "in_lldpe_film_list", "brent_spot"} <= keys
    s = _series(db, "dce_lldpe")
    assert s.material.code == "LLDPE" and s.currency == "CNY" and s.unit == "t" and s.source.key == "dce"


# ------------------------------------------------------------------ FRED
FRED_CSV = "observation_date,WPU066\n2026-06-01,251.2\n2026-07-01,.\n2026-08-01,256.209\n"
FX_CSV = {"DEXINUS": "observation_date,DEXINUS\n2026-08-01,84.00\n2026-09-01,85.00\n",
          "DEXCHUS": "observation_date,DEXCHUS\n2026-08-01,7.10\n2026-09-01,7.20\n",
          "DEXUSEU": "observation_date,DEXUSEU\n2026-09-01,1.25\n"}


def test_fred_parsers():
    assert FredConnector.parse_csv(FRED_CSV) == [(date(2026, 6, 1), 251.2), (date(2026, 8, 1), 256.209)]
    assert FredConnector.parse_csv("DATE,X\n2020-01-01,1.5\n") == [(date(2020, 1, 1), 1.5)]
    with pytest.raises(ValueError):
        FredConnector.parse_csv("<html>error</html>")
    assert FredConnector.parse_json({"observations": [{"date": "2026-01-01", "value": "."},
                                                      {"date": "2026-02-01", "value": "3.5"}]}) == \
        [(date(2026, 2, 1), 3.5)]


def test_fred_refresh_stores_series_and_fx(db, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    seen = []

    def handler(req: httpx.Request):
        sid = req.url.params.get("id")
        seen.append(sid)
        if sid in FX_CSV:
            return httpx.Response(200, text=FX_CSV[sid])
        if sid == "WPU066":
            return httpx.Response(200, text=FRED_CSV)
        return httpx.Response(200, text=f"observation_date,{sid}\n")

    src, job = _job(db, "fred")
    stats = FredConnector(db, src, job, client=_client(handler)).run("refresh", {"currencies": ["INR", "CNY", "EUR"]})
    db.commit()
    assert {"DEXINUS", "DEXCHUS", "DEXUSEU", "WPU066", "DCOILBRENTEU"} <= set(seen)
    pts = db.scalars(select(PricePoint).join(PriceSeries).where(PriceSeries.key == "us_ppi_plastic_resins")
                     .order_by(PricePoint.observed_at)).all()
    assert [float(p.price) for p in pts] == [251.2, 256.209]
    assert pts[0].source_url == "https://fred.stlouisfed.org/series/WPU066"
    eur = db.scalar(select(FxRate).where(FxRate.currency == "EUR"))
    assert float(eur.per_usd) == pytest.approx(0.8)  # DEXUSEU is USD per EUR -> inverted
    assert stats.created >= 2 + 5

    # second run: unchanged data creates nothing, revised value updates in place
    revised = FRED_CSV.replace("256.209", "257.0")
    h2 = lambda req: httpx.Response(200, text=revised if req.url.params.get("id") == "WPU066"  # noqa: E731
                                    else f"observation_date,{req.url.params.get('id')}\n")
    stats2 = FredConnector(db, src, job, client=_client(h2)).run("fetch_series", {})
    db.commit()
    assert stats2.created == 0 and stats2.updated == 1
    assert float(db.scalars(select(PricePoint.price).join(PriceSeries).where(
        PriceSeries.key == "us_ppi_plastic_resins").order_by(PricePoint.observed_at.desc())).first()) == 257.0


# ------------------------------------------------------------------ DCE
def test_dce_requires_credentials(db, monkeypatch):
    from app.connectors.base import NotConfigured

    monkeypatch.delenv("DCE_API_KEY", raising=False)
    src, job = _job(db, "dce")
    with pytest.raises(NotConfigured):
        DceConnector(db, src, job).run("refresh", {})


def test_dce_main_contract_settlement(db, monkeypatch):
    monkeypatch.setenv("DCE_API_KEY", "k")
    monkeypatch.setenv("DCE_SECRET", "s")
    calls = {"token": 0}
    today = date.today()

    def handler(req: httpx.Request):
        if req.url.path.endswith("/accessToken"):
            calls["token"] += 1
            assert req.headers["apikey"] == "k" and json.loads(req.content) == {"secret": "s"}
            return httpx.Response(200, json={"code": 200, "msg": "ok", "data": {"token": "T", "expiresIn": 3600}})
        body = json.loads(req.content)
        assert req.headers["authorization"] == "Bearer T"
        v = body["varietyId"]
        if v != "l":
            return httpx.Response(200, json={"code": 200, "data": []})
        return httpx.Response(200, json={"code": 200, "data": [
            {"variety": "LLDPE", "contractId": "l2601", "clearPrice": "7210", "close": "7200", "low": "7150",
             "high": "7260", "volumn": 350000, "openInterest": 600000},
            {"variety": "LLDPE", "contractId": "l2605", "clearPrice": "7300", "openInterest": 120000},
            {"variety": "LLDPE小计", "contractId": "", "openInterest": 720000},
        ]})

    src, job = _job(db, "dce")
    src.config = {}
    stats = DceConnector(db, src, job, client=_client(handler)).run("refresh", {"start": (today - timedelta(days=6)).isoformat()})
    db.commit()
    pts = db.scalars(select(PricePoint).join(PriceSeries).where(PriceSeries.key == "dce_lldpe")).all()
    weekdays = sum(1 for i in range(7) if (today - timedelta(days=6 - i)).weekday() < 5)
    assert len(pts) == weekdays and stats.created == weekdays
    p = pts[0]
    assert float(p.price) == 7210 and p.contract == "l2601" and float(p.open_interest) == 600000
    assert float(p.price_low) == 7150 and calls["token"] == 1


# ------------------------------------------------------------------ generic feed
def test_price_feed_csv_with_filter_and_env_header(db, monkeypatch):
    monkeypatch.setenv("FEED_TOKEN", "secret-token")
    s = _series(db, "in_lldpe_film_list")
    s.source_id = db.scalar(select(Source.id).where(Source.key == "price_feed"))
    s.config = {"feed_url": "https://sheets.example/pub?output=csv", "date_field": "Date", "price_field": "Price",
                "filter": {"field": "Grade", "equals": "LLDPE film"},
                "headers": {"Authorization": "Bearer ${ENV:FEED_TOKEN}"}}
    db.commit()
    csv_text = ("Date,Grade,Price\n01/10/2026,LLDPE film,104.5\n08/10/2026,LLDPE film,106\n"
                "08/10/2026,HDPE film,99\n")

    def handler(req):
        assert req.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(200, text=csv_text, headers={"content-type": "text/csv"})

    src, job = _job(db, "price_feed")
    stats = PriceFeedConnector(db, src, job, client=_client(handler)).run("refresh", {})
    db.commit()
    assert stats.created == 2
    prices = sorted(float(p.price) for p in db.scalars(select(PricePoint).where(PricePoint.series_id == s.id)))
    assert prices == [104.5, 106.0]


def test_price_feed_json_missing_env_fails_cleanly(db, monkeypatch):
    monkeypatch.delenv("NOPE_TOKEN", raising=False)
    s = _series(db, "us_lldpe_export")
    s.source_id = db.scalar(select(Source.id).where(Source.key == "price_feed"))
    s.config = {"feed_url": "https://api.example/prices?token=${ENV:NOPE_TOKEN}", "format": "json"}
    db.commit()
    src, job = _job(db, "price_feed")
    stats = PriceFeedConnector(db, src, job, client=_client(lambda r: httpx.Response(500))).run("refresh", {})
    assert stats.failed == 1 and "NOPE_TOKEN" in stats.log[-1]["msg"]


# ------------------------------------------------------------------ normalisation / board / alerts
def _fx(db):
    P.upsert_fx(db, "INR", date(2026, 1, 1), 80.0, "test")
    P.upsert_fx(db, "INR", date(2026, 10, 1), 84.0, "test")
    P.upsert_fx(db, "CNY", date(2026, 1, 1), 7.0, "test")
    db.flush()


def test_convert_currency_and_units(db):
    _fx(db)
    fx = P.FxBook(db)
    # INR 100/kg on 2026-10-15 -> USD/t at 84 INR/USD
    assert P.convert(100, "INR", "kg", "USD", "t", fx, date(2026, 10, 15)) == pytest.approx(100 / 84 * 1000)
    # rate in force on the date, not the latest
    assert P.convert(100, "INR", "kg", "USD", "kg", fx, date(2026, 5, 1)) == pytest.approx(1.25)
    # CNY/t -> INR/kg
    assert P.convert(7000, "CNY", "t", "INR", "kg", fx, date(2026, 10, 2)) == pytest.approx(84.0)
    # USD/lb -> USD/t
    assert P.convert(0.5, "USD", "lb", "USD", "t", fx, None) == pytest.approx(0.5 / 0.45359237 * 1000)
    # pegged currency without stored rates
    assert P.convert(3672.5, "AED", "t", "USD", "t", fx, None) == pytest.approx(1000)
    # not convertible
    assert P.convert(250, None, "index", "USD", "t", fx, None) is None
    assert P.convert(80, "USD", "bbl", "USD", "t", fx, None) is None
    assert P.convert(10, "VND", "kg", "USD", "kg", fx, None) is None


def test_board_compare_and_alerts(db, client):
    _fx(db)
    inl, cn = _series(db, "in_lldpe_film_list"), _series(db, "dce_lldpe")
    db.add(PriceAlertRule(series_id=inl.id, condition="above", threshold=105))
    db.add(PriceAlertRule(series_id=inl.id, condition="change_pct", threshold=5))
    db.commit()
    today = date.today()
    for d, v in ((today - timedelta(days=40), 100.0), (today - timedelta(days=10), 102.0), (today - timedelta(days=1), 108.0)):
        P.record_point(db, inl, d, v, origin="manual")
    P.record_point(db, cn, today - timedelta(days=1), 7210.0)
    db.commit()
    alerts = db.scalars(select(Alert).where(Alert.alert_type == "price_alert")).all()
    msgs = " | ".join(a.message for a in alerts)
    assert "rose above 105.00" in msgs and "+5.88%" in msgs
    # back-filling an older point never alerts
    P.record_point(db, inl, today - timedelta(days=60), 150.0)
    db.commit()
    assert len(db.scalars(select(Alert).where(Alert.alert_type == "price_alert")).all()) == len(alerts)

    r = client.get("/prices/board", params={"currency": "USD", "unit": "t", "material": "LLDPE"})
    assert r.status_code == 200
    items = {i["key"]: i for i in r.json()["items"]}
    row = items["in_lldpe_film_list"]
    assert row["latest"]["price"] == 108.0 and row["change_pct"] == pytest.approx(5.88, abs=0.01)
    assert row["change_1m_pct"] == pytest.approx(8.0)  # vs 100 (40 days ago)
    assert row["normalized"] == pytest.approx(108 / 84 * 1000, rel=1e-4) and row["normalized_unit"] == "USD/t"
    assert row["is_stale"] is False and len(row["spark"]) == 4
    assert items["us_lldpe_export"]["latest"] is None  # seeded but no data yet - shown, never invented
    assert any(f["currency"] == "INR" for f in r.json()["fx"])

    c = client.get("/prices/compare", params={"material": "LLDPE", "currency": "INR", "unit": "kg",
                                               "date_from": (today - timedelta(days=90)).isoformat()}).json()
    lines = {line["key"]: line for line in c["series"]}
    assert set(lines) == {"in_lldpe_film_list", "dce_lldpe"}
    assert lines["dce_lldpe"]["data"][-1]["v"] == pytest.approx(7210 / 7.0 * 84 / 1000, rel=1e-4)

    h = client.get(f"/prices/series/{inl.id}/history", params={"currency": "USD", "unit": "kg"}).json()
    assert len(h["points"]) == 4 and h["normalized_unit"] == "USD/kg"


def test_manual_entry_import_and_series_api(client, db):
    s = _series(db, "in_pp_raffia_list")
    r = client.post(f"/prices/series/{s.id}/points", json={"observed_at": "2026-10-01", "price": 98.5,
                                                            "note": "ex-Mumbai, excl. GST"})
    assert r.status_code == 201 and r.json()["origin"] == "manual" and r.json()["created"]
    assert client.post(f"/prices/series/{s.id}/points", json={"observed_at": "2999-01-01", "price": 1}).status_code == 422
    assert client.post(f"/prices/series/{s.id}/points", json={"observed_at": "2026-10-01", "price": -1}).status_code == 422

    csv_bytes = (b"series_key,date,price,note\nin_pp_raffia_list,2026-10-08,99.75,circular 41\n"
                 b"in_pp_raffia_list,2026-10-01,98.5,\nunknown_key,2026-10-08,1,\nin_pp_raffia_list,bad,1,\n")
    res = client.post("/prices/import", files={"file": ("p.csv", csv_bytes, "text/csv")}).json()
    assert res["created"] == 1 and res["failed"] == 2 and res["rows"] == 4

    new = client.post("/prices/series", json={"key": "vn_hdpe_cfr", "name": "Vietnam HDPE film CFR HCMC",
                                              "material": "HDPE", "country_code": "vn", "price_type": "assessment",
                                              "currency": "usd", "unit": "t", "frequency": "weekly"})
    assert new.status_code == 201, new.text
    assert new.json()["country_code"] == "VN" and new.json()["currency"] == "USD"
    assert client.post("/prices/series", json={"key": "vn_hdpe_cfr", "name": "dup", "price_type": "spot",
                                               "currency": "USD", "unit": "t"}).status_code == 409
    bad = client.patch(f"/prices/series/{new.json()['id']}",
                       json={"config": {"feed_url": "https://x.example", "headers": {"Authorization": "Bearer abc"}}})
    assert bad.status_code == 422  # literal secrets are refused
    ok = client.patch(f"/prices/series/{new.json()['id']}",
                      json={"source_key": "price_feed", "config": {"feed_url": "https://x.example",
                                                                   "headers": {"Authorization": "${ENV:X_TOKEN}"}}})
    assert ok.status_code == 200 and ok.json()["source_key"] == "price_feed"

    a = client.post("/prices/alerts", json={"series_id": s.id, "condition": "below", "threshold": 90})
    assert a.status_code == 201 and client.get("/prices/alerts").json()[0]["series_name"]
    assert client.post("/prices/alerts", json={"series_id": s.id, "condition": "change_pct",
                                               "threshold": 500}).status_code == 422

    fx = client.post("/prices/fx", json={"currency": "vnd", "rate_date": "2026-10-01", "per_usd": 25400})
    assert fx.status_code == 201
    assert any(f["currency"] == "VND" for f in client.get("/prices/fx").json())

    pt = db.scalar(select(PricePoint).where(PricePoint.series_id == s.id, PricePoint.origin == "import"))
    assert client.delete(f"/prices/points/{pt.id}").status_code == 204


def test_refresh_skips_disabled_sources(client, db):
    r = client.post("/prices/refresh").json()
    by = {j["source"]: j for j in r["jobs"]}
    assert by["dce"]["status"] == "skipped"  # awaiting credentials -> not enabled by default
    assert by["fred"]["status"] == "queued"
