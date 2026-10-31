"""Explainable lead scoring (0-100). This is a prioritisation score, NOT a probability of conversion.

Each component yields a fraction in [0,1] multiplied by its configurable weight; reasons explain every point.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, CompanyMaterial, Material, Shipment
from app.services.settings_store import get_setting


def tier_for(score: int, tiers: list[dict]) -> str:
    for t in sorted(tiers, key=lambda t: -t["min"]):
        if score >= t["min"]:
            return t["label"]
    return tiers[-1]["label"] if tiers else ""


def _material_relevance(materials: list[CompanyMaterial], cfg: dict) -> tuple[float, list[str]]:
    target_polys = set(cfg["target_polymers"])
    target_grades = set(cfg["target_grade_categories"])
    target_apps = set(cfg["target_applications"])
    rel = [m for m in materials if m.material and m.material.code in target_polys and m.review_status != "rejected"]
    if not rel:
        return 0.0, ["No target polymer (LDPE/LLDPE/HDPE) identified"]
    polys = sorted({m.material.code for m in rel})
    frac, reasons = 0.5, [f"Deals in target polymer(s): {', '.join(polys)}"]
    grades = sorted({m.grade_category for m in rel if m.grade_category in target_grades})
    if grades:
        frac += 0.2
        reasons.append(f"Target grade categories: {', '.join(grades)}")
    apps = sorted({m.application for m in rel if m.application in target_apps})
    if apps:
        frac += 0.15
        reasons.append(f"Target applications: {', '.join(apps)}")
    if len(polys) >= 2:
        frac += 0.1
        reasons.append("Multiple target polymers")
    if any(m.specifications for m in rel):
        frac += 0.05
        reasons.append("Technical specifications published")
    return min(frac, 1.0), reasons


def _activity(materials: list[CompanyMaterial], shipment_count: int) -> tuple[float, list[str]]:
    rels = [m for m in materials if m.relationship_type != "unknown" and m.review_status != "rejected"]
    if any(m.review_status == "confirmed" for m in rels):
        return 1.0, ["Buying/selling activity manually confirmed"]
    if shipment_count:
        return 1.0, [f"Buying/selling evidenced by {shipment_count} shipment record(s)"]
    if any(m.method == "trade_data" for m in rels):
        return 0.9, ["Activity from trade database records"]
    if rels:
        kinds = sorted({m.relationship_type for m in rels})
        frac = 0.6 if any(m.review_status == "auto" for m in rels) else 0.4
        return frac, [f"Stated on source pages: {', '.join(kinds)} (not yet manually confirmed)"]
    return 0.0, ["Buying/selling activity unknown - requires verification"]


def _international(company: Company, shipment_count: int, recent_shipments: int, types: set[str]) -> tuple[float, list[str]]:
    reasons, frac = [], 0.0
    if recent_shipments >= 10:
        frac = 0.9
    elif recent_shipments >= 3:
        frac = 0.7
    elif recent_shipments >= 1:
        frac = 0.45
    elif shipment_count:
        frac = 0.3
    if shipment_count:
        reasons.append(f"{shipment_count} shipment(s) on record, {recent_shipments} in last 24 months")
    if types & {"importer", "exporter"}:
        frac = min(1.0, frac + 0.3)
        reasons.append(f"Declares {' & '.join(sorted(types & {'importer', 'exporter'}))} activity")
    if not reasons:
        reasons.append("No international trade activity on record")
    return frac, reasons


def _contacts(company: Company, title_kws: list[str]) -> tuple[float, list[str]]:
    contacts = [c for c in company.contacts if not c.is_opted_out and c.verification_status not in ("invalid",)]
    frac, have = 0.0, []
    if company.website:
        frac += 0.2; have.append("website")
    if company.email or any(c.email and c.contact_type == "general" for c in contacts):
        frac += 0.2; have.append("company email")
    if company.phone or any(c.phone for c in contacts):
        frac += 0.2; have.append("phone")
    people = [c for c in contacts if c.contact_type == "individual"]
    if any(c.job_title and any(k in c.job_title.lower() for k in title_kws) for c in people):
        frac += 0.3; have.append("relevant decision-maker contact")
    elif people:
        frac += 0.15; have.append("individual contact (role unconfirmed)")
    if company.linkedin_url:
        frac += 0.1; have.append("LinkedIn")
    if any(c.verification_status in ("email_verified", "manually_verified") for c in contacts):
        have.append("verified contact")
    return min(frac, 1.0), [("Has " + ", ".join(have)) if have else "No contact information"]


def _recency(company: Company) -> tuple[float, list[str]]:
    ref = max([d for d in (company.last_verified_at, company.last_seen_at, company.first_discovered_at) if d], default=None)
    if not ref:
        return 0.0, ["No collection date"]
    days = (datetime.now(timezone.utc) - ref).days
    frac = 1.0 if days <= 30 else 0.7 if days <= 90 else 0.4 if days <= 180 else 0.2 if days <= 365 else 0.0
    return frac, [f"Data last refreshed {days} day(s) ago"]


def score_company(db: Session, company: Company, cfg: dict | None = None) -> dict:
    cfg = cfg or get_setting(db, "lead_scoring")
    w = cfg["weights"]
    materials = [m for m in company.materials if m.is_current]
    ship_q = select(func.count()).select_from(Shipment).where(
        or_(Shipment.importer_company_id == company.id, Shipment.exporter_company_id == company.id))
    shipment_count = db.scalar(ship_q) or 0
    recent = db.scalar(ship_q.where(Shipment.shipment_date >= date.today() - timedelta(days=730))) or 0 if shipment_count else 0
    types = {c.category for c in company.classifications if c.review_status != "rejected"}

    parts = {
        "material_relevance": _material_relevance(materials, cfg),
        "trading_activity": _activity(materials, shipment_count),
        "international_trade": _international(company, shipment_count, recent, types),
        "contact_completeness": _contacts(company, cfg.get("decision_maker_titles", [])),
        "data_recency": _recency(company),
    }
    total_weight = sum(w.values()) or 100
    breakdown, total = {}, 0.0
    for key, (frac, reasons) in parts.items():
        pts = frac * w.get(key, 0) * 100 / total_weight
        total += pts
        breakdown[key] = {"points": round(pts, 1), "max": round(w.get(key, 0) * 100 / total_weight, 1), "reasons": reasons}
    score = int(round(total))
    tier = tier_for(score, cfg["tiers"])
    company.lead_score = score
    company.lead_tier = tier
    company.lead_score_breakdown = {"components": breakdown, "tier": tier,
                                    "note": "Prioritisation score based on available evidence - not a conversion probability."}
    company.lead_score_updated_at = datetime.now(timezone.utc)
    return company.lead_score_breakdown


def rescore_all(db: Session, batch: int = 200) -> int:
    cfg = get_setting(db, "lead_scoring")
    n, last_id = 0, None
    while True:
        q = select(Company).where(Company.status == "active").order_by(Company.id).limit(batch).options(
            selectinload(Company.materials).selectinload(CompanyMaterial.material),
            selectinload(Company.materials).selectinload(CompanyMaterial.specifications),
            selectinload(Company.contacts), selectinload(Company.classifications))
        if last_id:
            q = q.where(Company.id > last_id)
        rows = db.scalars(q).all()
        if not rows:
            break
        for c in rows:
            score_company(db, c, cfg)
            n += 1
        last_id = rows[-1].id
        db.commit()
    return n
