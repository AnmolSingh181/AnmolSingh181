"""Auth, natural-language search, privacy requests (opt-out / correction / deletion)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import company_summary
from app.auth import current_user, hash_password, issue_token, log_activity, require_admin, verify_password
from app.config import get_settings
from app.db import get_db
from app.models import Contact, PrivacyRequest, SuppressionEntry, User
from app.services.nl_search import parse_query
from app.services.normalize import normalize_email, sha256
from app.services.search import search_companies

router = APIRouter()


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login", tags=["auth"])
def login(body: LoginIn, db: Session = Depends(get_db)):
    if get_settings().auth_mode != "local":
        raise HTTPException(400, "Local login disabled (AUTH_MODE=supabase) - sign in via Supabase Auth")
    u = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    u.last_login_at = datetime.now(timezone.utc)
    log_activity(db, u, "login")
    db.commit()
    return {"access_token": issue_token(u), "token_type": "bearer",
            "user": {"id": str(u.id), "email": u.email, "role": u.role, "full_name": u.full_name}}


@router.get("/auth/me", tags=["auth"])
def me(user: User = Depends(current_user)):
    return {"id": str(user.id), "email": user.email, "role": user.role, "full_name": user.full_name,
            "auth_mode": get_settings().auth_mode, "demo_mode": get_settings().show_demo_data}


class UserIn(BaseModel):
    email: EmailStr
    password: str | None = None
    full_name: str | None = None
    role: str = "analyst"


@router.get("/auth/users", tags=["auth"])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [{"id": str(u.id), "email": u.email, "role": u.role, "full_name": u.full_name, "is_active": u.is_active,
             "last_login_at": u.last_login_at} for u in db.scalars(select(User).order_by(User.created_at)).all()]


@router.post("/auth/users", tags=["auth"], status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.role not in ("admin", "analyst", "viewer"):
        raise HTTPException(422, "invalid role")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "User exists")
    if get_settings().auth_mode == "local" and (not body.password or len(body.password) < 10):
        raise HTTPException(422, "Password must be at least 10 characters")
    u = User(email=body.email.lower(), full_name=body.full_name, role=body.role,
             password_hash=hash_password(body.password) if body.password else None)
    db.add(u)
    db.commit()
    return {"id": str(u.id), "email": u.email, "role": u.role}


# ------------------------------------------------------------------ NL search
class NLIn(BaseModel):
    query: str
    page: int = 1
    page_size: int = 25
    use_ai: bool = True


@router.post("/search/nl", tags=["search"])
def nl_search(body: NLIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not body.query.strip():
        raise HTTPException(422, "empty query")
    filters, notes, parser = parse_query(db, body.query, body.use_ai)
    filters.page, filters.page_size = body.page, body.page_size
    total, rows = search_companies(db, filters)
    items = []
    for c in rows:
        s = company_summary(c)
        s["top_contacts"] = [{"name": x.full_name, "title": x.job_title, "email": x.email, "phone": x.phone,
                              "verification_status": x.verification_status, "source_url": x.source_url}
                             for x in sorted([x for x in c.contacts if not x.is_opted_out and x.verification_status != "invalid"],
                                             key=lambda x: (x.contact_type != "individual", x.decision_role == "unknown_authority"))[:3]]
        from app.services.search import GRADE_EXPAND, REL_EXPAND

        grades = {x for g in filters.grades for x in GRADE_EXPAND.get(g, [g])}
        rels = {x for r in filters.relationships for x in REL_EXPAND.get(r, [r])}

        def rank(m):  # evidence that matches more of the question first
            return -((not filters.polymers or m.material.code in filters.polymers) * 4
                     + (not grades or m.grade_category in grades) * 2 + (not rels or m.relationship_type in rels))

        mats = sorted([m for m in c.materials if m.is_current and m.review_status != "rejected"
                       and (not filters.polymers or m.material.code in filters.polymers)], key=rank)
        s["evidence"] = [{"polymer": m.material.code, "grade": m.grade_category, "relationship": m.relationship_type,
                          "text": (m.evidence_text or "")[:300], "url": m.evidence_url} for m in mats[:3]]
        items.append(s)
    log_activity(db, user, "nl_search", details={"query": body.query, "parser": parser, "results": total})
    db.commit()
    return {"query": body.query, "parser": parser, "interpretation": notes, "filters": filters.model_dump(exclude_defaults=True),
            "total": total, "items": items,
            "note": "Results are database records only. Empty results mean no matching evidence has been collected yet."}


# ------------------------------------------------------------------ privacy
class PrivacyIn(BaseModel):
    request_type: str  # opt_out | correction | deletion
    email: EmailStr
    details: str | None = None


@router.post("/privacy/requests", tags=["privacy"], status_code=201)
def submit_privacy_request(body: PrivacyIn, db: Session = Depends(get_db)):
    """Public endpoint (no auth) so data subjects can request opt-out, correction or deletion."""
    if body.request_type not in ("opt_out", "correction", "deletion"):
        raise HTTPException(422, "invalid request_type")
    email = normalize_email(body.email)
    contact = db.scalar(select(Contact).where(Contact.email_normalized == email))
    pr = PrivacyRequest(request_type=body.request_type, requester_email=email, contact_id=contact.id if contact else None,
                        details=(body.details or "")[:4000])
    db.add(pr)
    if body.request_type == "opt_out":  # honour immediately; admin review only confirms
        for c in db.scalars(select(Contact).where(Contact.email_normalized == email)).all():
            c.is_opted_out = True
        if not db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.value_hash == sha256(email))):
            db.add(SuppressionEntry(value_hash=sha256(email), value_type="email", reason="opt_out"))
    db.commit()
    return {"id": pr.id, "status": pr.status,
            "message": "Request received. Opt-outs take effect immediately; corrections and deletions are processed by an administrator."}


@router.get("/privacy/requests", tags=["privacy"])
def list_privacy(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [{"id": p.id, "type": p.request_type, "email": p.requester_email, "contact_id": str(p.contact_id) if p.contact_id else None,
             "details": p.details, "status": p.status, "created_at": p.created_at, "resolved_at": p.resolved_at,
             "resolution_notes": p.resolution_notes}
            for p in db.scalars(select(PrivacyRequest).order_by(PrivacyRequest.created_at.desc())).all()]


class ResolveIn(BaseModel):
    status: str = "completed"
    notes: str | None = None
    apply_deletion: bool = False


@router.post("/privacy/requests/{rid}/resolve", tags=["privacy"])
def resolve_privacy(rid: int, body: ResolveIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = db.get(PrivacyRequest, rid)
    if not p:
        raise HTTPException(404)
    if body.apply_deletion and p.request_type == "deletion":
        for c in db.scalars(select(Contact).where(Contact.email_normalized == p.requester_email)).all():
            for v, t in ((c.email_normalized, "email"), (c.phone_normalized, "phone")):
                if v and not db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.value_hash == sha256(v))):
                    db.add(SuppressionEntry(value_hash=sha256(v), value_type=t, reason="deletion"))
                    db.flush()
            db.delete(c)
        p.contact_id = None
    p.status, p.resolution_notes, p.resolved_at = body.status, body.notes, datetime.now(timezone.utc)
    log_activity(db, admin, "resolve_privacy_request", "privacy_request", str(rid), body.model_dump())
    db.commit()
    return {"ok": True}
