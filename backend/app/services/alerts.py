"""Alerts: stored in DB (shown in UI) and optionally POSTed to ALERT_WEBHOOK_URL (e.g. an n8n workflow)."""
import logging

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Alert

log = logging.getLogger(__name__)


def create_alert(db: Session, alert_type: str, message: str, entity_type: str | None = None,
                 entity_id: str | None = None, payload: dict | None = None, severity: str = "info",
                 deliver: bool = True) -> Alert:
    a = Alert(alert_type=alert_type, message=message[:2000], entity_type=entity_type, entity_id=entity_id,
              payload=payload or {}, severity=severity)
    db.add(a)
    url = get_settings().alert_webhook_url
    if deliver and url:
        try:
            httpx.post(url, json={"type": alert_type, "severity": severity, "message": message,
                                  "entity_type": entity_type, "entity_id": entity_id, "payload": payload or {}},
                       timeout=5)
            a.delivered_webhook = True
        except Exception as exc:  # alert delivery must never break a job
            log.warning("Alert webhook failed: %s", exc)
    return a
