import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import enums as E
from app.api.serializers import contact_out
from app.auth import current_user, log_activity, require_editor
from app.db import get_db
from app.models import (Company, CompanyMaterial, Contact, ContactVerification, Country, Material, Source,
                        SuppressionEntry, User)
from app.services.contacts import verify_contact
from app.services.ingestion import ContactInput, upsert_contact
from app.services.normalize import normalize_email, normalize_phone, sha256
from app.services.search import visible

router = APIRouter(tags=["contacts"])


@router.get("/contacts")
def list_contacts(q: str | None = None, company_id: uuid.UUID | None = None, country: list[str] = Query(default=[]),
                  title: str | None = None, department: list[str] = Query(default=[]),
                  material: list[str] = Query(default=[]), verification: list[str] = Query(default=[]),
                  contact_type: str | None = None, decision_role: list[str] = Query(default=[]),
                  page: int = 1, page_size: int = 50, db: Session = Depends(get_db), user: User = Depends(current_user)):
    qry = select(Contact).join(Company).where(Contact.is_opted_out.is_(False))
    qry = visible(qry)
    if q:
        like = f"%{q.lower()}%"
        qry = qry.where(or_(func.lower(Contact.full_name).like(like), func.lower(Contact.email).like(like),
                            func.lower(Company.name).like(like)))
    if company_id:
        qry = qry.where(Contact.company_id == company_id)
    if country:
        qry = qry.where(or_(Contact.country_code.in_(country), Company.country_code.in_(country)))
    if title:
        qry = qry.where(func.lower(Contact.job_title).like(f"%{title.lower()}%"))
    if department:
        qry = qry.where(Contact.department.in_(department))
    if verification:
        qry = qry.where(Contact.verification_status.in_(verification))
    if contact_type:
        qry = qry.where(Contact.contact_type == contact_type)
    if decision_role:
        qry = qry.where(Contact.decision_role.in_(decision_role))
    if material:
        qry = qry.where(exists().where(CompanyMaterial.company_id == Contact.company_id, CompanyMaterial.is_current,
                                       CompanyMaterial.material_id == Material.id, Material.code.in_(material)))
    total = db.scalar(select(func.count()).select_from(qry.subquery()))
    rows = db.scalars(qry.options(selectinload(Contact.company)).order_by(
        (Contact.contact_type == "individual").desc(), Contact.updated_at.desc())
        .offset((max(page, 1) - 1) * page_size).limit(min(page_size, 200))).all()
    return {"total": total, "items": [contact_out(c, include_company=True) for c in rows]}


class ContactIn(BaseModel):
    contact_type: str = "individual"
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    evidence: str | None = None
    source_url: str | None = None


@router.post("/companies/{cid}/contacts", status_code=201)
def add_contact(cid: uuid.UUID, body: ContactIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = db.get(Company, cid)
    if not c:
        raise HTTPException(404)
    if not (body.email or body.phone or body.linkedin_url):
        raise HTTPException(422, "A contact needs an email, phone or LinkedIn URL")
    src = db.scalar(select(Source).where(Source.key == "manual"))
    prefix = db.get(Country, c.country_code).phone_prefix if c.country_code else None
    ok = upsert_contact(db, c, ContactInput(**body.model_dump(exclude={"evidence"}),
                                            evidence=body.evidence or f"Added manually by {user.email}"), src, prefix)
    if not ok:
        raise HTTPException(409, "Contact already exists for this company or is on the suppression (opt-out) list")
    db.flush()
    log_activity(db, user, "add_contact", "company", str(cid))
    db.commit()
    return {"ok": True}


class ContactPatch(BaseModel):
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    decision_role: str | None = None


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: uuid.UUID, body: ContactPatch, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404)
    ch = body.model_dump(exclude_unset=True)
    if "decision_role" in ch and ch["decision_role"] not in E.DECISION_ROLES:
        raise HTTPException(422, "invalid decision_role")
    for k, v in ch.items():
        setattr(c, k, v)
    if "email" in ch:
        c.email_normalized = normalize_email(c.email)
        c.verification_status = "discovered"  # changed data must be re-verified
    if "phone" in ch:
        c.phone_normalized = normalize_phone(c.phone)
    if ch.get("decision_role") == "confirmed_decision_maker":
        db.add(ContactVerification(contact_id=c.id, check_type="manual", result="pass", status_after=c.verification_status,
                                   details={"decision_role": "confirmed by user"}, checked_by=user.id))
    log_activity(db, user, "update_contact", "contact", str(contact_id), ch)
    db.commit()
    return contact_out(c)


@router.post("/contacts/{contact_id}/verify")
def run_verification(contact_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404)
    co = db.get(Company, c.company_id)
    prefix = db.get(Country, co.country_code).phone_prefix if co.country_code else None
    status = verify_contact(db, c, prefix)
    db.commit()
    return {"verification_status": status,
            "checks": [{"type": v.check_type, "result": v.result, "status_after": v.status_after, "details": v.details,
                        "provider": v.provider, "at": v.checked_at.isoformat() if v.checked_at else None}
                       for v in db.scalars(select(ContactVerification).where(ContactVerification.contact_id == c.id)
                                           .order_by(ContactVerification.checked_at)).all()]}


class ManualVerify(BaseModel):
    result: str = "pass"  # pass -> manually_verified, fail -> invalid
    note: str | None = None
    confirm_decision_maker: bool = False


@router.post("/contacts/{contact_id}/manual-verify")
def manual_verify(contact_id: uuid.UUID, body: ManualVerify, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404)
    status = "manually_verified" if body.result == "pass" else "invalid"
    db.add(ContactVerification(contact_id=c.id, check_type="manual", result="pass" if body.result == "pass" else "fail",
                               status_after=status, details={"note": body.note}, checked_by=user.id))
    c.verification_status, c.last_verified_at = status, datetime.now(timezone.utc)
    if body.confirm_decision_maker and body.result == "pass":
        c.decision_role = "confirmed_decision_maker"
    log_activity(db, user, "manual_verify_contact", "contact", str(contact_id), body.model_dump())
    db.commit()
    return contact_out(c)


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: uuid.UUID, suppress: bool = True, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Deletes personal data. With suppress=true the email/phone is hashed onto the suppression list so it is never re-collected."""
    c = db.get(Contact, contact_id)
    if not c:
        raise HTTPException(404)
    if suppress:
        for v, t in ((c.email_normalized, "email"), (c.phone_normalized, "phone")):
            if v and not db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.value_hash == sha256(v))):
                db.add(SuppressionEntry(value_hash=sha256(v), value_type=t, reason="deletion"))
    db.delete(c)
    log_activity(db, user, "delete_contact", "contact", str(contact_id))
    db.commit()
    return {"ok": True}
