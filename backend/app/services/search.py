"""Company discovery search: combined filters over companies, materials, contacts, shipments and sources.

Material filters (polymer + grade + application + relationship) are applied to the SAME company_materials row, so
"virgin LLDPE film grade seller" means one row that is all of those - not four unrelated facts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import (Company, CompanyClassification, CompanyMaterial, CompanySourceRecord, Contact, Material,
                        Shipment, Source)

REL_EXPAND = {
    "buyer": ["buyer", "both", "historical_buyer"],
    "seller": ["seller", "both", "manufacturer", "historical_seller"],
    "both": ["both"],
    "manufacturer": ["manufacturer"],
    "historical_buyer": ["historical_buyer"],
    "historical_seller": ["historical_seller"],
    "unknown": ["unknown"],
}
GRADE_EXPAND = {"recycled": ["recycled", "pcr", "pir", "reprocessed"]}
VERIFIED = ["email_verified", "manually_verified"]


class CompanyFilters(BaseModel):
    q: str | None = None
    countries: list[str] = Field(default_factory=list)
    city: str | None = None
    polymers: list[str] = Field(default_factory=list)
    polymer_match: Literal["any", "all"] = "any"
    grades: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    trade_roles: list[Literal["importer", "exporter"]] = Field(default_factory=list)
    has_contacts: bool | None = None
    has_email: bool | None = None
    has_phone: bool | None = None
    has_website: bool | None = None
    has_decision_maker: bool | None = None
    contact_title: str | None = None
    contact_verification: list[str] = Field(default_factory=list)
    min_score: int | None = None
    max_score: int | None = None
    tiers: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    exclude_rejected: bool = True
    sort: Literal["score", "name", "discovered", "verified", "country"] = "score"
    order: Literal["asc", "desc"] = "desc"
    page: int = 1
    page_size: int = 25


def visible(q, model=Company, active_only: bool = True):
    """Demo records are only visible when APP_ENV=demo; merged/opted-out companies are hidden."""
    if active_only and model is Company:
        q = q.where(Company.status == "active")
    if not get_settings().show_demo_data:
        q = q.where(model.is_demo.is_(False))
    return q


def _material_clause(f: CompanyFilters, polymer_ids: list[int] | None):
    conds = [CompanyMaterial.company_id == Company.id, CompanyMaterial.is_current.is_(True)]
    if f.exclude_rejected:
        conds.append(CompanyMaterial.review_status != "rejected")
    if polymer_ids:
        conds.append(CompanyMaterial.material_id.in_(polymer_ids))
    if f.grades:
        conds.append(CompanyMaterial.grade_category.in_(sorted({x for g in f.grades for x in GRADE_EXPAND.get(g, [g])})))
    if f.applications:
        conds.append(CompanyMaterial.application.in_(f.applications))
    if f.relationships:
        conds.append(CompanyMaterial.relationship_type.in_(sorted({x for r in f.relationships for x in REL_EXPAND.get(r, [r])})))
    return exists().where(and_(*conds))


def build_query(db: Session, f: CompanyFilters):
    q = visible(select(Company))
    if f.q:
        like = f"%{f.q.strip().lower()}%"
        q = q.where(or_(func.lower(Company.name).like(like), Company.normalized_name.like(like),
                        func.lower(Company.description).like(like), func.lower(Company.domain).like(like),
                        Company.public_ref == f.q.strip().upper()))
    if f.countries:
        q = q.where(Company.country_code.in_([c.upper() for c in f.countries]))
    if f.city:
        q = q.where(func.lower(Company.city).like(f"%{f.city.lower()}%"))

    mat_filters = f.polymers or f.grades or f.applications or f.relationships
    if mat_filters:
        ids = {m.code: m.id for m in db.scalars(select(Material)).all()}
        poly_ids = [ids[p] for p in f.polymers if p in ids]
        if f.polymers and not poly_ids:
            return q.where(False)
        if f.polymer_match == "all" and len(poly_ids) > 1:
            for pid in poly_ids:
                q = q.where(_material_clause(f, [pid]))
        else:
            q = q.where(_material_clause(f, poly_ids or None))
    for t in f.company_types:
        cats = ["manufacturer", "producer"] if t in ("manufacturer", "producer") else [t]
        q = q.where(exists().where(CompanyClassification.company_id == Company.id, CompanyClassification.category.in_(cats),
                                   CompanyClassification.review_status != "rejected"))
    for role in f.trade_roles:
        col = Shipment.importer_company_id if role == "importer" else Shipment.exporter_company_id
        q = q.where(or_(exists().where(col == Company.id),
                        exists().where(CompanyClassification.company_id == Company.id, CompanyClassification.category == role)))

    contact_ok = and_(Contact.company_id == Company.id, Contact.is_opted_out.is_(False),
                      Contact.verification_status != "invalid")
    if f.has_contacts is not None:
        e = exists().where(contact_ok)
        q = q.where(e if f.has_contacts else ~e)
    if f.has_email is not None:
        e = or_(Company.email.is_not(None), exists().where(contact_ok, Contact.email.is_not(None)))
        q = q.where(e if f.has_email else ~e)
    if f.has_phone is not None:
        e = or_(Company.phone.is_not(None), exists().where(contact_ok, Contact.phone.is_not(None)))
        q = q.where(e if f.has_phone else ~e)
    if f.has_website is not None:
        q = q.where(Company.website.is_not(None) if f.has_website else Company.website.is_(None))
    if f.has_decision_maker:
        q = q.where(exists().where(contact_ok, Contact.contact_type == "individual",
                                   Contact.decision_role.in_(["likely_decision_maker", "confirmed_decision_maker"])))
    if f.contact_title:
        q = q.where(exists().where(contact_ok, func.lower(Contact.job_title).like(f"%{f.contact_title.lower()}%")))
    if f.contact_verification:
        q = q.where(exists().where(contact_ok, Contact.verification_status.in_(f.contact_verification)))
    if f.min_score is not None:
        q = q.where(Company.lead_score >= f.min_score)
    if f.max_score is not None:
        q = q.where(Company.lead_score <= f.max_score)
    if f.tiers:
        q = q.where(Company.lead_tier.in_(f.tiers))
    if f.sources:
        q = q.where(exists().where(CompanySourceRecord.company_id == Company.id,
                                   CompanySourceRecord.source_id == Source.id, Source.key.in_(f.sources)))
    return q


SORT_COLS = {"score": Company.lead_score, "name": Company.name, "discovered": Company.first_discovered_at,
             "verified": Company.last_verified_at, "country": Company.country_code}


def search_companies(db: Session, f: CompanyFilters, load_details: bool = True):
    q = build_query(db, f)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    col = SORT_COLS[f.sort]
    q = q.order_by(col.desc().nullslast() if f.order == "desc" else col.asc().nullslast(), Company.name)
    size = max(1, min(f.page_size, 500))
    q = q.offset((max(f.page, 1) - 1) * size).limit(size)
    if load_details:
        q = q.options(selectinload(Company.materials).selectinload(CompanyMaterial.material),
                      selectinload(Company.classifications), selectinload(Company.contacts))
    return total, db.scalars(q).all()
