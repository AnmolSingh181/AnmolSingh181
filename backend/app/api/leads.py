import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import enums as E
from app.api.serializers import lead_out
from app.auth import current_user, log_activity
from app.db import get_db
from app.models import Company, CompanyMaterial, Lead, LeadActivity, User

router = APIRouter(tags=["leads"])


def _opts():
    return [selectinload(Lead.company).selectinload(Company.materials).selectinload(CompanyMaterial.material),
            selectinload(Lead.company).selectinload(Company.classifications),
            selectinload(Lead.company).selectinload(Company.contacts), selectinload(Lead.activities)]


def _query(user, stage, priority, lead_type, material, due, q):
    qry = select(Lead).join(Company).where(Lead.owner_user_id == user.id)
    if stage:
        qry = qry.where(Lead.stage.in_(stage))
    if priority:
        qry = qry.where(Lead.priority.in_(priority))
    if lead_type:
        qry = qry.where(Lead.lead_type.in_(lead_type))
    if material:
        qry = qry.where(Lead.interested_materials.overlap(material))
    if due:
        qry = qry.where(Lead.next_follow_up_at.is_not(None), Lead.next_follow_up_at <= datetime.now(timezone.utc))
    if q:
        qry = qry.where(func.lower(Company.name).like(f"%{q.lower()}%"))
    return qry


@router.get("/leads")
def list_leads(stage: list[str] = Query(default=[]), priority: list[str] = Query(default=[]),
               lead_type: list[str] = Query(default=[]), material: list[str] = Query(default=[]), due: bool = False,
               q: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(_query(user, stage, priority, lead_type, material, due, q).options(*_opts())
                      .order_by(Lead.next_follow_up_at.asc().nullslast(), Lead.updated_at.desc())).all()
    counts = dict(db.execute(select(Lead.stage, func.count()).where(Lead.owner_user_id == user.id).group_by(Lead.stage)).all())
    return {"items": [lead_out(l) for l in rows], "stage_counts": {s: counts.get(s, 0) for s in E.LEAD_STAGES}}


class LeadIn(BaseModel):
    company_id: uuid.UUID
    lead_type: str = "unknown"
    stage: str = "new"
    priority: str = "medium"
    interested_materials: list[str] = []
    notes: str | None = None
    next_follow_up_at: datetime | None = None


def _validate(stage=None, priority=None, lead_type=None):
    if stage and stage not in E.LEAD_STAGES:
        raise HTTPException(422, "invalid stage")
    if priority and priority not in E.LEAD_PRIORITIES:
        raise HTTPException(422, "invalid priority")
    if lead_type and lead_type not in E.LEAD_TYPES:
        raise HTTPException(422, "invalid lead_type")


@router.post("/leads", status_code=201)
def create_lead(body: LeadIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _validate(body.stage, body.priority, body.lead_type)
    if not db.get(Company, body.company_id):
        raise HTTPException(404, "company not found")
    existing = db.scalar(select(Lead).where(Lead.company_id == body.company_id, Lead.owner_user_id == user.id))
    if existing:
        raise HTTPException(409, "Already saved as a lead")
    lead = Lead(owner_user_id=user.id, **body.model_dump())
    db.add(lead)
    db.flush()
    db.add(LeadActivity(lead_id=lead.id, user_id=user.id, activity_type="stage_change", summary=f"Lead created ({lead.stage})"))
    log_activity(db, user, "create_lead", "company", str(body.company_id))
    db.commit()
    return lead_out(db.scalar(select(Lead).where(Lead.id == lead.id).options(*_opts())))


class LeadPatch(BaseModel):
    lead_type: str | None = None
    stage: str | None = None
    priority: str | None = None
    interested_materials: list[str] | None = None
    communication_status: str | None = None
    notes: str | None = None
    last_contacted_at: datetime | None = None
    next_follow_up_at: datetime | None = None


def _own(db, lead_id, user) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.owner_user_id == user.id).options(*_opts()))
    if not lead:
        raise HTTPException(404)
    return lead


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: uuid.UUID, body: LeadPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lead = _own(db, lead_id, user)
    ch = body.model_dump(exclude_unset=True)
    _validate(ch.get("stage"), ch.get("priority"), ch.get("lead_type"))
    if "stage" in ch and ch["stage"] != lead.stage:
        db.add(LeadActivity(lead_id=lead.id, user_id=user.id, activity_type="stage_change",
                            summary=f"Stage: {lead.stage} -> {ch['stage']}"))
    for k, v in ch.items():
        setattr(lead, k, v)
    db.commit()
    return lead_out(_own(db, lead_id, user))


class ActivityIn(BaseModel):
    activity_type: str = "note"  # note | call | email | meeting | whatsapp
    summary: str
    mark_contacted: bool = False


@router.post("/leads/{lead_id}/activities", status_code=201)
def add_activity(lead_id: uuid.UUID, body: ActivityIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lead = _own(db, lead_id, user)
    db.add(LeadActivity(lead_id=lead.id, user_id=user.id, activity_type=body.activity_type[:30], summary=body.summary[:5000]))
    if body.mark_contacted or body.activity_type in ("call", "email", "meeting", "whatsapp"):
        lead.last_contacted_at = datetime.now(timezone.utc)
        if lead.stage in ("new", "researching"):
            lead.stage = "contacted"
    db.commit()
    return lead_out(_own(db, lead_id, user))


@router.delete("/leads/{lead_id}")
def delete_lead(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_own(db, lead_id, user))
    db.commit()
    return {"ok": True}


@router.get("/leads/export.csv")
def export_leads(stage: list[str] = Query(default=[]), priority: list[str] = Query(default=[]),
                 lead_type: list[str] = Query(default=[]), material: list[str] = Query(default=[]),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(_query(user, stage, priority, lead_type, material, False, None).options(*_opts())).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "public_ref", "country", "website", "company_email", "company_phone", "lead_type", "stage",
                "priority", "interested_materials", "lead_score", "last_contacted_at", "next_follow_up_at",
                "best_contact_name", "best_contact_title", "best_contact_email", "best_contact_phone", "notes"])
    for l in rows:
        c = l.company
        people = sorted([x for x in c.contacts if not x.is_opted_out and x.verification_status != "invalid"],
                        key=lambda x: (x.contact_type != "individual", x.decision_role == "unknown_authority"))
        best = people[0] if people else None
        w.writerow([c.name, c.public_ref, c.country_code, c.website, c.email, c.phone, l.lead_type, l.stage, l.priority,
                    ";".join(l.interested_materials or []), c.lead_score, l.last_contacted_at, l.next_follow_up_at,
                    best.full_name if best else "", best.job_title if best else "", best.email if best else "",
                    best.phone if best else "", (l.notes or "").replace("\n", " ")])
    log_activity(db, user, "export_leads", details={"rows": len(rows)})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})
