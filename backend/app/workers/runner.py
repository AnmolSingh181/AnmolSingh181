"""DB-backed job queue (scrape_jobs). Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED, so several
workers can run safely. A failing job never affects other jobs: it is rolled back, logged, retried with
exponential backoff (unless it is a configuration/terms/blocked error) and raises a 'job_failed' alert."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.base import NotConfigured, TermsNotConfirmed
from app.connectors.registry import get_connector
from app.db import SessionLocal
from app.models import ScrapeJob, Source
from app.services.alerts import create_alert
from app.services.http import BlockedError

log = logging.getLogger(__name__)
NO_RETRY = (NotConfigured, TermsNotConfirmed, BlockedError, ValueError)


def enqueue(db: Session, source_key: str, job_type: str, params: dict | None = None, priority: int = 100,
            user_id=None, scheduled_for: datetime | None = None) -> ScrapeJob:
    src = db.scalar(select(Source).where(Source.key == source_key))
    if not src:
        raise ValueError(f"unknown source {source_key}")
    job = ScrapeJob(source_id=src.id, job_type=job_type, params=params or {}, priority=priority, created_by=user_id,
                    scheduled_for=scheduled_for or datetime.now(timezone.utc))
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session) -> ScrapeJob | None:
    row = db.execute(text(
        "SELECT id FROM scrape_jobs WHERE status='queued' AND scheduled_for <= now() "
        "ORDER BY priority, scheduled_for LIMIT 1 FOR UPDATE SKIP LOCKED")).first()
    if not row:
        return None
    job = db.get(ScrapeJob, row[0])
    job.status, job.started_at, job.attempts = "running", datetime.now(timezone.utc), job.attempts + 1
    db.commit()
    return job


def execute(db: Session, job: ScrapeJob, connector_kwargs: dict | None = None) -> ScrapeJob:
    source = db.get(Source, job.source_id)
    cls = get_connector(source.key)
    now = datetime.now(timezone.utc)
    source.last_run_at = now
    try:
        if cls is None:
            raise NotConfigured(f"No connector registered for source '{source.key}'")
        conn = cls(db, source, job, **(connector_kwargs or {}))
        stats = conn.run(job.job_type, job.params or {})
        db.commit()
        job = db.get(ScrapeJob, job.id)
        source = db.get(Source, job.source_id)
        job.records_found, job.records_created = stats.found, stats.created
        job.records_updated, job.records_failed = stats.updated, stats.failed
        job.log = (job.log or []) + stats.log[-200:]
        job.status = "partial" if stats.failed and (stats.created or stats.updated) else \
            "failed" if stats.failed and not (stats.created or stats.updated or stats.found) else "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        source.last_success_at = job.finished_at if job.status != "failed" else source.last_success_at
        source.total_records = (source.total_records or 0) + stats.created
        if source.status == "error" and job.status != "failed":
            source.status = "active"
        source.last_error = None if job.status != "failed" else (stats.log[-1]["msg"] if stats.log else "failed")
        if job.status == "failed":
            create_alert(db, "job_failed", f"Job #{job.id} {source.name} / {job.job_type} failed",
                         entity_type="scrape_job", entity_id=str(job.id), severity="warning")
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(ScrapeJob, job.id)
        source = db.get(Source, job.source_id)
        retry = not isinstance(exc, NO_RETRY) and job.attempts < job.max_attempts
        job.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        job.log = (job.log or []) + [{"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": "error",
                                      "msg": traceback.format_exc()[-1500:]}]
        job.finished_at = datetime.now(timezone.utc)
        if retry:
            job.status = "queued"
            job.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=2 ** job.attempts)
        else:
            job.status = "failed"
            if isinstance(exc, NotConfigured):
                source.status = "awaiting_credentials" if source.requires_credentials else source.status
            elif isinstance(exc, TermsNotConfirmed):
                source.status = "requires_terms_review"
            else:
                source.status = "error" if source.status == "active" else source.status
            source.last_error = job.error_message
            create_alert(db, "job_failed", f"Job #{job.id} {source.name} / {job.job_type} failed: {exc}"[:500],
                         entity_type="scrape_job", entity_id=str(job.id), severity="warning")
        db.commit()
        log.warning("job %s failed (%s): %s", job.id, "will retry" if retry else "final", exc)
    return job


def run_pending(max_jobs: int = 10) -> int:
    n = 0
    db = SessionLocal()
    try:
        while n < max_jobs:
            job = claim_next(db)
            if not job:
                break
            execute(db, job)
            n += 1
    finally:
        db.close()
    return n


def recover_stale(db: Session, minutes: int = 120) -> int:
    """Jobs stuck in 'running' (worker crashed) go back to the queue."""
    res = db.execute(text("UPDATE scrape_jobs SET status='queued', scheduled_for=now() "
                          "WHERE status='running' AND started_at < now() - make_interval(mins => :m)"), {"m": minutes})
    db.commit()
    return res.rowcount or 0
