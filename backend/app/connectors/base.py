"""Connector framework. Each source is an independent connector; failures are isolated per job."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import ScrapeJob, Source

log = logging.getLogger(__name__)


class NotConfigured(Exception):
    """Credentials / contract missing. Job is failed without retry; source shows awaiting_credentials."""


class TermsNotConfirmed(Exception):
    """Source terms have not been reviewed/confirmed by an admin - automated collection is disabled."""


@dataclass
class JobStats:
    found: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0
    log: list = field(default_factory=list)


class BaseConnector:
    key: str = ""
    job_types: tuple[str, ...] = ()
    requires_terms_confirmation: bool = False

    def __init__(self, db: Session, source: Source, job: ScrapeJob | None = None):
        self.db = db
        self.source = source
        self.job = job
        self.stats = JobStats()

    # -- helpers
    def log(self, msg: str, level: str = "info"):
        entry = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": level, "msg": msg[:500]}
        self.stats.log.append(entry)
        getattr(log, level if level in ("info", "warning", "error") else "info")("[%s] %s", self.key, msg)

    def status(self) -> dict:
        """Readiness without network calls."""
        return {"ready": True, "message": "ready"}

    def ensure_allowed(self):
        if self.requires_terms_confirmation and not (self.source.config or {}).get("terms_confirmed"):
            raise TermsNotConfirmed(
                f"{self.source.name}: terms of use not confirmed. Review {self.source.base_url} terms and confirm in "
                "Data Sources before enabling automated collection.")

    def run(self, job_type: str, params: dict) -> JobStats:  # pragma: no cover - interface
        raise NotImplementedError
