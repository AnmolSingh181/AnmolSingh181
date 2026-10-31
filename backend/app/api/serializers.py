"""Model -> JSON dicts for API responses."""
from __future__ import annotations

from app.models import (Company, CompanyClassification, CompanyMaterial, Contact, Lead, MaterialSpecification, Shipment,
                        Source)


def _iso(d):
    return d.isoformat() if d else None


def spec_out(s: MaterialSpecification) -> dict:
    return {"id": s.id, "grade_number": s.grade_number, "brand": s.brand, "manufacturer_name": s.manufacturer_name,
            "mfi": s.mfi, "mfi_conditions": s.mfi_conditions, "density": s.density, "colour": s.colour, "form": s.form,
            "origin_country": s.origin_country, "packaging": s.packaging, "evidence_text": s.evidence_text,
            "evidence_url": s.evidence_url, "method": s.method}


def material_out(m: CompanyMaterial, with_specs: bool = True) -> dict:
    d = {"id": m.id, "polymer": m.material.code if m.material else None, "grade_category": m.grade_category,
         "application": m.application, "relationship": m.relationship_type, "form": m.form,
         "available_quantity": float(m.available_quantity) if m.available_quantity is not None else None,
         "required_quantity": float(m.required_quantity) if m.required_quantity is not None else None,
         "quantity_unit": m.quantity_unit, "quantity_period": m.quantity_period, "method": m.method,
         "confidence": round(m.confidence, 2), "evidence_text": m.evidence_text, "evidence_url": m.evidence_url,
         "review_status": m.review_status, "is_current": m.is_current, "first_seen_at": _iso(m.first_seen_at),
         "last_seen_at": _iso(m.last_seen_at)}
    if with_specs:
        d["specifications"] = [spec_out(s) for s in m.specifications]
    return d


def classification_out(c: CompanyClassification) -> dict:
    return {"id": c.id, "category": c.category, "method": c.method, "confidence": round(c.confidence, 2),
            "evidence_text": c.evidence_text, "evidence_url": c.evidence_url, "review_status": c.review_status}


def contact_out(c: Contact, include_company: bool = False) -> dict:
    d = {"id": str(c.id), "company_id": str(c.company_id), "contact_type": c.contact_type, "full_name": c.full_name,
         "job_title": c.job_title, "department": c.department, "decision_role": c.decision_role, "email": c.email,
         "phone": c.phone, "linkedin_url": c.linkedin_url, "country_code": c.country_code, "source_url": c.source_url,
         "evidence_text": c.evidence_text, "verification_status": c.verification_status,
         "last_verified_at": _iso(c.last_verified_at), "is_opted_out": c.is_opted_out, "is_demo": c.is_demo,
         "created_at": _iso(c.created_at)}
    if include_company and c.company:
        d["company_name"] = c.company.name
        d["company_country"] = c.company.country_code
    return d


def company_summary(c: Company) -> dict:
    mats = [m for m in c.materials if m.is_current and m.review_status != "rejected"]
    contacts = [x for x in c.contacts if not x.is_opted_out and x.verification_status != "invalid"]
    return {
        "id": str(c.id), "public_ref": c.public_ref, "name": c.name, "country_code": c.country_code, "city": c.city,
        "website": c.website, "email": c.email, "phone": c.phone, "lead_score": c.lead_score, "lead_tier": c.lead_tier,
        "company_types": sorted({x.category for x in c.classifications if x.review_status != "rejected"}),
        "polymers": sorted({m.material.code for m in mats if m.material}),
        "grades": sorted({m.grade_category for m in mats if m.grade_category != "unknown"}),
        "applications": sorted({m.application for m in mats if m.application != "unknown"}),
        "relationships": sorted({m.relationship_type for m in mats if m.relationship_type != "unknown"}),
        "contact_count": len(contacts),
        "decision_makers": sum(1 for x in contacts if x.decision_role != "unknown_authority"),
        "first_discovered_at": _iso(c.first_discovered_at), "last_seen_at": _iso(c.last_seen_at),
        "last_verified_at": _iso(c.last_verified_at), "is_demo": c.is_demo,
    }


def company_detail(c: Company) -> dict:
    d = company_summary(c)
    d.update({
        "normalized_name": c.normalized_name, "state": c.state, "address": c.address, "postal_code": c.postal_code,
        "domain": c.domain, "linkedin_url": c.linkedin_url, "description": c.description,
        "registration_number": c.registration_number, "registration_authority": c.registration_authority,
        "status": c.status, "lead_score_breakdown": c.lead_score_breakdown,
        "lead_score_updated_at": _iso(c.lead_score_updated_at), "website_last_crawled_at": _iso(c.website_last_crawled_at),
        "aliases": [{"alias": a.alias, "type": a.alias_type} for a in c.aliases],
        "locations": [{"id": l.id, "type": l.location_type, "address": l.address, "city": l.city, "state": l.state,
                       "country_code": l.country_code, "is_primary": l.is_primary, "source_url": l.source_url}
                      for l in c.locations],
        "classifications": [classification_out(x) for x in c.classifications],
        "materials": [material_out(m) for m in sorted(c.materials, key=lambda m: (not m.is_current, -m.confidence))],
        "contacts": [contact_out(x) for x in c.contacts if not x.is_opted_out],
        "notes": [{"id": n.id, "body": n.body, "created_at": _iso(n.created_at), "user_id": str(n.user_id) if n.user_id else None}
                  for n in sorted(c.notes, key=lambda n: n.created_at, reverse=True)],
        "source_records": [{"id": s.id, "source": s.source.name if s.source else None,
                            "source_key": s.source.key if s.source else None, "source_url": s.source_url,
                            "match_method": s.match_method, "match_score": s.match_score,
                            "collected_at": _iso(s.collected_at), "raw_record_id": s.raw_record_id}
                           for s in sorted(c.source_records, key=lambda s: s.collected_at, reverse=True)],
    })
    return d


def shipment_out(s: Shipment) -> dict:
    return {"id": s.id, "source": s.source.name if s.source else None, "external_id": s.external_id,
            "shipment_date": _iso(s.shipment_date), "importer_company_id": str(s.importer_company_id) if s.importer_company_id else None,
            "exporter_company_id": str(s.exporter_company_id) if s.exporter_company_id else None,
            "importer_name": s.importer_name_raw, "exporter_name": s.exporter_name_raw,
            "importer_country": s.importer_country, "exporter_country": s.exporter_country,
            "origin_country": s.origin_country, "destination_country": s.destination_country,
            "port_of_loading": s.port_of_loading, "port_of_discharge": s.port_of_discharge, "hs_code": s.hs_code,
            "product_description": s.product_description, "material": s.material.code if s.material else None,
            "material_inference": s.material_inference, "grade_category": s.grade_category,
            "quantity": float(s.quantity) if s.quantity is not None else None, "quantity_unit": s.quantity_unit,
            "weight_kg": float(s.weight_kg) if s.weight_kg is not None else None,
            "value": float(s.value) if s.value is not None else None, "currency": s.currency,
            "source_url": s.source_url, "collected_at": _iso(s.collected_at), "is_demo": s.is_demo}


def lead_out(l: Lead) -> dict:
    return {"id": str(l.id), "company_id": str(l.company_id), "company": company_summary(l.company) if l.company else None,
            "owner_user_id": str(l.owner_user_id), "lead_type": l.lead_type, "stage": l.stage, "priority": l.priority,
            "interested_materials": l.interested_materials, "communication_status": l.communication_status,
            "notes": l.notes, "last_contacted_at": _iso(l.last_contacted_at), "next_follow_up_at": _iso(l.next_follow_up_at),
            "created_at": _iso(l.created_at), "updated_at": _iso(l.updated_at),
            "activities": [{"id": a.id, "type": a.activity_type, "summary": a.summary, "created_at": _iso(a.created_at)}
                           for a in l.activities[:50]]}


def source_out(s: Source) -> dict:
    return {"id": s.id, "key": s.key, "name": s.name, "source_type": s.source_type, "access_method": s.access_method,
            "base_url": s.base_url, "status": s.status, "enabled": s.enabled, "requires_credentials": s.requires_credentials,
            "credential_env_vars": s.credential_env_vars, "terms_notes": s.terms_notes, "pricing_notes": s.pricing_notes,
            "config": {k: v for k, v in (s.config or {}).items() if "key" not in k.lower() and "secret" not in k.lower()},
            "refresh_interval_days": s.refresh_interval_days, "last_run_at": _iso(s.last_run_at),
            "last_success_at": _iso(s.last_success_at), "last_error": s.last_error, "total_records": s.total_records}
