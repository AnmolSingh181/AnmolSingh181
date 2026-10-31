"""Dashboard aggregates and acceptance-criteria evaluation - always computed from live database rows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, distinct, exists, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (ClassificationReview, Company, CompanyClassification, CompanyMaterial, CompanySourceRecord,
                        Contact, DuplicateCandidate, Material, RawRecord, ScrapeJob, Shipment, Source)

TARGETS = {
    "relevant_companies_min": 1000,
    "pct_with_website": 60,
    "pct_with_email": 40,
    "pct_with_phone": 40,
    "classification_accuracy": 80,
    "duplicate_rate_max": 5,
    "source_traceability": 100,
}


def _demo_filter(model):
    return True if get_settings().show_demo_data else model.is_demo.is_(False)


def _active():
    return and_(Company.status == "active", _demo_filter(Company))


def _count(db, q):
    return db.scalar(q) or 0


def dashboard(db: Session) -> dict:
    act = _active()
    total = _count(db, select(func.count()).select_from(Company).where(act))

    def by_rel(rels):
        return _count(db, select(func.count(distinct(CompanyMaterial.company_id))).join(Company).where(
            act, CompanyMaterial.is_current, CompanyMaterial.review_status != "rejected",
            CompanyMaterial.relationship_type.in_(rels)))

    def by_type(cats):
        return _count(db, select(func.count(distinct(CompanyClassification.company_id))).join(Company).where(
            act, CompanyClassification.category.in_(cats), CompanyClassification.review_status != "rejected"))

    contact_status = dict(db.execute(select(Contact.verification_status, func.count()).join(Company).where(
        act, Contact.is_opted_out.is_(False)).group_by(Contact.verification_status)).all())
    by_country = [{"country": c or "Unknown", "count": n} for c, n in db.execute(
        select(Company.country_code, func.count()).where(act).group_by(Company.country_code)
        .order_by(func.count().desc())).all()]
    by_material = [{"material": code, "companies": n} for code, n in db.execute(
        select(Material.code, func.count(distinct(CompanyMaterial.company_id))).join(CompanyMaterial)
        .join(Company, Company.id == CompanyMaterial.company_id)
        .where(act, CompanyMaterial.is_current, CompanyMaterial.review_status != "rejected")
        .group_by(Material.code).order_by(func.count(distinct(CompanyMaterial.company_id)).desc())).all()]
    by_grade = [{"grade": g, "companies": n} for g, n in db.execute(
        select(CompanyMaterial.grade_category, func.count(distinct(CompanyMaterial.company_id))).join(Company)
        .where(act, CompanyMaterial.is_current, CompanyMaterial.review_status != "rejected")
        .group_by(CompanyMaterial.grade_category).order_by(func.count(distinct(CompanyMaterial.company_id)).desc())).all()]
    recent = db.execute(select(Company.id, Company.name, Company.country_code, Company.lead_score, Company.lead_tier,
                               Company.first_discovered_at).where(act)
                        .order_by(Company.first_discovered_at.desc()).limit(8)).mappings().all()
    top = db.execute(select(Company.id, Company.name, Company.country_code, Company.lead_score, Company.lead_tier)
                     .where(act, Company.lead_score >= 80).order_by(Company.lead_score.desc()).limit(8)).mappings().all()
    ship_q = select(Shipment).where(_demo_filter(Shipment)).order_by(Shipment.shipment_date.desc().nullslast()).limit(8)
    ships = [{"id": s.id, "date": s.shipment_date, "importer": s.importer_name_raw, "exporter": s.exporter_name_raw,
              "hs_code": s.hs_code, "material": s.material.code if s.material else None,
              "importer_country": s.importer_country, "exporter_country": s.exporter_country,
              "importer_company_id": s.importer_company_id, "exporter_company_id": s.exporter_company_id}
             for s in db.scalars(ship_q).all()]
    since = datetime.now(timezone.utc) - timedelta(days=7)
    jobs = dict(db.execute(select(ScrapeJob.status, func.count()).where(ScrapeJob.created_at >= since)
                           .group_by(ScrapeJob.status)).all())
    src_status = dict(db.execute(select(Source.status, func.count()).group_by(Source.status)).all())
    last_success = db.scalar(select(func.max(Source.last_success_at)))
    return {
        "totals": {
            "companies": total,
            "buyers": by_rel(["buyer", "both", "historical_buyer"]),
            "sellers": by_rel(["seller", "both", "manufacturer", "historical_seller"]),
            "manufacturers": by_type(["manufacturer", "producer"]),
            "traders": by_type(["trader", "distributor"]),
            "recyclers": by_type(["recycler", "processor"]),
            "importers": by_type(["importer"]),
            "exporters": by_type(["exporter"]),
            "contacts": sum(contact_status.values()),
            "verified_contacts": sum(v for k, v in contact_status.items() if k in ("email_verified", "manually_verified")),
            "high_priority": _count(db, select(func.count()).select_from(Company).where(act, Company.lead_score >= 80)),
            "shipments": _count(db, select(func.count()).select_from(Shipment).where(_demo_filter(Shipment))),
        },
        "contact_verification": contact_status,
        "by_country": by_country,
        "by_material": by_material,
        "by_grade": by_grade,
        "recent_companies": [dict(r) for r in recent],
        "high_priority_leads": [dict(r) for r in top],
        "recent_shipments": ships,
        "collection": {"jobs_last_7_days": jobs, "sources_by_status": src_status, "last_successful_collection": last_success,
                       "queued": _count(db, select(func.count()).select_from(ScrapeJob).where(ScrapeJob.status == "queued")),
                       "running": _count(db, select(func.count()).select_from(ScrapeJob).where(ScrapeJob.status == "running"))},
        "demo_mode": get_settings().show_demo_data,
    }


def data_quality(db: Session) -> dict:
    act = _active()
    total = _count(db, select(func.count()).select_from(Company).where(act))
    target_ids = select(Material.id).where(Material.is_target)
    relevant_q = select(Company.id).where(act, exists().where(
        CompanyMaterial.company_id == Company.id, CompanyMaterial.is_current, CompanyMaterial.review_status != "rejected",
        CompanyMaterial.material_id.in_(target_ids)))
    relevant = _count(db, select(func.count()).select_from(relevant_q.subquery()))
    contact_ok = and_(Contact.company_id == Company.id, Contact.is_opted_out.is_(False), Contact.verification_status != "invalid")
    with_web = _count(db, select(func.count()).select_from(Company).where(act, Company.website.is_not(None)))
    with_email = _count(db, select(func.count()).select_from(Company).where(act, or_(
        Company.email.is_not(None), exists().where(contact_ok, Contact.email.is_not(None)))))
    with_phone = _count(db, select(func.count()).select_from(Company).where(act, or_(
        Company.phone.is_not(None), exists().where(contact_ok, Contact.phone.is_not(None)))))
    traced = _count(db, select(func.count()).select_from(Company).where(act, exists().where(
        CompanySourceRecord.company_id == Company.id)))
    pending_dups = _count(db, select(func.count()).select_from(DuplicateCandidate).where(DuplicateCandidate.status == "pending"))
    merged = _count(db, select(func.count()).select_from(Company).where(Company.status == "merged"))
    n_rev = _count(db, select(func.count()).select_from(ClassificationReview))
    n_ok = _count(db, select(func.count()).select_from(ClassificationReview).where(
        ClassificationReview.polymer_correct.is_(True),
        or_(ClassificationReview.grade_correct.is_(None), ClassificationReview.grade_correct.is_(True)),
        or_(ClassificationReview.relationship_correct.is_(None), ClassificationReview.relationship_correct.is_(True))))
    awaiting_review = _count(db, select(func.count()).select_from(CompanyMaterial).join(Company).where(
        act, CompanyMaterial.is_current, CompanyMaterial.review_status == "needs_review"))
    raw_pending = _count(db, select(func.count()).select_from(RawRecord).where(RawRecord.processing_status == "pending"))
    raw_failed = _count(db, select(func.count()).select_from(RawRecord).where(RawRecord.processing_status == "failed"))

    def pct(n, d):
        return round(100 * n / d, 1) if d else None

    acc = pct(n_ok, n_rev)
    dup_rate = pct(pending_dups, total)
    m = {
        "total_companies": total,
        "relevant_companies": relevant,
        "pct_with_website": pct(with_web, total),
        "pct_with_email": pct(with_email, total),
        "pct_with_phone": pct(with_phone, total),
        "source_traceability": pct(traced, total),
        "pending_duplicate_candidates": pending_dups,
        "duplicate_rate": dup_rate,
        "merged_records": merged,
        "classification_reviews": n_rev,
        "classification_accuracy": acc,
        "materials_awaiting_review": awaiting_review,
        "raw_records_pending": raw_pending,
        "raw_records_failed": raw_failed,
    }
    checks = [
        ("Relevant company profiles", relevant, f">= {TARGETS['relevant_companies_min']}", relevant >= TARGETS["relevant_companies_min"]),
        ("Companies with website (%)", m["pct_with_website"], ">= 60", (m["pct_with_website"] or 0) >= 60),
        ("Companies with business email (%)", m["pct_with_email"], ">= 40", (m["pct_with_email"] or 0) >= 40),
        ("Companies with phone (%)", m["pct_with_phone"], ">= 40", (m["pct_with_phone"] or 0) >= 40),
        ("Classification accuracy on reviewed sample (%)", acc, ">= 80 (needs >= 50 reviews)",
         acc is not None and acc >= 80 and n_rev >= 50),
        ("Pending duplicate rate (%)", dup_rate, "< 5", dup_rate is not None and dup_rate < 5),
        ("Source traceability (%)", m["source_traceability"], "= 100", m["source_traceability"] == 100),
    ]
    m["acceptance"] = [{"metric": a, "value": v, "target": t, "met": bool(ok)} for a, v, t, ok in checks]
    return m
