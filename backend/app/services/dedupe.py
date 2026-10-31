"""Entity resolution.

Automatic match (same master record) requires a strong identifier:
  1. registration number + country
  2. company website/email domain (non-generic) + name not contradictory (token-set similarity >= 50)
  3. normalised phone + name similarity >= 60
  4. identical normalised name (or alias) + same country + same city, with no conflicting domain
Name similarity on its own NEVER merges - it only creates a DuplicateCandidate for human review.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rapidfuzz import fuzz
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import (Company, CompanyAlias, CompanyClassification, CompanyLocation, CompanyMaterial, CompanyNote,
                        CompanySourceRecord, Contact, DuplicateCandidate, Lead, PriceObservation, Shipment)
from app.services.normalize import core_name, normalize_company_name

log = logging.getLogger(__name__)


@dataclass
class CompanyCandidate:
    name: str
    country_code: str | None = None
    city: str | None = None
    address: str | None = None
    domain: str | None = None
    phone_normalized: str | None = None
    registration_number: str | None = None

    @property
    def normalized_name(self) -> str:
        return normalize_company_name(self.name)


@dataclass
class MatchResult:
    company: Company | None
    method: str
    score: float
    possible: list[tuple[Company, float, list[str]]] = field(default_factory=list)


def name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ca, cb = core_name(a), core_name(b)
    return max(fuzz.token_set_ratio(ca, cb), fuzz.ratio(a, b))


def _active(q):
    return q.where(Company.status == "active")


def _same_city(a: str | None, b: str | None) -> bool:
    return bool(a and b and normalize_company_name(a) == normalize_company_name(b))


def find_match(db: Session, cand: CompanyCandidate, allow_unique_exact_name: bool = False) -> MatchResult:
    """allow_unique_exact_name: for trade-data parties (name + country is all a bill of lading carries) accept an
    IDENTICAL normalised name in the same country when exactly one non-conflicting candidate exists."""
    nn = cand.normalized_name
    possible: dict[uuid.UUID, tuple[Company, float, list[str]]] = {}

    def add_possible(c: Company, score: float, reason: str):
        cur = possible.get(c.id)
        if cur:
            possible[c.id] = (c, max(cur[1], score), cur[2] + [reason])
        else:
            possible[c.id] = (c, score, [reason])

    if cand.registration_number and cand.country_code:
        c = db.scalar(_active(select(Company)).where(Company.country_code == cand.country_code,
                                                     Company.registration_number == cand.registration_number))
        if c:
            return MatchResult(c, "registration", 1.0)

    if cand.domain:
        for c in db.scalars(_active(select(Company)).where(Company.domain == cand.domain)).all():
            sim = name_similarity(nn, c.normalized_name)
            if sim >= 50:
                return MatchResult(c, "domain", round(0.9 + sim / 1000, 3))
            add_possible(c, 0.6, f"same domain {cand.domain} but different name (similarity {sim:.0f})")

    if cand.phone_normalized:
        for c in db.scalars(_active(select(Company)).where(Company.phone_normalized == cand.phone_normalized)).all():
            sim = name_similarity(nn, c.normalized_name)
            if sim >= 60:
                return MatchResult(c, "phone+name", round(0.85 + sim / 1000, 3))
            add_possible(c, 0.5, f"same phone but different name (similarity {sim:.0f})")

    if nn:
        alias_ids = select(CompanyAlias.company_id).where(CompanyAlias.normalized_alias == nn)
        q = _active(select(Company)).where(or_(Company.normalized_name == nn, Company.id.in_(alias_ids)))
        if cand.country_code:
            q = q.where(Company.country_code == cand.country_code)
        exact = db.scalars(q).all()
        clean = [c for c in exact if not (cand.domain and c.domain and cand.domain != c.domain)]
        if allow_unique_exact_name and cand.country_code and len(clean) == 1 and len(exact) == 1:
            return MatchResult(clean[0], "exact_name+country", 0.75)
        for c in exact:
            conflicting_domain = bool(cand.domain and c.domain and cand.domain != c.domain)
            if not conflicting_domain and cand.country_code and _same_city(cand.city, c.city):
                return MatchResult(c, "name+country+city", 0.8)
            if not conflicting_domain and cand.country_code and cand.address and c.address and \
                    normalize_company_name(cand.address) == normalize_company_name(c.address):
                return MatchResult(c, "name+country+address", 0.85)
            reason = "identical name" + (" in same country" if cand.country_code else "")
            if conflicting_domain:
                reason += f" but different domains ({c.domain} vs {cand.domain})"
            add_possible(c, 0.7, reason)

        # fuzzy candidates via pg_trgm (review only)
        if cand.country_code and len(nn) >= 4:
            rows = db.execute(text(
                "SELECT id, similarity(normalized_name, :n) AS s FROM companies "
                "WHERE status='active' AND country_code = :cc AND normalized_name % :n "
                "ORDER BY s DESC LIMIT 5"), {"n": nn, "cc": cand.country_code}).all()
            for cid, s in rows:
                if s >= 0.55 and cid not in possible:
                    c = db.get(Company, cid)
                    sim = name_similarity(nn, c.normalized_name)
                    if sim >= 80:
                        add_possible(c, round(min(0.65, s), 3), f"similar name (trigram {s:.2f}, token {sim:.0f})")

    return MatchResult(None, "new", 0.0, list(possible.values()))


def record_duplicate_candidates(db: Session, company: Company, possible: list[tuple[Company, float, list[str]]]) -> int:
    n = 0
    for other, score, reasons in possible:
        if other.id == company.id:
            continue
        a, b = (company.id, other.id) if str(company.id) < str(other.id) else (other.id, company.id)
        exists = db.scalar(select(DuplicateCandidate).where(DuplicateCandidate.company_a_id == a,
                                                            DuplicateCandidate.company_b_id == b))
        if exists:
            continue
        db.add(DuplicateCandidate(company_a_id=a, company_b_id=b, score=score, reasons=reasons))
        n += 1
    return n


def add_alias(db: Session, company: Company, alias: str, alias_type: str = "source_variant", source_id: int | None = None):
    na = normalize_company_name(alias)
    if not na or na == company.normalized_name:
        return
    exists = db.scalar(select(CompanyAlias.id).where(CompanyAlias.company_id == company.id, CompanyAlias.normalized_alias == na))
    if not exists:
        db.add(CompanyAlias(company_id=company.id, alias=alias[:300], normalized_alias=na[:300], alias_type=alias_type,
                            source_id=source_id))


FILLABLE = ["country_code", "state", "city", "address", "postal_code", "website", "domain", "email", "phone",
            "phone_normalized", "linkedin_url", "description", "registration_number", "registration_authority"]


def merge_companies(db: Session, master: Company, dup: Company, user_id=None) -> Company:
    """Merge dup into master. Nothing is deleted: dup becomes status='merged' pointing at master."""
    if master.id == dup.id:
        return master
    db.flush()
    for f in FILLABLE:
        if getattr(master, f) in (None, "") and getattr(dup, f) not in (None, ""):
            setattr(master, f, getattr(dup, f))
    add_alias(db, master, dup.name, "merged")
    for a in list(dup.aliases):
        add_alias(db, master, a.alias, a.alias_type)

    master_emails = {c.email_normalized for c in master.contacts if c.email_normalized}
    for c in list(dup.contacts):
        if c.email_normalized and c.email_normalized in master_emails:
            continue  # same mailbox already on master; dup copy stays attached to merged record for history
        c.company_id = master.id
    for loc in list(dup.locations):
        loc.company_id = master.id
    have = {c.category for c in master.classifications}
    for cl in list(dup.classifications):
        if cl.category not in have:
            cl.company_id = master.id
    master_keys = {(m.material_id, m.grade_category, m.application, m.relationship_type) for m in master.materials if m.is_current}
    for m in list(dup.materials):
        if m.is_current and (m.material_id, m.grade_category, m.application, m.relationship_type) in master_keys:
            m.is_current = False
        m.company_id = master.id
    db.flush()
    for sr in list(dup.source_records):
        clash = sr.raw_record_id is not None and db.scalar(select(CompanySourceRecord.id).where(CompanySourceRecord.company_id == master.id,
                                                               CompanySourceRecord.source_id == sr.source_id,
                                                               CompanySourceRecord.raw_record_id == sr.raw_record_id))
        if not clash:
            sr.company_id = master.id
    for n in list(dup.notes):
        n.company_id = master.id
    db.execute(update(Shipment).where(Shipment.importer_company_id == dup.id).values(importer_company_id=master.id))
    db.execute(update(Shipment).where(Shipment.exporter_company_id == dup.id).values(exporter_company_id=master.id))
    db.execute(update(PriceObservation).where(PriceObservation.company_id == dup.id).values(company_id=master.id))
    for lead in db.scalars(select(Lead).where(Lead.company_id == dup.id)).all():
        clash = db.scalar(select(Lead).where(Lead.company_id == master.id, Lead.owner_user_id == lead.owner_user_id))
        if clash:
            clash.notes = "\n".join(x for x in [clash.notes, f"[merged from {dup.name}] {lead.notes or ''}"] if x)
        else:
            lead.company_id = master.id
    dup.status = "merged"
    dup.merged_into_id = master.id
    db.execute(update(DuplicateCandidate).where(
        or_(and_(DuplicateCandidate.company_a_id == dup.id, DuplicateCandidate.company_b_id == master.id),
            and_(DuplicateCandidate.company_a_id == master.id, DuplicateCandidate.company_b_id == dup.id)))
        .values(status="merged", resolved_by=user_id, resolved_at=datetime.now(timezone.utc)))
    db.flush()
    db.expire(master)
    return master


def duplicate_rate(db: Session) -> float:
    total = db.scalar(select(func.count()).select_from(Company).where(Company.status == "active")) or 0
    pending = db.scalar(select(func.count()).select_from(DuplicateCandidate).where(DuplicateCandidate.status == "pending")) or 0
    return round(pending / total, 4) if total else 0.0
