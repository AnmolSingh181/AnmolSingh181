import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import enums as E
from app.api.serializers import company_detail, company_summary, material_out, shipment_out
from app.auth import current_user, log_activity, require_editor
from app.db import get_db
from app.models import (ClassificationReview, Company, CompanyClassification, CompanyMaterial, CompanyNote,
                        CompanySourceRecord, Lead, Material, Shipment, Source, User)
from app.services.ingestion import CompanyInput, ContactInput, MaterialInput, ingest_company
from app.services.scoring import score_company
from app.services.search import CompanyFilters, search_companies, visible

router = APIRouter(tags=["companies"])


def filters_from_query(
    q: str | None = None, country: list[str] = Query(default=[]), city: str | None = None,
    polymer: list[str] = Query(default=[]), polymer_match: str = "any", grade: list[str] = Query(default=[]),
    application: list[str] = Query(default=[]), relationship: list[str] = Query(default=[]),
    company_type: list[str] = Query(default=[]), trade_role: list[str] = Query(default=[]),
    has_contacts: bool | None = None, has_email: bool | None = None, has_phone: bool | None = None,
    has_website: bool | None = None, has_decision_maker: bool | None = None, contact_title: str | None = None,
    contact_verification: list[str] = Query(default=[]), min_score: int | None = None, max_score: int | None = None,
    tier: list[str] = Query(default=[]), source: list[str] = Query(default=[]), sort: str = "score", order: str = "desc",
    page: int = 1, page_size: int = 25,
) -> CompanyFilters:
    try:
        return CompanyFilters(q=q, countries=country, city=city, polymers=polymer, polymer_match=polymer_match,
                              grades=grade, applications=application, relationships=relationship,
                              company_types=company_type, trade_roles=trade_role, has_contacts=has_contacts,
                              has_email=has_email, has_phone=has_phone, has_website=has_website,
                              has_decision_maker=has_decision_maker, contact_title=contact_title,
                              contact_verification=contact_verification, min_score=min_score, max_score=max_score,
                              tiers=tier, sources=source, sort=sort, order=order, page=page, page_size=page_size)
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/companies")
def list_companies(f: CompanyFilters = Depends(filters_from_query), db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    total, rows = search_companies(db, f)
    return {"total": total, "page": f.page, "page_size": f.page_size, "items": [company_summary(c) for c in rows]}


@router.post("/companies/search")
def search_body(f: CompanyFilters, db: Session = Depends(get_db), user: User = Depends(current_user)):
    total, rows = search_companies(db, f)
    return {"total": total, "page": f.page, "page_size": f.page_size, "items": [company_summary(c) for c in rows]}


EXPORT_COLS = ["public_ref", "name", "country_code", "city", "website", "email", "phone", "company_types", "polymers",
               "grades", "applications", "relationships", "lead_score", "lead_tier", "contact_count", "last_seen_at"]


@router.get("/companies/export.csv")
def export_companies(f: CompanyFilters = Depends(filters_from_query), db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    f.page, f.page_size = 1, 500
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLS + ["profile_url"])
    total, _ = search_companies(db, f, load_details=False)
    pages = (total + 499) // 500
    for p in range(1, min(pages, 40) + 1):
        f.page = p
        _, rows = search_companies(db, f)
        for c in rows:
            s = company_summary(c)
            w.writerow([";".join(s[k]) if isinstance(s[k], list) else s[k] for k in EXPORT_COLS] + [f"/companies/{c.id}"])
    log_activity(db, user, "export_companies", details={"rows": total})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=companies.csv"})


def _load(db: Session, cid: uuid.UUID) -> Company:
    c = db.scalar(visible(select(Company), active_only=False).where(Company.id == cid).options(
        selectinload(Company.materials).selectinload(CompanyMaterial.material),
        selectinload(Company.materials).selectinload(CompanyMaterial.specifications),
        selectinload(Company.classifications), selectinload(Company.contacts), selectinload(Company.aliases),
        selectinload(Company.locations), selectinload(Company.notes),
        selectinload(Company.source_records).selectinload(CompanySourceRecord.source)))
    if not c:
        raise HTTPException(404, "Company not found")
    return c


@router.get("/companies/{cid}")
def get_company(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _load(db, cid)
    if c.status == "merged" and c.merged_into_id:
        return {"redirect_to": str(c.merged_into_id), "status": "merged"}
    d = company_detail(c)
    ships = db.scalars(select(Shipment).where(or_(Shipment.importer_company_id == cid, Shipment.exporter_company_id == cid))
                       .order_by(Shipment.shipment_date.desc().nullslast()).limit(100)).all()
    d["shipments"] = [shipment_out(s) for s in ships]
    countries = {c.country_code} | {l.country_code for l in c.locations} | \
        {s.origin_country for s in ships} | {s.destination_country for s in ships}
    d["countries_of_operation"] = sorted(x for x in countries if x)
    lead = db.scalar(select(Lead).where(Lead.company_id == cid, Lead.owner_user_id == user.id))
    d["lead"] = {"id": str(lead.id), "stage": lead.stage, "priority": lead.priority, "lead_type": lead.lead_type} if lead else None
    from app.models import ContactVerification

    ids = [x.id for x in c.contacts]
    d["verification_history"] = [
        {"contact_id": str(v.contact_id), "check_type": v.check_type, "result": v.result, "status_after": v.status_after,
         "provider": v.provider, "checked_at": v.checked_at.isoformat(), "details": v.details}
        for v in db.scalars(select(ContactVerification).where(ContactVerification.contact_id.in_(ids))
                            .order_by(ContactVerification.checked_at.desc()).limit(100)).all()] if ids else []
    log_activity(db, user, "view_company", "company", str(cid))
    db.commit()
    return d


class ManualCompany(BaseModel):
    name: str
    country: str | None = None
    city: str | None = None
    address: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    description: str | None = None
    company_types: list[str] = []
    evidence: str | None = None


@router.post("/companies", status_code=201)
def create_company(body: ManualCompany, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    src = db.scalar(select(Source).where(Source.key == "manual"))
    contacts = [ContactInput(contact_type="general", email=body.email, phone=body.phone, evidence=f"Entered by {user.email}")] \
        if (body.email or body.phone) else []
    out = ingest_company(db, src, CompanyInput(
        name=body.name, country=body.country, city=body.city, address=body.address, website=body.website,
        email=body.email, phone=body.phone, linkedin_url=body.linkedin_url, description=body.description,
        company_types=body.company_types, company_type_evidence=body.evidence or f"Entered manually by {user.email}",
        classification_text=body.description, contacts=contacts), use_ai=False, explicit_method="manual")
    log_activity(db, user, "create_company", "company", out.company_id)
    db.commit()
    return out.model_dump()


class CompanyPatch(BaseModel):
    name: str | None = None
    country_code: str | None = None
    state: str | None = None
    city: str | None = None
    address: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    description: str | None = None
    registration_number: str | None = None
    registration_authority: str | None = None
    mark_verified: bool | None = None


@router.patch("/companies/{cid}")
def update_company(cid: uuid.UUID, body: CompanyPatch, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    from app.services.normalize import company_domain, normalize_company_name, normalize_phone, normalize_url

    c = _load(db, cid)
    changes = body.model_dump(exclude_unset=True)
    verified = changes.pop("mark_verified", None)
    for k, v in changes.items():
        setattr(c, k, v or None)
    if "name" in changes and c.name:
        c.normalized_name = normalize_company_name(c.name)
    if "website" in changes:
        c.website = normalize_url(c.website)
        c.domain = company_domain(c.website, c.email)
    if "phone" in changes:
        c.phone_normalized = normalize_phone(c.phone)
    if verified:
        c.last_verified_at = datetime.now(timezone.utc)
    score_company(db, c)
    log_activity(db, user, "update_company", "company", str(cid), changes)
    db.commit()
    return company_detail(_load(db, cid))


class NoteIn(BaseModel):
    body: str


@router.post("/companies/{cid}/notes", status_code=201)
def add_note(cid: uuid.UUID, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    _load(db, cid)
    n = CompanyNote(company_id=cid, user_id=user.id, body=body.body[:5000])
    db.add(n)
    db.commit()
    return {"id": n.id}


class MaterialIn(BaseModel):
    polymer: str
    grade_category: str = "unknown"
    application: str = "unknown"
    relationship: str = "unknown"
    form: str | None = None
    evidence: str
    mfi: float | None = None
    density: float | None = None
    grade_number: str | None = None
    brand: str | None = None
    colour: str | None = None
    available_quantity: float | None = None
    required_quantity: float | None = None


@router.post("/companies/{cid}/materials", status_code=201)
def add_material(cid: uuid.UUID, body: MaterialIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = _load(db, cid)
    for field, allowed in (("grade_category", E.GRADE_CATEGORIES), ("application", E.APPLICATIONS),
                           ("relationship", E.RELATIONSHIPS)):
        if getattr(body, field) not in allowed:
            raise HTTPException(422, f"invalid {field}")
    from app.models import MaterialSpecification
    from app.services.ingestion import material_ids

    mids = material_ids(db)
    if body.polymer not in mids:
        raise HTTPException(422, "unknown polymer")
    now = datetime.now(timezone.utc)
    row = db.scalar(select(CompanyMaterial).where(
        CompanyMaterial.company_id == cid, CompanyMaterial.material_id == mids[body.polymer], CompanyMaterial.is_current,
        CompanyMaterial.grade_category == body.grade_category, CompanyMaterial.application == body.application,
        CompanyMaterial.relationship_type == body.relationship))
    src = db.scalar(select(Source).where(Source.key == "manual"))
    if not row:
        row = CompanyMaterial(company_id=cid, material_id=mids[body.polymer], grade_category=body.grade_category,
                              application=body.application, relationship_type=body.relationship, form=body.form,
                              available_quantity=body.available_quantity, required_quantity=body.required_quantity,
                              quantity_unit="MT" if (body.available_quantity or body.required_quantity) else None,
                              method="manual", confidence=1.0, evidence_text=body.evidence, source_id=src.id)
        db.add(row)
        db.flush()
    row.review_status, row.reviewed_by, row.reviewed_at, row.last_seen_at = "confirmed", user.id, now, now
    if any(v is not None for v in (body.mfi, body.density, body.grade_number, body.brand, body.colour)):
        db.add(MaterialSpecification(company_material_id=row.id, mfi=body.mfi, density=body.density,
                                     grade_number=body.grade_number, brand=body.brand, colour=body.colour, form=body.form,
                                     evidence_text=body.evidence, method="manual"))
    db.flush()
    db.expire_all()
    score_company(db, _load(db, cid))
    log_activity(db, user, "add_material", "company", str(cid), body.model_dump())
    db.commit()
    return material_out(db.get(CompanyMaterial, row.id))


class ReviewIn(BaseModel):
    status: str  # confirmed | rejected | needs_review
    polymer_correct: bool | None = None
    grade_correct: bool | None = None
    relationship_correct: bool | None = None
    comment: str | None = None


@router.post("/company-materials/{mid}/review")
def review_material(mid: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    m = db.get(CompanyMaterial, mid)
    if not m:
        raise HTTPException(404)
    if body.status not in ("confirmed", "rejected", "needs_review"):
        raise HTTPException(422, "invalid status")
    m.review_status, m.reviewed_by, m.reviewed_at = body.status, user.id, datetime.now(timezone.utc)
    pc = body.polymer_correct if body.polymer_correct is not None else body.status == "confirmed"
    if body.status != "needs_review":
        db.add(ClassificationReview(company_material_id=mid, reviewer_id=user.id, polymer_correct=pc,
                                    grade_correct=body.grade_correct if body.grade_correct is not None else (body.status == "confirmed" or None),
                                    relationship_correct=body.relationship_correct if body.relationship_correct is not None else (body.status == "confirmed" or None),
                                    comment=body.comment))
    db.flush()
    score_company(db, _load(db, m.company_id))
    log_activity(db, user, "review_material", "company_material", str(mid), body.model_dump())
    db.commit()
    return {"ok": True, "review_status": m.review_status}


class ClassificationIn(BaseModel):
    category: str
    status: str = "confirmed"
    evidence: str | None = None


@router.post("/companies/{cid}/classifications")
def set_classification(cid: uuid.UUID, body: ClassificationIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = _load(db, cid)
    if body.category not in E.COMPANY_TYPES or body.status not in E.REVIEW_STATUSES:
        raise HTTPException(422, "invalid category/status")
    cl = next((x for x in c.classifications if x.category == body.category), None)
    if cl:
        cl.review_status = body.status
    else:
        db.add(CompanyClassification(company_id=cid, category=body.category, method="manual", confidence=1.0,
                                     evidence_text=body.evidence or f"Set manually by {user.email}", review_status=body.status))
    db.flush()
    score_company(db, _load(db, cid))
    db.commit()
    return {"ok": True}


@router.post("/companies/{cid}/recrawl")
def recrawl(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    from app.workers.runner import enqueue

    c = _load(db, cid)
    if not c.website:
        raise HTTPException(400, "Company has no website")
    j = enqueue(db, "company_website", "crawl_website", {"url": c.website, "country": c.country_code}, priority=10,
                user_id=user.id)
    db.commit()
    return {"job_id": j.id}


@router.post("/companies/{cid}/rescore")
def rescore(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _load(db, cid)
    b = score_company(db, c)
    db.commit()
    return {"lead_score": c.lead_score, "breakdown": b}
