from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.serializers import shipment_out
from app.auth import current_user
from app.db import get_db
from app.models import Material, Shipment, TradeStatistic, User
from app.services.search import visible

router = APIRouter(tags=["trade"])


def _ship_query(importer, exporter, country, material, hs_code, date_from, date_to, min_qty, max_qty, q):
    qry = visible(select(Shipment), Shipment)
    if importer:
        qry = qry.where(func.lower(Shipment.importer_name_raw).like(f"%{importer.lower()}%"))
    if exporter:
        qry = qry.where(func.lower(Shipment.exporter_name_raw).like(f"%{exporter.lower()}%"))
    if country:
        qry = qry.where(or_(Shipment.importer_country.in_(country), Shipment.exporter_country.in_(country),
                            Shipment.origin_country.in_(country), Shipment.destination_country.in_(country)))
    if material:
        qry = qry.where(Shipment.material_id.in_(select(Material.id).where(Material.code.in_(material))))
    if hs_code:
        qry = qry.where(Shipment.hs_code.like(f"{hs_code.replace('.', '')}%"))
    if date_from:
        qry = qry.where(Shipment.shipment_date >= date_from)
    if date_to:
        qry = qry.where(Shipment.shipment_date <= date_to)
    qty = func.coalesce(Shipment.weight_kg, Shipment.quantity)
    if min_qty is not None:
        qry = qry.where(qty >= min_qty)
    if max_qty is not None:
        qry = qry.where(qty <= max_qty)
    if q:
        qry = qry.where(func.lower(Shipment.product_description).like(f"%{q.lower()}%"))
    return qry


@router.get("/shipments")
def list_shipments(importer: str | None = None, exporter: str | None = None, country: list[str] = Query(default=[]),
                   material: list[str] = Query(default=[]), hs_code: str | None = None, date_from: date | None = None,
                   date_to: date | None = None, min_qty: float | None = None, max_qty: float | None = None,
                   q: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    qry = _ship_query(importer, exporter, country, material, hs_code, date_from, date_to, min_qty, max_qty, q)
    total = db.scalar(select(func.count()).select_from(qry.subquery()))
    rows = db.scalars(qry.options(selectinload(Shipment.material), selectinload(Shipment.source))
                      .order_by(Shipment.shipment_date.desc().nullslast(), Shipment.id.desc())
                      .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 200))).all()
    return {"total": total, "items": [shipment_out(s) for s in rows]}


@router.get("/shipments/relationships")
def supplier_buyer_pairs(country: list[str] = Query(default=[]), material: list[str] = Query(default=[]),
                         limit: int = 50, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Supplier -> buyer relationships aggregated from shipment records."""
    base = _ship_query(None, None, country, material, None, None, None, None, None, None).subquery()
    rows = db.execute(select(base.c.exporter_name_raw, base.c.exporter_company_id, base.c.exporter_country,
                             base.c.importer_name_raw, base.c.importer_company_id, base.c.importer_country,
                             func.count().label("shipments"), func.min(base.c.shipment_date).label("first"),
                             func.max(base.c.shipment_date).label("last"),
                             func.sum(func.coalesce(base.c.weight_kg, 0)).label("weight_kg"))
                      .where(base.c.exporter_name_raw.is_not(None), base.c.importer_name_raw.is_not(None))
                      .group_by(base.c.exporter_name_raw, base.c.exporter_company_id, base.c.exporter_country,
                                base.c.importer_name_raw, base.c.importer_company_id, base.c.importer_country)
                      .order_by(func.count().desc()).limit(limit)).mappings().all()
    return [{**{k: (str(v) if k.endswith("_id") and v else v) for k, v in r.items()},
             "weight_kg": float(r["weight_kg"] or 0)} for r in rows]


@router.get("/trade-stats")
def trade_stats(reporter: list[str] = Query(default=[]), hs_code: list[str] = Query(default=[]), flow: str | None = None,
                partner: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    qry = select(TradeStatistic)
    if reporter:
        qry = qry.where(TradeStatistic.reporter_country.in_(reporter))
    if hs_code:
        qry = qry.where(TradeStatistic.hs_code.in_(hs_code))
    if flow:
        qry = qry.where(TradeStatistic.flow == flow)
    if partner:
        qry = qry.where(TradeStatistic.partner_country == partner)
    rows = db.scalars(qry.order_by(TradeStatistic.period.desc(), TradeStatistic.value_usd.desc().nullslast()).limit(500)).all()
    return [{"reporter": r.reporter_country, "partner": r.partner_country, "partner_name": r.partner_name, "flow": r.flow,
             "hs_code": r.hs_code, "hs_description": r.hs_description, "period": r.period,
             "value_usd": float(r.value_usd) if r.value_usd is not None else None,
             "net_weight_kg": float(r.net_weight_kg) if r.net_weight_kg is not None else None,
             "quantity": float(r.quantity) if r.quantity is not None else None, "quantity_unit": r.quantity_unit,
             "source_url": r.source_url} for r in rows]
