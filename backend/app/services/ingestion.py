"""Ingestion pipeline shared by every connector.

raw record -> extraction -> classification (rules, then validated AI) -> entity resolution -> upsert
-> contacts (suppression-aware) -> source traceability -> lead score -> alerts.
History is preserved: nothing collected earlier is deleted; superseded material rows are closed (is_current=false).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import enums as E
from app.config import get_settings
from app.data.reference import HS_MATERIAL_MAP
from app.models import (Company, CompanyClassification, CompanyLocation, CompanyMaterial, CompanySourceRecord, Contact,
                        Country, Material, MaterialSpecification, PriceObservation, RawRecord, ScrapeJob, Shipment,
                        Source, SuppressionEntry, TradeStatistic)
from app.services import ai_classifier
from app.services.alerts import create_alert
from app.services.classifier import ClassificationResult, classify_text, find_polymers, _matches
from app.services.contacts import decision_role_for_title, department_for_title
from app.services.dedupe import CompanyCandidate, add_alias, find_match, record_duplicate_candidates
from app.services.normalize import (clean_text, company_domain, normalize_company_name, normalize_email,
                                    normalize_phone, normalize_url, sha256)
from app.services.scoring import score_company

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ input models
class ContactInput(BaseModel):
    contact_type: str = "general"
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    country: str | None = None
    evidence: str | None = None
    source_url: str | None = None
    decision_role: str | None = None


class MaterialInput(BaseModel):
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
    quantity_unit: str | None = None
    price: float | None = None
    currency: str | None = None
    price_unit: str | None = None


class CompanyInput(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    state: str | None = None
    city: str | None = None
    address: str | None = None
    postal_code: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    description: str | None = None
    registration_number: str | None = None
    registration_authority: str | None = None
    company_types: list[str] = Field(default_factory=list)       # explicit from source (e.g. directory category)
    company_type_evidence: str | None = None
    classification_text: str | None = None                       # page text to classify
    materials: list[MaterialInput] = Field(default_factory=list)  # explicit (CSV/trade data)
    contacts: list[ContactInput] = Field(default_factory=list)
    source_url: str | None = None
    external_id: str | None = None
    collected_at: datetime | None = None
    is_demo: bool = False


class ShipmentInput(BaseModel):
    external_id: str | None = None
    shipment_date: date | None = None
    importer_name: str | None = None
    importer_address: str | None = None
    importer_country: str | None = None
    exporter_name: str | None = None
    exporter_address: str | None = None
    exporter_country: str | None = None
    origin_country: str | None = None
    destination_country: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    hs_code: str | None = None
    product_description: str | None = None
    quantity: float | None = None
    quantity_unit: str | None = None
    weight_kg: float | None = None
    value: float | None = None
    currency: str | None = None
    bill_of_lading: str | None = None
    source_url: str | None = None
    is_demo: bool = False


# ------------------------------------------------------------------ helpers
_country_cache: dict[str, str] | None = None


def _country_index(db: Session) -> dict[str, str]:
    global _country_cache
    if _country_cache is None:
        idx = {}
        for c in db.scalars(select(Country)).all():
            idx[c.code.lower()] = c.code
            idx[c.name.lower()] = c.code
            for a in c.aliases or []:
                idx[a.lower()] = c.code
        _country_cache = idx
    return _country_cache


def reset_country_cache():
    global _country_cache
    _country_cache = None


def resolve_country(db: Session, value: str | None) -> str | None:
    if not value:
        return None
    v = clean_text(value).lower().strip(" .,")
    idx = _country_index(db)
    if v in idx:
        return idx[v]
    for k, code in idx.items():  # "Dubai, UAE" -> match trailing token
        if len(k) > 2 and (v.endswith(" " + k) or v.endswith("," + k) or v.endswith(", " + k)):
            return code
    return None


def _phone_prefix(db: Session, cc: str | None) -> str | None:
    if not cc:
        return None
    c = db.get(Country, cc)
    return c.phone_prefix if c else None


def material_ids(db: Session) -> dict[str, int]:
    return {m.code: m.id for m in db.scalars(select(Material)).all()}


def content_hash(payload) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def store_raw(db: Session, source: Source, record_type: str, payload: dict, raw_text: str | None = None,
              source_url: str | None = None, external_id: str | None = None, job: ScrapeJob | None = None,
              is_demo: bool = False) -> tuple[RawRecord, bool]:
    h = content_hash({"p": payload, "t": raw_text, "u": source_url})
    existing = db.scalar(select(RawRecord).where(RawRecord.source_id == source.id, RawRecord.content_hash == h))
    if existing:
        return existing, False
    rr = RawRecord(source_id=source.id, scrape_job_id=job.id if job else None, record_type=record_type,
                   source_url=source_url, external_id=external_id, content_hash=h, payload=payload,
                   raw_text=raw_text, is_demo=is_demo)
    db.add(rr)
    db.flush()
    return rr, True


def is_suppressed(db: Session, email: str | None = None, phone: str | None = None) -> bool:
    hashes = [sha256(v) for v in (email, phone) if v]
    if not hashes:
        return False
    return bool(db.scalar(select(SuppressionEntry.id).where(SuppressionEntry.value_hash.in_(hashes))))


# ------------------------------------------------------------------ company ingestion
class IngestOutcome(BaseModel):
    company_id: str
    created: bool
    match_method: str
    materials_added: int = 0
    contacts_added: int = 0
    duplicates_flagged: int = 0


def _apply_classification(db: Session, company: Company, result: ClassificationResult, methods: dict, source: Source,
                          raw: RawRecord | None, url: str | None, mids: dict[str, int], is_new: bool,
                          is_demo: bool) -> int:
    added = 0
    now = datetime.now(timezone.utc)
    current = {(m.material_id, m.grade_category, m.application, m.relationship_type): m
               for m in company.materials if m.is_current}
    new_keys = []
    for f in result.materials:
        mid = mids.get(f.polymer)
        if not mid:
            continue
        key = (mid, f.grade_category, f.application, f.relationship)
        method = methods.get(f.key, "rule")
        row = current.get(key)
        if row:
            row.last_seen_at = now
            if row.review_status not in ("confirmed", "rejected") and f.confidence > row.confidence:
                row.confidence, row.evidence_text, row.evidence_url = f.confidence, f.evidence, url
            for attr in ("available_quantity", "required_quantity", "quantity_unit", "quantity_period", "form"):
                if getattr(f, attr) is not None:
                    setattr(row, attr, getattr(f, attr))
        else:
            row = CompanyMaterial(company_id=company.id, material_id=mid, grade_category=f.grade_category,
                                  application=f.application, relationship_type=f.relationship, form=f.form,
                                  available_quantity=f.available_quantity, required_quantity=f.required_quantity,
                                  quantity_unit=f.quantity_unit, quantity_period=f.quantity_period,
                                  method=method, confidence=f.confidence, evidence_text=f.evidence, evidence_url=url,
                                  raw_record_id=raw.id if raw else None, source_id=source.id,
                                  review_status=f.review_status)
            db.add(row)
            company.materials.append(row)
            current[key] = row
            added += 1
            new_keys.append(f"{f.polymer} {f.grade_category} {f.application} ({f.relationship})")
        db.flush()
        existing_specs = {(s.grade_number, s.mfi, s.density, s.colour, s.brand) for s in row.specifications}
        for sp in f.specs:
            sig = (sp.grade_number, sp.mfi, sp.density, sp.colour, sp.brand)
            if sig in existing_specs:
                continue
            existing_specs.add(sig)
            db.add(MaterialSpecification(company_material_id=row.id, grade_number=sp.grade_number, brand=sp.brand,
                                         mfi=sp.mfi, mfi_conditions=sp.mfi_conditions, density=sp.density,
                                         colour=sp.colour, form=sp.form, origin_country=sp.origin_country,
                                         packaging=sp.packaging, evidence_text=sp.evidence, evidence_url=url,
                                         method=method, raw_record_id=raw.id if raw else None))
    if new_keys and not is_new:
        create_alert(db, "material_change", f"{company.name}: new material portfolio entries - {'; '.join(new_keys[:5])}",
                     entity_type="company", entity_id=str(company.id), payload={"added": new_keys})

    polys = {m.material.code if m.material else None for m in company.materials if m.is_current}
    for p in result.prices:
        poly = p.polymer or (next(iter(polys)) if len(polys) == 1 else None)
        if not poly or poly not in mids:
            continue
        dup = db.scalar(select(PriceObservation.id).where(PriceObservation.company_id == company.id,
                                                          PriceObservation.evidence_text == p.evidence))
        if not dup:
            db.add(PriceObservation(company_id=company.id, material_id=mids[poly], price=p.price, currency=p.currency,
                                    unit=p.unit, incoterm=p.incoterm, evidence_text=p.evidence, source_url=url,
                                    source_id=source.id, raw_record_id=raw.id if raw else None, is_demo=is_demo))

    have = {c.category: c for c in company.classifications}
    for b in result.business_types:
        if b.category not in E.COMPANY_TYPES:
            continue
        cur = have.get(b.category)
        if cur:
            if cur.review_status not in ("confirmed", "rejected") and b.confidence > cur.confidence:
                cur.confidence, cur.evidence_text, cur.evidence_url = b.confidence, b.evidence, url
            continue
        cl = CompanyClassification(company_id=company.id, category=b.category,
                                   method=methods.get(("bt", b.category), "rule"), confidence=b.confidence,
                                   evidence_text=b.evidence, evidence_url=url, raw_record_id=raw.id if raw else None)
        db.add(cl)
        company.classifications.append(cl)
        have[b.category] = cl
    return added


def upsert_contact(db: Session, company: Company, ci: ContactInput, source: Source, prefix: str | None,
                   is_demo: bool = False) -> bool:
    email = normalize_email(ci.email)
    phone_n = normalize_phone(ci.phone, prefix)
    if not (email or phone_n or ci.linkedin_url):
        return False
    if is_suppressed(db, email, phone_n):
        log.info("Contact suppressed (opt-out/deletion) - not stored")
        return False
    existing = None
    for c in company.contacts:
        if (email and c.email_normalized == email) or (not email and phone_n and c.phone_normalized == phone_n
                                                        and c.contact_type == ci.contact_type and not c.email):
            existing = c
            break
    if existing:
        if existing.is_opted_out:
            return False
        for attr, val in (("full_name", ci.full_name), ("job_title", ci.job_title), ("linkedin_url", ci.linkedin_url)):
            if val and not getattr(existing, attr):
                setattr(existing, attr, val)
        if ci.phone and not existing.phone:
            existing.phone, existing.phone_normalized = ci.phone, phone_n
        if existing.verification_status == "outdated":
            existing.verification_status = "discovered"
        existing.updated_at = datetime.now(timezone.utc)
        return False
    ctype = ci.contact_type if ci.contact_type in E.CONTACT_TYPES else "general"
    if ci.full_name:
        ctype = "individual"
    role = ci.decision_role if ci.decision_role in E.DECISION_ROLES and ci.decision_role != "confirmed_decision_maker" \
        else decision_role_for_title(ci.job_title) if ctype == "individual" else "unknown_authority"
    c = Contact(company_id=company.id, contact_type=ctype, full_name=ci.full_name, job_title=ci.job_title,
                department=ci.department or department_for_title(ci.job_title), decision_role=role,
                email=ci.email.strip() if ci.email else None, email_normalized=email, phone=ci.phone, phone_normalized=phone_n,
                linkedin_url=ci.linkedin_url, country_code=company.country_code, source_id=source.id,
                source_url=ci.source_url, evidence_text=(ci.evidence or "")[:1000] or None, is_demo=is_demo)
    db.add(c)
    company.contacts.append(c)
    return True


def ingest_company(db: Session, source: Source, data: CompanyInput, raw: RawRecord | None = None,
                   job: ScrapeJob | None = None, use_ai: bool = True, explicit_method: str = "import",
                   allow_unique_exact_name: bool = False) -> IngestOutcome:
    s = get_settings()
    cc = resolve_country(db, data.country)
    prefix = _phone_prefix(db, cc)
    website = normalize_url(data.website)
    domain = company_domain(website, data.email)
    phone_n = normalize_phone(data.phone, prefix)
    now = datetime.now(timezone.utc)
    collected = data.collected_at or now

    cand = CompanyCandidate(name=data.name, country_code=cc, city=data.city, address=data.address, domain=domain,
                            phone_normalized=phone_n, registration_number=data.registration_number)
    match = find_match(db, cand, allow_unique_exact_name=allow_unique_exact_name)
    created = match.company is None
    if created:
        company = Company(name=clean_text(data.name)[:300], normalized_name=cand.normalized_name[:300] or data.name.lower(),
                          country_code=cc, state=data.state, city=data.city, address=data.address,
                          postal_code=data.postal_code, website=website, domain=domain,
                          email=normalize_email(data.email), phone=data.phone, phone_normalized=phone_n,
                          linkedin_url=data.linkedin_url, description=(data.description or "")[:4000] or None,
                          registration_number=data.registration_number,
                          registration_authority=data.registration_authority, primary_source_id=source.id,
                          first_discovered_at=collected, last_seen_at=collected, is_demo=data.is_demo)
        db.add(company)
        db.flush()
    else:
        company = match.company
        for attr, val in (("state", data.state), ("city", data.city), ("address", data.address),
                          ("postal_code", data.postal_code), ("website", website), ("domain", domain),
                          ("email", normalize_email(data.email)), ("phone", data.phone), ("phone_normalized", phone_n),
                          ("linkedin_url", data.linkedin_url), ("registration_number", data.registration_number),
                          ("registration_authority", data.registration_authority), ("country_code", cc)):
            if val and not getattr(company, attr):
                setattr(company, attr, val)
        if data.description and not company.description:
            company.description = data.description[:4000]
        company.last_seen_at = max(filter(None, [company.last_seen_at, collected]))
        if clean_text(data.name) != company.name:
            add_alias(db, company, data.name, source_id=source.id)
    for a in data.aliases:
        add_alias(db, company, a, "trade_name", source.id)

    if data.address and not any((l.address or "").lower() == data.address.lower() for l in company.locations):
        db.add(CompanyLocation(company_id=company.id, location_type="headquarters" if created else "other",
                               address=data.address, city=data.city, state=data.state, postal_code=data.postal_code,
                               country_code=cc, phone=data.phone, is_primary=created, source_id=source.id,
                               source_url=data.source_url))

    # --- classification
    mids = material_ids(db)
    result = ClassificationResult()
    methods: dict = {}
    if data.classification_text:
        result = classify_text(data.classification_text)
        mode = s.ai_classification_mode
        if use_ai and (mode == "always" or (mode == "fallback" and result.inconclusive)) and ai_classifier.ai_available(db):
            ai_result, _rej = ai_classifier.classify_with_ai(db, data.classification_text)
            result, methods = ai_classifier.merge_results(result, ai_result)
    # explicit materials supplied by the source (CSV columns, trade data)
    from app.services.classifier import MaterialFinding, PriceFinding, Spec, BusinessFinding

    for m in data.materials:
        if m.polymer not in mids:
            continue
        f = MaterialFinding(polymer=m.polymer,
                            grade_category=m.grade_category if m.grade_category in E.GRADE_CATEGORIES else "unknown",
                            application=m.application if m.application in E.APPLICATIONS else "unknown",
                            relationship=m.relationship if m.relationship in E.RELATIONSHIPS else "unknown",
                            form=m.form if m.form in E.MATERIAL_FORMS else None, evidence=m.evidence, confidence=0.75,
                            available_quantity=m.available_quantity, required_quantity=m.required_quantity,
                            quantity_unit=m.quantity_unit)
        sp = Spec(evidence=m.evidence, grade_number=m.grade_number, brand=m.brand, mfi=m.mfi, density=m.density,
                  colour=m.colour, form=f.form)
        if sp.has_values():
            f.specs.append(sp)
        result.materials.append(f)
        methods[f.key] = explicit_method
        if m.price and m.currency and m.price_unit:
            result.prices.append(PriceFinding(m.polymer, m.price, m.currency[:3].upper(), m.price_unit, None, m.evidence))
    for t in data.company_types:
        if t in E.COMPANY_TYPES and t not in {b.category for b in result.business_types}:
            result.business_types.append(BusinessFinding(t, data.company_type_evidence or f"Listed as {t} by {source.name}", 0.7))
            methods[("bt", t)] = explicit_method

    added = _apply_classification(db, company, result, methods, source, raw, data.source_url, mids, created, data.is_demo)

    # --- contacts
    n_contacts = 0
    for ci in data.contacts:
        n_contacts += int(upsert_contact(db, company, ci, source, prefix, data.is_demo))
    if not company.email:
        gen = [c for c in company.contacts if c.contact_type == "general" and c.email_normalized]
        gen.sort(key=lambda c: (company.domain is None or not c.email_normalized.endswith("@" + company.domain)))
        if gen:
            company.email = gen[0].email_normalized
    if not company.phone:
        ph = next((c for c in company.contacts if c.contact_type == "general" and c.phone), None)
        if ph:
            company.phone, company.phone_normalized = ph.phone, ph.phone_normalized

    # --- traceability
    db.flush()
    exists = db.scalar(select(CompanySourceRecord.id).where(
        CompanySourceRecord.company_id == company.id, CompanySourceRecord.source_id == source.id,
        CompanySourceRecord.raw_record_id == (raw.id if raw else None)))
    if not exists or raw is None:
        db.add(CompanySourceRecord(company_id=company.id, source_id=source.id, raw_record_id=raw.id if raw else None,
                                   source_url=data.source_url, external_id=data.external_id,
                                   extracted_data=data.model_dump(mode="json", exclude={"classification_text"}),
                                   match_method=match.method, match_score=match.score, collected_at=collected))

    dups = record_duplicate_candidates(db, company, match.possible) if match.possible else 0
    db.flush()
    db.refresh(company)
    score_company(db, company)
    if created:
        create_alert(db, "new_company", f"New company discovered: {company.name} ({cc or 'country unknown'}) via {source.name}",
                     entity_type="company", entity_id=str(company.id),
                     payload={"score": company.lead_score, "source": source.key}, deliver=False)
    if raw is not None:
        raw.processing_status, raw.processed_at = "processed", now
    return IngestOutcome(company_id=str(company.id), created=created, match_method=match.method, materials_added=added,
                         contacts_added=n_contacts, duplicates_flagged=dups)


# ------------------------------------------------------------------ shipments
def classify_shipment_material(description: str | None, hs_code: str | None) -> tuple[str | None, str | None, str | None]:
    """Returns (material_code, inference, grade_category). Description wins over HS code."""
    grade = None
    if description:
        polys = [p for p, _, _ in find_polymers(description)]
        grades = [g for g, _ in _matches("grades", description)]
        grade = grades[0] if grades else None
        specific = [p for p in polys if p not in ("PE_OTHER",)]
        if specific:
            # most frequently named polymer
            return max(set(specific), key=specific.count), "description", grade
    hs6 = (hs_code or "").replace(".", "").strip()[:6]
    if hs6 in HS_MATERIAL_MAP:
        code, ambiguous = HS_MATERIAL_MAP[hs6]
        return code, "ambiguous_hs" if ambiguous else "hs_code", grade
    return None, None, grade


def _trade_party(db: Session, source: Source, name: str | None, address: str | None, country: str | None, role: str,
                 material_code: str | None, grade: str | None, evidence: str, ship_date: date | None,
                 raw: RawRecord | None, is_demo: bool) -> Company | None:
    if not name or len(name.strip()) < 3:
        return None
    rel = "historical_buyer" if role == "importer" else "historical_seller"
    mats = []
    if material_code:
        mats.append(MaterialInput(polymer=material_code, grade_category=grade or "unknown", relationship=rel,
                                  evidence=evidence[:900]))
    out = ingest_company(db, source, CompanyInput(
        name=name, country=country, address=address, company_types=[role],
        company_type_evidence=f"{role.title()} of record on shipment: {evidence[:300]}", materials=mats,
        collected_at=datetime.combine(ship_date, datetime.min.time(), tzinfo=timezone.utc) if ship_date else None,
        is_demo=is_demo), raw=raw, use_ai=False, explicit_method="trade_data", allow_unique_exact_name=True)
    return db.get(Company, out.company_id)


def ingest_shipment(db: Session, source: Source, data: ShipmentInput, raw: RawRecord | None = None) -> tuple[Shipment, bool]:
    ext = data.external_id or content_hash(data.model_dump(mode="json"))[:40]
    existing = db.scalar(select(Shipment).where(Shipment.source_id == source.id, Shipment.external_id == ext))
    if existing:
        return existing, False
    mids = material_ids(db)
    mcode, inference, grade = classify_shipment_material(data.product_description, data.hs_code)
    evidence = clean_text(f"{data.shipment_date or ''} HS {data.hs_code or '-'}: {data.product_description or ''}")
    imp_cc = resolve_country(db, data.importer_country or data.destination_country)
    exp_cc = resolve_country(db, data.exporter_country or data.origin_country)
    importer = _trade_party(db, source, data.importer_name, data.importer_address, imp_cc, "importer", mcode, grade,
                            evidence, data.shipment_date, raw, data.is_demo)
    exporter = _trade_party(db, source, data.exporter_name, data.exporter_address, exp_cc, "exporter", mcode, grade,
                            evidence, data.shipment_date, raw, data.is_demo)
    sh = Shipment(source_id=source.id, external_id=ext, shipment_date=data.shipment_date,
                  importer_company_id=importer.id if importer else None,
                  exporter_company_id=exporter.id if exporter else None,
                  importer_name_raw=data.importer_name, exporter_name_raw=data.exporter_name,
                  importer_country=imp_cc, exporter_country=exp_cc,
                  origin_country=resolve_country(db, data.origin_country) or exp_cc,
                  destination_country=resolve_country(db, data.destination_country) or imp_cc,
                  port_of_loading=data.port_of_loading, port_of_discharge=data.port_of_discharge,
                  hs_code=(data.hs_code or "").replace(".", "")[:12] or None, product_description=data.product_description,
                  material_id=mids.get(mcode) if mcode else None, material_inference=inference, grade_category=grade,
                  quantity=data.quantity, quantity_unit=data.quantity_unit, weight_kg=data.weight_kg, value=data.value,
                  currency=data.currency, bill_of_lading=data.bill_of_lading, source_url=data.source_url,
                  raw_record_id=raw.id if raw else None, is_demo=data.is_demo)
    db.add(sh)
    db.flush()
    for c in (importer, exporter):
        if c:
            score_company(db, c)
    if raw is not None:
        raw.processing_status, raw.processed_at = "processed", datetime.now(timezone.utc)
    return sh, True


def upsert_trade_statistic(db: Session, source: Source, **kw) -> bool:
    existing = db.scalar(select(TradeStatistic).where(
        TradeStatistic.source_id == source.id, TradeStatistic.reporter_country == kw["reporter_country"],
        TradeStatistic.partner_country == kw["partner_country"], TradeStatistic.flow == kw["flow"],
        TradeStatistic.hs_code == kw["hs_code"], TradeStatistic.period == kw["period"]))
    if existing:
        for k, v in kw.items():
            setattr(existing, k, v)
        existing.collected_at = datetime.now(timezone.utc)
        return False
    db.add(TradeStatistic(source_id=source.id, **kw))
    return True
