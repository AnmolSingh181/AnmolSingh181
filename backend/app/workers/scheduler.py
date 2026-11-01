"""Scheduled refresh workflows (APScheduler) + queue worker loop.

Run:  python -m app.workers.scheduler
Schedules come from app_settings.refresh_schedule (editable via API). Each workflow only ENQUEUES jobs; the worker
loop executes them, so a failing source never blocks the others.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ScrapeJob, Source
from app.services.contacts import mark_outdated
from app.services.scoring import rescore_all
from app.services.settings_store import get_setting
from app.workers.runner import enqueue, recover_stale, run_pending

log = logging.getLogger("scheduler")


def _has_open_job(db, source_key: str, job_type: str) -> bool:
    src = db.scalar(select(Source).where(Source.key == source_key))
    return bool(src and db.scalar(select(ScrapeJob.id).where(
        ScrapeJob.source_id == src.id, ScrapeJob.job_type == job_type, ScrapeJob.status.in_(["queued", "running"]))))


def enqueue_if_enabled(source_key: str, job_type: str, params: dict | None = None, min_interval_days: float | None = None):
    db = SessionLocal()
    try:
        src = db.scalar(select(Source).where(Source.key == source_key))
        if not src or not src.enabled:
            return
        if _has_open_job(db, source_key, job_type):
            return
        if min_interval_days and src.last_success_at and \
                src.last_success_at > datetime.now(timezone.utc) - timedelta(days=min_interval_days):
            return  # ran recently (e.g. worker restarted) - skip
        enqueue(db, source_key, job_type, params or {}, priority=120)
        db.commit()
        log.info("scheduled %s/%s", source_key, job_type)
    finally:
        db.close()


def weekly_discovery():
    enqueue_if_enabled("web_search", "discover", {"max_queries": 20}, min_interval_days=6)


def producer_discovery():
    """Key-free: Wikidata PE/petrochemical producers -> queue their websites for crawling."""
    enqueue_if_enabled("wikidata", "discover_producers", {}, min_interval_days=25)


def website_refresh():
    db = SessionLocal()
    days = get_setting(db, "refresh_schedule").get("website_days", 45)
    db.close()
    enqueue_if_enabled("company_website", "refresh_websites", {"older_than_days": days, "limit": 50})


def trade_refresh():
    for key, jt in (("us_census", "trade_stats"), ("un_comtrade", "trade_stats"), ("importyeti", "fetch_shipments"),
                    ("volza", "fetch_shipments"), ("panjiva", "fetch_shipments"), ("tradedata_pro", "fetch_shipments")):
        enqueue_if_enabled(key, jt)


def contact_refresh():
    enqueue_if_enabled("apollo", "enrich_contacts", {"limit": 25})
    db = SessionLocal()
    try:
        n = mark_outdated(db, 180)
        db.commit()
        log.info("marked %s contacts outdated", n)
    finally:
        db.close()


def rescore():
    db = SessionLocal()
    try:
        log.info("rescored %s companies", rescore_all(db))
    finally:
        db.close()


def housekeeping():
    db = SessionLocal()
    try:
        recover_stale(db)
    finally:
        db.close()


def build_scheduler() -> BackgroundScheduler:
    db = SessionLocal()
    sched_cfg = get_setting(db, "refresh_schedule")
    db.close()
    s = BackgroundScheduler(timezone="UTC")
    s.add_job(weekly_discovery, "interval", days=sched_cfg.get("discovery_days", 7), id="discovery",
              next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5))
    s.add_job(producer_discovery, "interval", days=1, id="producers",
              next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1))
    s.add_job(website_refresh, "interval", days=1, id="website_refresh")  # daily sweep of records older than N days
    s.add_job(trade_refresh, "interval", days=sched_cfg.get("trade_days", 7), id="trade")
    s.add_job(contact_refresh, "interval", days=sched_cfg.get("contact_days", 30), id="contacts")
    s.add_job(rescore, "interval", hours=sched_cfg.get("rescore_hours", 24), id="rescore")
    s.add_job(housekeeping, "interval", minutes=30, id="housekeeping")
    return s


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sched = build_scheduler()
    sched.start()
    log.info("scheduler started; worker loop polling queue")
    try:
        while True:
            try:
                if run_pending(max_jobs=5) == 0:
                    time.sleep(10)
            except Exception as exc:  # keep the worker alive
                log.exception("worker loop error: %s", exc)
                time.sleep(30)
    except KeyboardInterrupt:
        sched.shutdown()


if __name__ == "__main__":
    main()
