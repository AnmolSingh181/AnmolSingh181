"""Market price tracking: storing observations, FX/unit normalisation, the price board, comparisons and alerts.

Prices are stored exactly as published (native currency and unit). Normalisation to a display currency/unit happens
at read time using the FX rate in force on the observation date, so a price is never silently rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import FxRate, Material, PriceAlertRule, PricePoint, PriceSeries
from app.services.alerts import create_alert
from app.services.settings_store import get_setting

LB_KG = 0.45359237
# price per <unit>  ->  multiply by this to get price per kg
PER_KG = {"kg": 1.0, "t": 1 / 1000.0, "lb": 1 / LB_KG}
MASS_UNITS = set(PER_KG)


# ------------------------------------------------------------------ FX
class FxBook:
    """FX lookups for one request: units of currency per USD on (or before) a date. Loaded lazily per currency."""

    def __init__(self, db: Session):
        self.db = db
        self._rates: dict[str, list[tuple[date, float]]] = {}
        self._pegs = {k.upper(): float(v) for k, v in (get_setting(db, "price_tracking").get("fx_pegs") or {}).items()}

    def _load(self, cur: str) -> list[tuple[date, float]]:
        if cur not in self._rates:
            rows = self.db.execute(select(FxRate.rate_date, FxRate.per_usd).where(FxRate.currency == cur)
                                   .order_by(FxRate.rate_date)).all()
            self._rates[cur] = [(d, float(r)) for d, r in rows]
        return self._rates[cur]

    def per_usd(self, cur: str | None, on: date | None = None) -> float | None:
        if not cur:
            return None
        cur = cur.upper()
        if cur == "USD":
            return 1.0
        rows = self._load(cur)
        if rows:
            if on is None:
                return rows[-1][1]
            best = None
            for d, r in rows:  # rows are sorted; small (a few thousand) per currency
                if d <= on:
                    best = r
                else:
                    break
            return best if best is not None else rows[0][1]  # before history starts: earliest known rate
        return self._pegs.get(cur)

    def latest(self) -> list[dict]:
        sub = select(FxRate.currency, func.max(FxRate.rate_date).label("d")).group_by(FxRate.currency).subquery()
        rows = self.db.execute(select(FxRate).join(sub, (FxRate.currency == sub.c.currency) &
                                                   (FxRate.rate_date == sub.c.d)).order_by(FxRate.currency)).scalars()
        out = [{"currency": r.currency, "per_usd": float(r.per_usd), "rate_date": r.rate_date, "source": r.source}
               for r in rows]
        have = {o["currency"] for o in out}
        out += [{"currency": c, "per_usd": v, "rate_date": None, "source": "peg"} for c, v in self._pegs.items()
                if c not in have]
        return sorted(out, key=lambda o: o["currency"])


def upsert_fx(db: Session, currency: str, rate_date: date, per_usd: float, source: str) -> bool:
    row = db.scalar(select(FxRate).where(FxRate.currency == currency.upper(), FxRate.rate_date == rate_date))
    if row:
        row.per_usd, row.source = per_usd, source
        return False
    db.add(FxRate(currency=currency.upper(), rate_date=rate_date, per_usd=per_usd, source=source))
    return True


def convert(price: float | None, currency: str | None, unit: str, to_currency: str, to_unit: str, fx: FxBook,
            on: date | None) -> float | None:
    """Convert a price between currencies and mass units. None when not convertible (index, missing FX, bbl->t)."""
    if price is None or not currency:
        return None
    if unit != to_unit and not (unit in MASS_UNITS and to_unit in MASS_UNITS):
        return None
    src, dst = fx.per_usd(currency, on), fx.per_usd(to_currency, on)
    if not src or not dst:
        return None
    value = price / src * dst
    if unit != to_unit:
        value = value * PER_KG[unit] / PER_KG[to_unit]
    return value


# ------------------------------------------------------------------ storing points
def as_datetime(v: date | datetime) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.combine(v, time(0, 0), tzinfo=timezone.utc)


@dataclass
class PointOutcome:
    point: PricePoint
    created: bool
    changed: bool


def record_point(db: Session, series: PriceSeries, observed: date | datetime, price: float, *,
                 low: float | None = None, high: float | None = None, volume: float | None = None,
                 open_interest: float | None = None, contract: str | None = None, provisional: bool = False,
                 origin: str = "connector", source_url: str | None = None, note: str | None = None,
                 raw_record_id: int | None = None, user_id=None, evaluate_alerts: bool = True) -> PointOutcome:
    """Insert or update the point for (series, observed). Publishers revise data (e.g. preliminary PPI), so an
    existing point is updated in place when the value changes. New latest points are checked against alert rules."""
    if price is None or price <= 0:
        raise ValueError("price must be a positive number")
    when = as_datetime(observed)
    p = db.scalar(select(PricePoint).where(PricePoint.series_id == series.id, PricePoint.observed_at == when))
    created = p is None
    if created:
        p = PricePoint(series_id=series.id, observed_at=when, price=price)
        db.add(p)
        changed = True
    else:
        changed = float(p.price) != float(price) or bool(p.is_provisional) != provisional
    p.price, p.price_low, p.price_high, p.volume, p.open_interest = price, low, high, volume, open_interest
    p.contract, p.is_provisional, p.origin = contract, provisional, origin
    p.source_url, p.note = source_url or p.source_url, note if note is not None else p.note
    p.raw_record_id = raw_record_id or p.raw_record_id
    if user_id:
        p.created_by = user_id
    db.flush()
    if evaluate_alerts and changed:
        check_alerts(db, series, p)
    return PointOutcome(p, created, changed)


def _previous_point(db: Session, series_id: int, before: datetime) -> PricePoint | None:
    return db.scalar(select(PricePoint).where(PricePoint.series_id == series_id, PricePoint.observed_at < before)
                     .order_by(PricePoint.observed_at.desc()).limit(1))


def check_alerts(db: Session, series: PriceSeries, point: PricePoint) -> int:
    """Evaluate the series' active rules against `point` if it is the latest observation. Returns alerts raised."""
    latest = db.scalar(select(func.max(PricePoint.observed_at)).where(PricePoint.series_id == series.id))
    if latest and point.observed_at < latest:
        return 0  # back-filled history never triggers alerts
    rules = db.scalars(select(PriceAlertRule).where(PriceAlertRule.series_id == series.id,
                                                    PriceAlertRule.is_active)).all()
    if not rules:
        return 0
    prev = _previous_point(db, series.id, point.observed_at)
    price, n = float(point.price), 0
    unit = f"{series.currency or ''}/{series.unit}".strip("/")
    for r in rules:
        thr = float(r.threshold)
        msg = None
        if r.condition == "above" and price > thr and (prev is None or float(prev.price) <= thr):
            msg = f"{series.name}: {price:,.2f} {unit} rose above {thr:,.2f}"
        elif r.condition == "below" and price < thr and (prev is None or float(prev.price) >= thr):
            msg = f"{series.name}: {price:,.2f} {unit} fell below {thr:,.2f}"
        elif r.condition == "change_pct" and prev is not None and float(prev.price) > 0:
            chg = (price / float(prev.price) - 1) * 100
            if abs(chg) >= abs(thr):
                msg = (f"{series.name}: {chg:+.2f}% to {price:,.2f} {unit} "
                       f"(previous {float(prev.price):,.2f} on {prev.observed_at.date()})")
        if msg:
            create_alert(db, "price_alert", msg, entity_type="price_series", entity_id=str(series.id),
                         payload={"rule_id": r.id, "price": price, "observed_at": point.observed_at.isoformat()},
                         severity="warning")
            r.last_triggered_at = datetime.now(timezone.utc)
            n += 1
    return n


# ------------------------------------------------------------------ import
IMPORT_ALIASES = {
    "series_key": ("series_key", "series", "key", "series id", "series_id"),
    "date": ("date", "observed_at", "price_date", "as_of", "period"),
    "price": ("price", "value", "close", "settle", "settlement", "mid"),
    "low": ("low", "price_low", "min"),
    "high": ("high", "price_high", "max"),
    "note": ("note", "notes", "comment", "basis"),
    "source_url": ("source_url", "url", "source"),
    "contract": ("contract",),
}


def _num(v) -> float | None:
    if v in (None, "", "-", "."):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def import_price_rows(db: Session, rows: list[dict], default_series_key: str | None = None, user_id=None,
                      origin: str = "import") -> dict:
    """Rows with series_key/date/price (+ optional low/high/note/source_url). Returns counts and row errors."""
    from app.connectors.imports import parse_date

    series_by_key = {s.key: s for s in db.scalars(select(PriceSeries)).all()}
    created = updated = 0
    errors: list[dict] = []
    for i, raw in enumerate(rows, start=2):  # row 1 = header
        low_keys = {str(k).strip().lower(): v for k, v in raw.items() if k is not None}
        get = lambda f: next((low_keys[a] for a in IMPORT_ALIASES[f] if a in low_keys), None)  # noqa: E731
        key = str(get("series_key") or default_series_key or "").strip()
        s = series_by_key.get(key)
        d, price = parse_date(get("date")), _num(get("price"))
        if not s:
            errors.append({"row": i, "error": f"unknown series_key '{key}'"})
            continue
        if not d or price is None or price <= 0:
            errors.append({"row": i, "error": "missing/invalid date or price"})
            continue
        out = record_point(db, s, d, price, low=_num(get("low")), high=_num(get("high")),
                           contract=(str(get("contract")) if get("contract") else None), origin=origin,
                           source_url=(str(get("source_url")) if get("source_url") else None),
                           note=(str(get("note")) if get("note") else None), user_id=user_id)
        created += int(out.created)
        updated += int(not out.created and out.changed)
    return {"rows": len(rows), "created": created, "updated": updated, "failed": len(errors), "errors": errors[:50]}


# ------------------------------------------------------------------ read models
def series_out(s: PriceSeries) -> dict:
    return {"id": s.id, "key": s.key, "name": s.name, "material": s.material.code if s.material else None,
            "grade": s.grade, "country_code": s.country_code, "location": s.location, "price_type": s.price_type,
            "currency": s.currency, "unit": s.unit, "incoterm": s.incoterm, "frequency": s.frequency,
            "source_key": s.source.key if s.source else None, "source_name": s.source.name if s.source else None,
            "source_status": s.source.status if s.source else None, "external_code": s.external_code,
            "config": _public_config(s.config or {}), "is_active": s.is_active, "notes": s.notes}


def _public_config(cfg: dict) -> dict:
    """Never echo literal header values (they may hold tokens); ${ENV:...} references are fine to show."""
    out = dict(cfg)
    if isinstance(out.get("headers"), dict):
        out["headers"] = {k: (v if isinstance(v, str) and v.startswith("${ENV:") else "***")
                          for k, v in out["headers"].items()}
    return out


def point_out(p: PricePoint) -> dict:
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return {"id": p.id, "observed_at": p.observed_at, "price": f(p.price), "low": f(p.price_low),
            "high": f(p.price_high), "volume": f(p.volume), "open_interest": f(p.open_interest),
            "contract": p.contract, "is_provisional": p.is_provisional, "origin": p.origin,
            "source_url": p.source_url, "note": p.note, "collected_at": p.collected_at}


def _pct(a: float | None, b: float | None) -> float | None:
    return round((a / b - 1) * 100, 2) if a is not None and b else None


def _target_unit(series: PriceSeries, unit: str) -> str:
    return unit if series.unit in MASS_UNITS else series.unit


def board(db: Session, currency: str = "USD", unit: str = "t", material: list[str] | None = None,
          country: list[str] | None = None, price_type: list[str] | None = None, include_inactive: bool = False,
          spark_points: int = 30) -> dict:
    """Latest price per series with moves (1 point, ~1 week, ~1 month, ~1 year) and a normalised value."""
    q = select(PriceSeries).options(selectinload(PriceSeries.material), selectinload(PriceSeries.source))
    if not include_inactive:
        q = q.where(PriceSeries.is_active)
    if material:
        q = q.where(PriceSeries.material_id.in_(select(Material.id).where(Material.code.in_(material))))
    if country:
        q = q.where(PriceSeries.country_code.in_([c.upper() for c in country]))
    if price_type:
        q = q.where(PriceSeries.price_type.in_(price_type))
    series = db.scalars(q.order_by(PriceSeries.country_code.nullslast(), PriceSeries.id)).all()
    fx = FxBook(db)
    stale_cfg = get_setting(db, "price_tracking").get("stale_after_days") or {}
    now = datetime.now(timezone.utc)
    items = []
    for s in series:
        pts = db.scalars(select(PricePoint).where(PricePoint.series_id == s.id)
                         .order_by(PricePoint.observed_at.desc()).limit(max(spark_points, 2))).all()
        latest = pts[0] if pts else None
        row = series_out(s)
        row.update({"latest": None, "previous": None, "change_pct": None, "change_1w_pct": None,
                    "change_1m_pct": None, "change_1y_pct": None, "normalized": None, "normalized_unit": None,
                    "is_stale": None, "age_days": None, "spark": [], "points": 0})
        if latest:
            lp = float(latest.price)

            def at_or_before(days: int) -> float | None:
                v = db.scalar(select(PricePoint.price).where(
                    PricePoint.series_id == s.id, PricePoint.observed_at <= latest.observed_at - timedelta(days=days))
                    .order_by(PricePoint.observed_at.desc()).limit(1))
                return float(v) if v is not None else None

            prev = float(pts[1].price) if len(pts) > 1 else None
            tu = _target_unit(s, unit)
            norm = convert(lp, s.currency, s.unit, currency, tu, fx, latest.observed_at.date())
            age = (now - latest.observed_at).total_seconds() / 86400
            row.update({
                "latest": point_out(latest), "previous": prev, "change_pct": _pct(lp, prev),
                "change_1w_pct": _pct(lp, at_or_before(7)), "change_1m_pct": _pct(lp, at_or_before(28)),
                "change_1y_pct": _pct(lp, at_or_before(365)),
                "normalized": round(norm, 4) if norm is not None else None,
                "normalized_unit": f"{currency}/{tu}" if norm is not None else None,
                "age_days": round(age, 1), "is_stale": age > float(stale_cfg.get(s.frequency, 30)),
                "spark": [{"t": p.observed_at, "v": float(p.price)} for p in reversed(pts)],
                "points": db.scalar(select(func.count()).where(PricePoint.series_id == s.id)),
            })
        items.append(row)
    last = db.scalar(select(func.max(PricePoint.collected_at)))
    return {"currency": currency, "unit": unit, "generated_at": now, "last_collected_at": last, "items": items,
            "fx": fx.latest()}


def history(db: Session, series: PriceSeries, date_from: date | None = None, date_to: date | None = None,
            currency: str | None = None, unit: str | None = None, limit: int = 5000) -> dict:
    q = select(PricePoint).where(PricePoint.series_id == series.id)
    if date_from:
        q = q.where(PricePoint.observed_at >= as_datetime(date_from))
    if date_to:
        q = q.where(PricePoint.observed_at < as_datetime(date_to + timedelta(days=1)))
    pts = db.scalars(q.order_by(PricePoint.observed_at.desc()).limit(min(limit, 20000))).all()[::-1]
    fx = FxBook(db) if currency else None
    tu = _target_unit(series, unit or series.unit)
    out = []
    for p in pts:
        d = point_out(p)
        if fx:
            n = convert(float(p.price), series.currency, series.unit, currency, tu, fx, p.observed_at.date())
            d["normalized"] = round(n, 4) if n is not None else None
        out.append(d)
    return {"series": series_out(series), "normalized_unit": f"{currency}/{tu}" if currency else None, "points": out}


def compare(db: Session, material: str, currency: str = "USD", unit: str = "t", date_from: date | None = None,
            series_ids: list[int] | None = None) -> dict:
    """All priced (non-index) series of one material, normalised to one currency/unit for a cross-market chart."""
    q = (select(PriceSeries).options(selectinload(PriceSeries.material), selectinload(PriceSeries.source))
         .join(Material, PriceSeries.material_id == Material.id)
         .where(Material.code == material, PriceSeries.unit.in_(MASS_UNITS), PriceSeries.is_active))
    if series_ids:
        q = q.where(PriceSeries.id.in_(series_ids))
    start = date_from or (date.today() - timedelta(days=365))
    fx = FxBook(db)
    lines, skipped = [], []
    for s in db.scalars(q.order_by(PriceSeries.country_code, PriceSeries.id)).all():
        pts = db.scalars(select(PricePoint).where(PricePoint.series_id == s.id,
                                                  PricePoint.observed_at >= as_datetime(start))
                         .order_by(PricePoint.observed_at)).all()
        if not pts:
            continue
        data = []
        for p in pts:
            v = convert(float(p.price), s.currency, s.unit, currency, unit, fx, p.observed_at.date())
            if v is not None:
                data.append({"t": p.observed_at, "v": round(v, 4)})
        if data:
            lines.append({**series_out(s), "data": data})
        else:
            skipped.append({"key": s.key, "reason": f"no FX rate for {s.currency}"})
    return {"material": material, "currency": currency, "unit": unit, "from": start, "series": lines,
            "skipped": skipped}
