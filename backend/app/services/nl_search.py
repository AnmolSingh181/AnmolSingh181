"""Natural-language -> structured CompanyFilters. Results always come from the database via search_companies;
the parser (rules, optionally OpenAI with a strict schema) only produces filters, never results."""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import enums as E
from app.config import get_settings
from app.models import ApiUsage, Country
from app.services.classifier import _matches, find_polymers
from app.services.search import VERIFIED, CompanyFilters

log = logging.getLogger(__name__)

SELLER_WORDS = r"\b(suppliers?|sellers?|selling|sell|offering|vendors?|stockists?|exporters?|exporting|providers?|sources? of)\b"
BUYER_WORDS = r"\b(buyers?|buying|purchasers?|purchasing|importers?|importing|consumers?|requir\w+|needs?|wanted)\b"
TYPE_WORDS = {
    "trader": r"\btrad(?:ers?|ing companies|ing firms|ing houses?)\b",
    "distributor": r"\bdistributors?\b",
    "recycler": r"\brecyclers?\b|\brecycling (?:companies|firms|plants)\b",
    "manufacturer": r"\b(?:manufacturers?|producers?|petrochemical companies)\b",
    "converter": r"\bconverters?\b|\b(?:film|bag|pipe) (?:makers|manufacturers)\b",
    "processor": r"\b(?:processors?|compounders?|reprocessors?)\b",
    "scrap_aggregator": r"\bscrap (?:dealers?|aggregators?|collectors?)\b",
}


def _countries(db: Session, text: str) -> list[str]:
    found = []
    tl = f" {text.lower()} "
    for c in db.scalars(select(Country)).all():
        for n in [c.name] + list(c.aliases or []):
            if len(n) <= 3 and n.upper() == n:  # short codes like UAE, USA, KSA: case-sensitive token
                if re.search(rf"(?<![A-Za-z]){re.escape(n)}(?![A-Za-z])", text):
                    found.append(c.code)
                    break
            elif re.search(rf"\b{re.escape(n.lower())}\b", tl):
                found.append(c.code)
                break
    return sorted(set(found))


def parse_rules(db: Session, query: str) -> tuple[CompanyFilters, list[str]]:
    f = CompanyFilters()
    notes = []
    polys = sorted({p for p, _, _ in find_polymers(query)} - {"PE_OTHER"})
    if polys:
        f.polymers = polys
        notes.append(f"polymer: {', '.join(polys)}")
        if len(polys) > 1 and re.search(r"\bboth\b|\band\b", query, re.I) and re.search(r"\bboth\b|dealing in", query, re.I):
            f.polymer_match = "all"
            notes.append("must deal in all listed polymers")
    grades = [g for g, _ in _matches("grades", query)]
    # "recyclers" is a company type, not a grade
    if "recycled" in grades and not re.search(r"\brecycled\b|\bPCR\b|\bPIR\b|\brecycl\w+ (?:granules|pellets|flakes|material)",
                                               query, re.I):
        grades.remove("recycled")
    if grades:
        f.grades = grades
        notes.append(f"grade: {', '.join(grades)}")
    apps = [a for a, _ in _matches("applications", query)]
    if not apps and re.search(r"\bfilm\b", query, re.I):
        apps = ["film"]
    if apps:
        f.applications = apps
        notes.append(f"application: {', '.join(apps)}")
    rels = []
    if re.search(SELLER_WORDS, query, re.I):
        rels.append("seller")
    if re.search(BUYER_WORDS, query, re.I):
        rels.append("buyer")
    if len(rels) == 1:
        f.relationships = rels
        notes.append(f"relationship: {rels[0]}")
    if re.search(r"\bimport(?:ers?|ing)\b", query, re.I):
        f.trade_roles.append("importer")
        notes.append("trade role: importer (classification or shipment records)")
    if re.search(r"\bexport(?:ers?|ing)\b", query, re.I):
        f.trade_roles.append("exporter")
        notes.append("trade role: exporter (classification or shipment records)")
    for t, rx in TYPE_WORDS.items():
        if re.search(rx, query, re.I):
            f.company_types.append(t)
    if f.company_types:
        notes.append(f"company type: {', '.join(f.company_types)}")
        if "manufacturer" in f.company_types and f.relationships == ["seller"]:
            f.relationships = []  # "manufacturers" already implies the role
    cc = _countries(db, query)
    if cc:
        f.countries = cc
        notes.append(f"country: {', '.join(cc)}")
    m = re.search(r"\b(procurement|purchas\w*|sourcing|sales|export|import|commercial|business development|managing director)"
                  r"\s+(?:manager|director|head|officer|contacts?)", query, re.I)
    if m:
        f.contact_title = "purchas" if m.group(1).lower().startswith("purchas") else m.group(1).lower()
        notes.append(f"contact title contains '{f.contact_title}'")
    elif re.search(r"\bdecision[\s-]?makers?\b", query, re.I):
        f.has_decision_maker = True
        notes.append("has a decision-maker contact (title-based)")
    if re.search(r"\bverified\b", query, re.I):
        f.contact_verification = VERIFIED
        notes.append("verified contacts only")
    if re.search(r"\bemails?\b", query, re.I):
        f.has_email = True
    if re.search(r"\bphones?\b|\btelephone\b", query, re.I):
        f.has_phone = True
    if re.search(r"\bcontacts?\b|\bcontact (?:details|information|info)\b", query, re.I) and not f.contact_title:
        f.has_contacts = True
        notes.append("has contact information")
    if re.search(r"\bhigh[\s-]priority\b|\btop leads?\b", query, re.I):
        f.min_score = 80
        notes.append("lead score >= 80")
    return f, notes


AI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["polymers", "polymer_match", "grades", "applications", "relationships", "company_types", "trade_roles",
                 "countries", "contact_title", "has_contacts", "min_score"],
    "properties": {
        "polymers": {"type": "array", "items": {"type": "string", "enum": ["LDPE", "LLDPE", "HDPE", "PE_SCRAP"]}},
        "polymer_match": {"type": "string", "enum": ["any", "all"]},
        "grades": {"type": "array", "items": {"type": "string", "enum": E.GRADE_CATEGORIES}},
        "applications": {"type": "array", "items": {"type": "string", "enum": E.APPLICATIONS}},
        "relationships": {"type": "array", "items": {"type": "string", "enum": ["buyer", "seller", "both", "manufacturer"]}},
        "company_types": {"type": "array", "items": {"type": "string", "enum": E.COMPANY_TYPES}},
        "trade_roles": {"type": "array", "items": {"type": "string", "enum": ["importer", "exporter"]}},
        "countries": {"type": "array", "items": {"type": "string", "description": "ISO 3166-1 alpha-2"}},
        "contact_title": {"type": ["string", "null"]},
        "has_contacts": {"type": ["boolean", "null"]},
        "min_score": {"type": ["integer", "null"]},
    },
}


def parse_ai(db: Session, query: str) -> CompanyFilters | None:
    s = get_settings()
    if not s.openai_api_key:
        return None
    from app.services.ai_classifier import PRICE_IN, PRICE_OUT, month_to_date_cost

    if month_to_date_cost(db) >= s.ai_monthly_budget_usd:
        return None
    try:
        from openai import OpenAI

        resp = OpenAI(api_key=s.openai_api_key).chat.completions.create(
            model=s.openai_model,
            messages=[{"role": "system", "content": "Translate a plastics B2B search request into database filters. "
                       "Only set filters the user explicitly asked for. Countries as ISO2 codes."},
                      {"role": "user", "content": query}],
            response_format={"type": "json_schema", "json_schema": {"name": "filters", "strict": True, "schema": AI_SCHEMA}})
        data = json.loads(resp.choices[0].message.content or "{}")
        u = resp.usage
        db.add(ApiUsage(provider="openai", operation="nl_search", units=(u.prompt_tokens + u.completion_tokens),
                        input_tokens=u.prompt_tokens, output_tokens=u.completion_tokens,
                        estimated_cost_usd=u.prompt_tokens / 1e6 * PRICE_IN + u.completion_tokens / 1e6 * PRICE_OUT))
    except Exception as exc:
        log.warning("AI query parse failed: %s", exc)
        return None
    valid_cc = {c.code for c in db.scalars(select(Country)).all()}
    data["countries"] = [c.upper() for c in data.get("countries", []) if c.upper() in valid_cc]
    data = {k: v for k, v in data.items() if v not in (None, [])}
    try:
        return CompanyFilters(**data)
    except Exception:
        return None


def parse_query(db: Session, query: str, use_ai: bool = True) -> tuple[CompanyFilters, list[str], str]:
    rules, notes = parse_rules(db, query)
    if use_ai:
        ai = parse_ai(db, query)
        if ai is not None:
            return ai, [f"{k}: {v}" for k, v in ai.model_dump(exclude_defaults=True).items()], "ai"
    return rules, notes, "rules"
