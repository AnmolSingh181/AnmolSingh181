"""Data source management, jobs, imports, duplicates, settings, data quality, alerts, dashboard, meta."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import enums as E
from app.api.serializers import company_summary, material_out, source_out
from app.auth import current_user, log_activity, require_admin, require_editor
from app.connectors.registry import DEFAULT_JOB, get_connector
from app.db import get_db
from app.models import (Alert, ApiUsage, Company, CompanyMaterial, Contact, Country, DuplicateCandidate, Material,
                        RawRecord, ScrapeJob, Source, User)
from app.services.dedupe import merge_companies
from app.services.metrics import dashboard, data_quality
from app.services.settings_store import get_setting, set_setting

router = APIRouter(tags=["admin"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return dashboard(db)


@router.get("/meta")
def meta(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {
        "countries": [{"code": c.code, "name": c.name, "is_active": c.is_active, "region": c.region}
                      for c in db.scalars(select(Country).order_by(Country.priority, Country.name)).all()],
        "materials": [{"code": m.code, "name": m.name, "is_target": m.is_target, "hs_codes": m.hs_codes, "notes": m.notes}
                      for m in db.scalars(select(Material).order_by(Material.id)).all()],
        "sources": [{"key": s.key, "name": s.name} for s in db.scalars(select(Source).order_by(Source.name)).all()],
        "company_types": E.COMPANY_TYPES, "grade_categories": E.GRADE_CATEGORIES, "applications": E.APPLICATIONS,
        "relationships": E.RELATIONSHIPS, "material_forms": E.MATERIAL_FORMS,
        "verification_statuses": E.CONTACT_VERIFICATION_STATUSES, "decision_roles": E.DECISION_ROLES,
        "lead_stages": E.LEAD_STAGES, "lead_types": E.LEAD_TYPES, "lead_priorities": E.LEAD_PRIORITIES,
        "tiers": [t["label"] for t in get_setting(db, "lead_scoring")["tiers"]],
        "departments": ["Procurement", "Sales", "Export/Import", "Management"],
    }


class CountryPatch(BaseModel):
    is_active: bool


@router.patch("/countries/{code}")
def update_country(code: str, body: CountryPatch, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    c = db.get(Country, code.upper())
    if not c:
        raise HTTPException(404)
    c.is_active = body.is_active
    db.commit()
    return {"code": c.code, "is_active": c.is_active}


# ------------------------------------------------------------------ sources & jobs
@router.get("/sources")
def list_sources(db: Session = Depends(get_db), user: User = Depends(current_user)):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    failed = dict(db.execute(select(ScrapeJob.source_id, func.count()).where(ScrapeJob.status == "failed",
                                                                             ScrapeJob.created_at >= since)
                             .group_by(ScrapeJob.source_id)).all())
    raw = dict(db.execute(select(RawRecord.source_id, func.count()).group_by(RawRecord.source_id)).all())
    out = []
    for s in db.scalars(select(Source).order_by(Source.source_type, Source.name)).all():
        d = source_out(s)
        cls = get_connector(s.key)
        try:
            d["readiness"] = cls(db, s).status() if cls else {"ready": False, "message": "no automated connector"}
        except Exception as exc:
            d["readiness"] = {"ready": False, "message": str(exc)}
        d["failed_jobs_30d"] = failed.get(s.id, 0)
        d["raw_records"] = raw.get(s.id, 0)
        d["default_job"] = DEFAULT_JOB.get(s.key)
        out.append(d)
    month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = [{"provider": p, "requests": int(n or 0), "units": int(u or 0), "cost_usd": float(c or 0)}
             for p, n, u, c in db.execute(select(ApiUsage.provider, func.count(), func.sum(ApiUsage.units),
                                                 func.sum(ApiUsage.estimated_cost_usd))
                                          .where(ApiUsage.created_at >= month).group_by(ApiUsage.provider)).all()]
    q = data_quality(db)
    return {"sources": out, "api_usage_month": usage,
            "summary": {"pending_duplicates": q["pending_duplicate_candidates"],
                        "materials_awaiting_review": q["materials_awaiting_review"],
                        "raw_pending": q["raw_records_pending"], "raw_failed": q["raw_records_failed"],
                        "contacts_awaiting_verification": db.scalar(select(func.count()).select_from(Contact).where(
                            Contact.verification_status.in_(["discovered", "syntax_checked"]))) or 0}}


class SourcePatch(BaseModel):
    enabled: bool | None = None
    status: str | None = None
    config: dict | None = None
    confirm_terms: bool | None = None
    terms_note: str | None = None
    refresh_interval_days: int | None = None


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourcePatch, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404)
    if body.config is not None:
        cfg = dict(body.config)
        cfg.pop("terms_confirmed", None)  # only via confirm_terms
        s.config = {**{k: v for k, v in (s.config or {}).items() if k.startswith("terms_")}, **cfg}
    if body.confirm_terms is not None:
        cfg = dict(s.config or {})
        if body.confirm_terms:
            cfg.update(terms_confirmed=True, terms_confirmed_by=user.email,
                       terms_confirmed_at=datetime.now(timezone.utc).isoformat(), terms_note=body.terms_note)
            if s.status == "requires_terms_review":
                s.status = "active"
        else:
            cfg.update(terms_confirmed=False)
            s.status = "requires_terms_review"
            s.enabled = False
        s.config = cfg
    if body.status is not None:
        if body.status not in E.SOURCE_STATUSES:
            raise HTTPException(422, "invalid status")
        s.status = body.status
    if body.enabled is not None:
        if body.enabled and s.status == "requires_terms_review":
            raise HTTPException(400, "Confirm the source's terms of use before enabling it")
        s.enabled = body.enabled
    if body.refresh_interval_days is not None:
        s.refresh_interval_days = body.refresh_interval_days
    log_activity(db, user, "update_source", "source", str(source_id), body.model_dump(exclude_none=True))
    db.commit()
    return source_out(s)


class RunIn(BaseModel):
    job_type: str | None = None
    params: dict = {}
    run_now: bool = False


@router.post("/sources/{key}/run")
def run_source(key: str, body: RunIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    from app.workers.runner import enqueue, execute

    s = db.scalar(select(Source).where(Source.key == key))
    if not s:
        raise HTTPException(404)
    jt = body.job_type or DEFAULT_JOB.get(key)
    if not jt:
        raise HTTPException(400, "This source has no automated job (use import or manual entry)")
    job = enqueue(db, key, jt, body.params, priority=20, user_id=user.id)
    db.commit()
    if body.run_now:
        job.status, job.started_at, job.attempts = "running", datetime.now(timezone.utc), 1
        db.commit()
        job = execute(db, job)
    return job_out(job)


def job_out(j: ScrapeJob) -> dict:
    return {"id": j.id, "source_id": j.source_id, "source": j.source.name if j.source else None,
            "source_key": j.source.key if j.source else None, "job_type": j.job_type, "params": j.params,
            "status": j.status, "attempts": j.attempts, "scheduled_for": j.scheduled_for, "started_at": j.started_at,
            "finished_at": j.finished_at, "records_found": j.records_found, "records_created": j.records_created,
            "records_updated": j.records_updated, "records_failed": j.records_failed, "error_message": j.error_message,
            "log": (j.log or [])[-50:], "created_at": j.created_at}


@router.get("/jobs")
def list_jobs(status: str | None = None, source: str | None = None, limit: int = 50, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    q = select(ScrapeJob).join(Source)
    if status:
        q = q.where(ScrapeJob.status == status)
    if source:
        q = q.where(Source.key == source)
    counts = dict(db.execute(select(ScrapeJob.status, func.count()).group_by(ScrapeJob.status)).all())
    return {"counts": counts, "items": [job_out(j) for j in db.scalars(q.order_by(ScrapeJob.id.desc()).limit(min(limit, 200))).all()]}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    j = db.get(ScrapeJob, job_id)
    if not j:
        raise HTTPException(404)
    j.status, j.scheduled_for, j.attempts, j.error_message = "queued", datetime.now(timezone.utc), 0, None
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    j = db.get(ScrapeJob, job_id)
    if not j or j.status not in ("queued",):
        raise HTTPException(400, "Only queued jobs can be cancelled")
    j.status = "cancelled"
    db.commit()
    return job_out(j)


@router.post("/imports")
async def import_file(file: UploadFile = File(...), kind: str = Form(...), origin_source: str | None = Form(None),
                      mapping: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(require_editor)):
    """Upload a permitted CSV/XLSX export. kind = companies | shipments. origin_source = source key the export came from."""
    from app.connectors.imports import CsvImportConnector, read_table

    if kind not in ("companies", "shipments"):
        raise HTTPException(422, "kind must be companies or shipments")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 20MB); split it into parts")
    src = db.scalar(select(Source).where(Source.key == "csv_import"))
    origin = db.scalar(select(Source).where(Source.key == origin_source)) if origin_source else None
    job = ScrapeJob(source_id=(origin or src).id, job_type="import_file", status="running", attempts=1,
                    params={"filename": file.filename, "kind": kind, "origin_source": origin_source},
                    started_at=datetime.now(timezone.utc), created_by=user.id)
    db.add(job)
    db.commit()
    try:
        headers, rows = read_table(content, file.filename or "upload.csv")
        conn = CsvImportConnector(db, src, job)
        stats = conn.import_rows(kind, headers, rows, json.loads(mapping) if mapping else None, origin_source=origin)
        job = db.get(ScrapeJob, job.id)
        job.status = "partial" if stats.failed and stats.created + stats.updated else "failed" if stats.failed else "succeeded"
        job.records_found, job.records_created, job.records_updated, job.records_failed = (
            stats.found, stats.created, stats.updated, stats.failed)
        job.log = stats.log[-200:]
        (origin or src).last_run_at = (origin or src).last_success_at = datetime.now(timezone.utc)
        (origin or src).total_records = ((origin or src).total_records or 0) + stats.created
    except Exception as exc:
        db.rollback()
        job = db.get(ScrapeJob, job.id)
        job.status, job.error_message = "failed", str(exc)[:2000]
    job.finished_at = datetime.now(timezone.utc)
    log_activity(db, user, "import_file", details={"file": file.filename, "kind": kind, "job": job.id})
    db.commit()
    return job_out(job)


# ------------------------------------------------------------------ duplicates
@router.get("/duplicates")
def list_duplicates(status: str = "pending", db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(DuplicateCandidate).where(DuplicateCandidate.status == status)
                      .order_by(DuplicateCandidate.score.desc()).limit(200)).all()
    out = []
    for d in rows:
        a, b = db.get(Company, d.company_a_id), db.get(Company, d.company_b_id)
        if not a or not b:
            continue
        out.append({"id": d.id, "score": d.score, "reasons": d.reasons, "status": d.status,
                    "a": company_summary(a) | {"domain": a.domain, "address": a.address},
                    "b": company_summary(b) | {"domain": b.domain, "address": b.address}})
    return out


class MergeIn(BaseModel):
    master_id: uuid.UUID


@router.post("/duplicates/{dup_id}/merge")
def merge_duplicate(dup_id: int, body: MergeIn, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    d = db.get(DuplicateCandidate, dup_id)
    if not d or d.status != "pending":
        raise HTTPException(404)
    if body.master_id not in (d.company_a_id, d.company_b_id):
        raise HTTPException(422, "master must be one of the pair")
    other = d.company_b_id if body.master_id == d.company_a_id else d.company_a_id
    master = merge_companies(db, db.get(Company, body.master_id), db.get(Company, other), user.id)
    from app.services.scoring import score_company

    score_company(db, db.get(Company, master.id))
    log_activity(db, user, "merge_companies", "company", str(master.id), {"merged": str(other)})
    db.commit()
    return {"master_id": str(master.id)}


@router.post("/duplicates/{dup_id}/reject")
def reject_duplicate(dup_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    d = db.get(DuplicateCandidate, dup_id)
    if not d:
        raise HTTPException(404)
    d.status, d.resolved_by, d.resolved_at = "rejected", user.id, datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ settings, quality, alerts
@router.get("/settings/{key}")
def read_setting(key: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return get_setting(db, key)


@router.put("/settings/{key}")
def write_setting(key: str, value: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if key == "lead_scoring":
        w = value.get("weights", {})
        if not w or any(not isinstance(v, (int, float)) or v < 0 for v in w.values()):
            raise HTTPException(422, "weights must be non-negative numbers")
    out = set_setting(db, key, value)
    log_activity(db, user, "update_setting", "setting", key)
    db.commit()
    return out


@router.post("/admin/rescore")
def rescore_everything(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    from app.services.scoring import rescore_all

    return {"rescored": rescore_all(db)}


@router.get("/quality")
def quality(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return data_quality(db)


@router.get("/quality/review-sample")
def review_sample(n: int = 20, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Random auto-classified material rows for manual accuracy review."""
    from sqlalchemy.orm import selectinload

    rows = db.scalars(select(CompanyMaterial).join(Company).where(
        Company.status == "active", CompanyMaterial.is_current, CompanyMaterial.review_status.in_(["auto", "needs_review"]))
        .options(selectinload(CompanyMaterial.material), selectinload(CompanyMaterial.specifications))
        .order_by(func.random()).limit(min(n, 100))).all()
    out = []
    for m in rows:
        c = db.get(Company, m.company_id)
        out.append(material_out(m) | {"company_id": str(c.id), "company_name": c.name, "country_code": c.country_code})
    return out


@router.get("/alerts")
def list_alerts(unread_only: bool = False, limit: int = 50, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Alert)
    if unread_only:
        q = q.where(Alert.is_read.is_(False))
    rows = db.scalars(q.order_by(Alert.created_at.desc()).limit(min(limit, 200))).all()
    unread = db.scalar(select(func.count()).select_from(Alert).where(Alert.is_read.is_(False)))
    return {"unread": unread, "items": [{"id": a.id, "type": a.alert_type, "severity": a.severity, "message": a.message,
                                         "entity_type": a.entity_type, "entity_id": a.entity_id, "is_read": a.is_read,
                                         "created_at": a.created_at} for a in rows]}


@router.post("/alerts/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    from sqlalchemy import update

    db.execute(update(Alert).where(Alert.is_read.is_(False)).values(is_read=True))
    db.commit()
    return {"ok": True}
