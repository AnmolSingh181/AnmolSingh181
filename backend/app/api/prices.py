"""Market prices: price board, series history, cross-market comparison, manual entry, import, FX and alerts."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import enums as E
from app.auth import current_user, log_activity, require_editor
from app.db import get_db
from app.models import Material, PriceAlertRule, PricePoint, PriceSeries, ScrapeJob, Source, User
from app.services import prices as P

router = APIRouter(prefix="/prices", tags=["prices"])

PRICE_SOURCES = ("fred", "dce", "price_feed", "plastemart")


def _series(db: Session, series_id: int) -> PriceSeries:
    s = db.scalar(select(PriceSeries).options(selectinload(PriceSeries.material), selectinload(PriceSeries.source))
                  .where(PriceSeries.id == series_id))
    if not s:
        raise HTTPException(404, "price series not found")
    return s


def _cur(v: str) -> str:
    v = (v or "USD").upper()
    if not re.fullmatch(r"[A-Z]{3}", v):
        raise HTTPException(422, "currency must be a 3-letter ISO code")
    return v


def _unit(v: str) -> str:
    if v not in P.MASS_UNITS:
        raise HTTPException(422, f"unit must be one of {sorted(P.MASS_UNITS)}")
    return v


@router.get("/board")
def price_board(currency: str = "USD", unit: str = "t", material: list[str] = Query(default=[]),
                country: list[str] = Query(default=[]), price_type: list[str] = Query(default=[]),
                include_inactive: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Latest price of every tracked series, with moves and a value normalised to `currency`/`unit`."""
    return P.board(db, _cur(currency), _unit(unit), material or None, country or None, price_type or None,
                   include_inactive)


@router.get("/meta")
def price_meta(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"price_types": E.PRICE_TYPES, "frequencies": E.PRICE_FREQUENCIES, "units": E.PRICE_UNITS,
            "alert_conditions": E.PRICE_ALERT_CONDITIONS,
            "sources": [{"key": s.key, "name": s.name, "status": s.status, "enabled": s.enabled}
                        for s in db.scalars(select(Source).where(Source.source_type == "market_data")
                                            .order_by(Source.id)).all()]
            + [{"key": "price_import", "name": "Manual entry / import", "status": "active", "enabled": True}]}


@router.get("/compare")
def price_compare(material: str, currency: str = "USD", unit: str = "t", date_from: date | None = None,
                  series: list[int] = Query(default=[]), db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    """Every priced series of one material (e.g. LLDPE in India, China, USA) normalised to one currency/unit."""
    return P.compare(db, material.upper(), _cur(currency), _unit(unit), date_from, series or None)


@router.get("/fx")
def fx_rates(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return P.FxBook(db).latest()


class FxIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate_date: date
    per_usd: float = Field(gt=0)


@router.post("/fx", status_code=201)
def add_fx(body: FxIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Manual FX rate (units of currency per 1 USD), for currencies without an automatic feed."""
    P.upsert_fx(db, _cur(body.currency), body.rate_date, body.per_usd, "manual")
    db.commit()
    return {"currency": body.currency.upper(), "rate_date": body.rate_date, "per_usd": body.per_usd}


# ------------------------------------------------------------------ series
class SeriesIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{3,80}$")
    name: str = Field(min_length=3, max_length=200)
    material: str | None = None
    grade: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    location: str | None = None
    price_type: str
    currency: str | None = None
    unit: str
    incoterm: str | None = None
    frequency: str = "daily"
    source_key: str = "price_import"
    external_code: str | None = None
    config: dict = {}
    is_active: bool = True
    notes: str | None = None


class SeriesPatch(BaseModel):
    name: str | None = None
    material: str | None = None
    grade: str | None = None
    country_code: str | None = None
    location: str | None = None
    price_type: str | None = None
    currency: str | None = None
    unit: str | None = None
    incoterm: str | None = None
    frequency: str | None = None
    source_key: str | None = None
    external_code: str | None = None
    config: dict | None = None
    is_active: bool | None = None
    notes: str | None = None


def _apply(db: Session, s: PriceSeries, data: dict):
    if "price_type" in data and data["price_type"] not in E.PRICE_TYPES:
        raise HTTPException(422, f"price_type must be one of {E.PRICE_TYPES}")
    if "unit" in data and data["unit"] not in E.PRICE_UNITS:
        raise HTTPException(422, f"unit must be one of {E.PRICE_UNITS}")
    if "frequency" in data and data["frequency"] not in E.PRICE_FREQUENCIES:
        raise HTTPException(422, f"frequency must be one of {E.PRICE_FREQUENCIES}")
    if "material" in data:
        code = data.pop("material")
        if code:
            m = db.scalar(select(Material).where(Material.code == code.upper()))
            if not m:
                raise HTTPException(422, f"unknown material {code}")
            s.material = m
        else:
            s.material = None
    if "source_key" in data:
        key = data.pop("source_key")
        src = db.scalar(select(Source).where(Source.key == key))
        if not src:
            raise HTTPException(422, f"unknown source {key}")
        s.source = src
    if data.get("currency"):
        data["currency"] = _cur(data["currency"])
    if data.get("country_code"):
        data["country_code"] = data["country_code"].upper()
    if "config" in data and isinstance(data["config"], dict):
        hdrs = data["config"].get("headers") or {}
        if any(isinstance(v, str) and not v.startswith("${ENV:") and v != "***" for v in hdrs.values()):
            raise HTTPException(422, "feed headers must reference secrets as ${ENV:VAR_NAME}, not literal values")
        if hdrs and s.config and isinstance(s.config.get("headers"), dict):  # keep masked values unchanged
            data["config"]["headers"] = {k: (s.config["headers"].get(k, v) if v == "***" else v)
                                         for k, v in hdrs.items()}
    for k, v in data.items():
        setattr(s, k, v)
    if s.price_type != "index" and s.unit != "index" and not s.currency:
        raise HTTPException(422, "currency is required for priced series")


@router.get("/series")
def list_series(include_inactive: bool = True, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(PriceSeries).options(selectinload(PriceSeries.material), selectinload(PriceSeries.source))
    if not include_inactive:
        q = q.where(PriceSeries.is_active)
    return [P.series_out(s) for s in db.scalars(q.order_by(PriceSeries.id)).all()]


@router.post("/series", status_code=201)
def create_series(body: SeriesIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    if db.scalar(select(PriceSeries.id).where(PriceSeries.key == body.key)):
        raise HTTPException(409, "a series with this key already exists")
    s = PriceSeries(key=body.key, config={})
    _apply(db, s, body.model_dump(exclude={"key"}))
    db.add(s)
    db.flush()
    log_activity(db, user, "create_price_series", "price_series", str(s.id), {"key": s.key})
    db.commit()
    return P.series_out(_series(db, s.id))


@router.patch("/series/{series_id}")
def update_series(series_id: int, body: SeriesPatch, db: Session = Depends(get_db),
                  user: User = Depends(require_editor)):
    s = _series(db, series_id)
    _apply(db, s, body.model_dump(exclude_unset=True))
    log_activity(db, user, "update_price_series", "price_series", str(s.id), body.model_dump(exclude_unset=True))
    db.commit()
    return P.series_out(_series(db, s.id))


@router.get("/series/{series_id}/history")
def series_history(series_id: int, date_from: date | None = None, date_to: date | None = None,
                   currency: str | None = None, unit: str | None = None, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    s = _series(db, series_id)
    return P.history(db, s, date_from, date_to, _cur(currency) if currency else None, _unit(unit) if unit else None)


class PointIn(BaseModel):
    observed_at: date | datetime
    price: float = Field(gt=0)
    low: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2000)


@router.post("/series/{series_id}/points", status_code=201)
def add_point(series_id: int, body: PointIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Manual price entry, e.g. from a producer price circular. State the basis (ex-works, GST...) in `note`."""
    s = _series(db, series_id)
    if body.low and body.high and body.low > body.high:
        raise HTTPException(422, "low must not exceed high")
    obs = body.observed_at
    if (obs.date() if isinstance(obs, datetime) else obs) > date.today():
        raise HTTPException(422, "observed_at cannot be in the future")
    out = P.record_point(db, s, obs, body.price, low=body.low, high=body.high, origin="manual",
                         source_url=body.source_url, note=body.note, user_id=user.id)
    log_activity(db, user, "add_price_point", "price_series", str(s.id),
                 {"observed_at": str(obs), "price": body.price})
    db.commit()
    return {**P.point_out(out.point), "created": out.created}


@router.delete("/points/{point_id}", status_code=204)
def delete_point(point_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    p = db.get(PricePoint, point_id)
    if not p:
        raise HTTPException(404)
    if p.origin == "connector":
        raise HTTPException(400, "connector data is re-collected automatically; deactivate the series instead")
    log_activity(db, user, "delete_price_point", "price_series", str(p.series_id),
                 {"observed_at": p.observed_at.isoformat(), "price": float(p.price)})
    db.delete(p)
    db.commit()


@router.post("/import")
async def import_prices(file: UploadFile = File(...), series_key: str | None = Form(None),
                        db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """CSV/XLSX with columns series_key, date, price[, low, high, note, source_url]. `series_key` form field
    applies to files that have no series column."""
    from app.connectors.imports import read_table

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10MB)")
    try:
        _, rows = read_table(content, file.filename or "prices.csv")
    except Exception as exc:
        raise HTTPException(422, f"could not read file: {exc}")
    res = P.import_price_rows(db, rows, default_series_key=series_key, user_id=user.id)
    src = db.scalar(select(Source).where(Source.key == "price_import"))
    if src:
        src.last_run_at = src.last_success_at = datetime.now(timezone.utc)
        src.total_records = (src.total_records or 0) + res["created"]
    log_activity(db, user, "import_prices", details={"file": file.filename, **{k: res[k] for k in
                                                                                 ("rows", "created", "failed")}})
    db.commit()
    return res


@router.post("/refresh")
def refresh_prices(run_now: bool = False, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Queue (or run immediately) all enabled price connectors."""
    from app.workers.runner import enqueue, execute

    jobs = []
    for key in PRICE_SOURCES:
        src = db.scalar(select(Source).where(Source.key == key))
        if not src or not src.enabled:
            jobs.append({"source": key, "status": "skipped", "reason": f"source {src.status if src else 'missing'}"
                                                                       " / not enabled"})
            continue
        job = enqueue(db, key, "refresh", {}, priority=20, user_id=user.id)
        db.commit()
        if run_now:
            job.status, job.started_at, job.attempts = "running", datetime.now(timezone.utc), 1
            db.commit()
            job = execute(db, job)
        job = db.get(ScrapeJob, job.id)
        jobs.append({"source": key, "job_id": job.id, "status": job.status, "created": job.records_created,
                     "updated": job.records_updated, "error": job.error_message})
    return {"jobs": jobs}


# ------------------------------------------------------------------ alerts
class AlertIn(BaseModel):
    series_id: int
    condition: str
    threshold: float


def _alert_out(r: PriceAlertRule) -> dict:
    return {"id": r.id, "series_id": r.series_id, "series_name": r.series.name if r.series else None,
            "condition": r.condition, "threshold": float(r.threshold), "is_active": r.is_active,
            "last_triggered_at": r.last_triggered_at, "created_at": r.created_at}


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(PriceAlertRule).options(selectinload(PriceAlertRule.series))
                      .order_by(PriceAlertRule.id)).all()
    return [_alert_out(r) for r in rows]


@router.post("/alerts", status_code=201)
def create_alert_rule(body: AlertIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    if body.condition not in E.PRICE_ALERT_CONDITIONS:
        raise HTTPException(422, f"condition must be one of {E.PRICE_ALERT_CONDITIONS}")
    if body.condition == "change_pct" and not (0 < abs(body.threshold) <= 100):
        raise HTTPException(422, "change_pct threshold is a percentage between 0 and 100")
    if body.condition != "change_pct" and body.threshold <= 0:
        raise HTTPException(422, "threshold must be a positive price")
    _series(db, body.series_id)
    r = PriceAlertRule(series_id=body.series_id, condition=body.condition, threshold=body.threshold,
                       created_by=user.id)
    db.add(r)
    db.commit()
    return _alert_out(db.scalar(select(PriceAlertRule).options(selectinload(PriceAlertRule.series))
                                .where(PriceAlertRule.id == r.id)))


@router.delete("/alerts/{rule_id}", status_code=204)
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    r = db.get(PriceAlertRule, rule_id)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
