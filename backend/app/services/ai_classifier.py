"""OpenAI structured extraction with strict evidence validation.

The model must quote evidence verbatim. Every returned item is checked against the source text:
- evidence_quote must literally occur in the source (whitespace/case-insensitive)
- the polymer must be named inside the quote (checked with the rule dictionary)
- numeric specs (MFI, density, quantities) and grade numbers must literally appear in the quote
- buyer/seller relationships without an explicit intent cue in the quote are downgraded to needs_review
Anything failing validation is dropped (or the field nulled) and logged - never stored as fact.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import enums as E
from app.config import get_settings
from app.models import ApiUsage
from app.services.classifier import (BusinessFinding, ClassificationResult, MaterialFinding, Spec, _matches,
                                     find_polymers)

log = logging.getLogger(__name__)

# USD per 1M tokens; override with env if pricing changes
import os

PRICE_IN = float(os.environ.get("OPENAI_INPUT_PRICE_PER_M", "0.25"))
PRICE_OUT = float(os.environ.get("OPENAI_OUTPUT_PRICE_PER_M", "2.00"))

POLYMERS = ["LDPE", "LLDPE", "HDPE", "PE_SCRAP", "PE_OTHER"]


def _nullable(t: str | dict) -> dict:
    if isinstance(t, dict):
        return {"anyOf": [t, {"type": "null"}]}
    return {"type": [t, "null"]}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["materials", "business_types"],
    "properties": {
        "materials": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["polymer", "grade_category", "application", "relationship", "form", "evidence_quote",
                             "mfi", "density", "grade_number", "brand", "colour", "available_quantity_mt",
                             "required_quantity_mt"],
                "properties": {
                    "polymer": {"type": "string", "enum": POLYMERS},
                    "grade_category": {"type": "string", "enum": E.GRADE_CATEGORIES},
                    "application": {"type": "string", "enum": E.APPLICATIONS},
                    "relationship": {"type": "string", "enum": [r for r in E.RELATIONSHIPS if not r.startswith("historical")]},
                    "form": _nullable({"type": "string", "enum": E.MATERIAL_FORMS}),
                    "evidence_quote": {"type": "string"},
                    "mfi": _nullable("number"),
                    "density": _nullable("number"),
                    "grade_number": _nullable("string"),
                    "brand": _nullable("string"),
                    "colour": _nullable("string"),
                    "available_quantity_mt": _nullable("number"),
                    "required_quantity_mt": _nullable("number"),
                },
            },
        },
        "business_types": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "evidence_quote"],
                "properties": {
                    "category": {"type": "string", "enum": E.COMPANY_TYPES},
                    "evidence_quote": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You extract plastics-trading facts from company web pages and trade listings.
Polymers: LDPE, LLDPE (linear low-density PE), HDPE, PE_SCRAP (PE waste/scrap where polymer is not specified), PE_OTHER.
Terminology: 'non-prime' = non_prime_unspecified unless the text says near-prime or off-grade; 'off-spec' = off_spec;
'wide-spec' = near_prime; 'reprocessed granules'/'repro' = reprocessed; PCR = pcr (post-consumer); PIR = pir (post-industrial).
Business types: 'manufacturer'/'producer' ONLY for resin/polymer producers. Companies making bags, films, pipes, bottles from
resin are 'converter'. Compounders/reprocessors are 'processor'.
Relationship: seller if the company offers/supplies/exports the material, buyer if it buys/purchases/requires it,
manufacturer if it produces the resin. Use 'unknown' if the text does not explicitly say.
STRICT RULES: copy evidence_quote VERBATIM from the text (one or two sentences). Never guess. Use null for any value
(mfi, density, grade_number, brand, colour, quantities) that is not written in the quote. Do not convert units.
Return an empty list when nothing relevant is present."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _num_in(value: float, quote: str) -> bool:
    nums = re.findall(r"\d+(?:[.,]\d+)?", quote.replace(",", "") if value >= 1000 else quote)
    for n in nums:
        try:
            if abs(float(n.replace(",", ".")) - value) < 1e-6:
                return True
        except ValueError:
            continue
    return False


def month_to_date_cost(db: Session) -> float:
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    v = db.scalar(select(func.coalesce(func.sum(ApiUsage.estimated_cost_usd), 0)).where(
        ApiUsage.provider == "openai", ApiUsage.created_at >= start))
    return float(v or 0)


def ai_available(db: Session | None = None) -> bool:
    s = get_settings()
    if not s.openai_api_key or s.ai_classification_mode == "off":
        return False
    if db is not None and month_to_date_cost(db) >= s.ai_monthly_budget_usd:
        log.warning("OpenAI monthly budget reached; AI classification skipped")
        return False
    return True


def validate_ai_output(data: dict, source_text: str) -> tuple[ClassificationResult, list[str]]:
    """Pure function: turn model JSON into validated findings. Returns (result, rejection_reasons)."""
    src = _norm(source_text)
    rejected: list[str] = []
    out = ClassificationResult()
    for item in data.get("materials", []) or []:
        quote = (item.get("evidence_quote") or "").strip()
        nq = _norm(quote)
        if len(nq) < 8 or nq not in src:
            rejected.append(f"material quote not found in source: {quote[:80]!r}")
            continue
        poly = item.get("polymer")
        if poly not in POLYMERS:
            rejected.append(f"invalid polymer {poly}")
            continue
        named = {p for p, _, _ in find_polymers(quote)}
        if poly not in named and not (poly in ("PE_SCRAP", "PE_OTHER") and re.search(r"poly\s?ethylene|\bPE\b", quote, re.I)):
            rejected.append(f"polymer {poly} not named in quote")
            continue
        grade = item.get("grade_category") if item.get("grade_category") in E.GRADE_CATEGORIES else "unknown"
        app = item.get("application") if item.get("application") in E.APPLICATIONS else "unknown"
        rel = item.get("relationship") if item.get("relationship") in E.RELATIONSHIPS else "unknown"
        review = "auto"
        if rel in ("buyer", "seller", "both") and not _matches("intent", quote):
            review = "needs_review"
        if grade == "non_prime_unspecified":
            review = "needs_review"
        spec = Spec(evidence=quote)
        for field, lo, hi in (("mfi", 0, 200), ("density", 0.85, 1.0)):
            v = item.get(field)
            if v is not None:
                if isinstance(v, (int, float)) and lo <= v < hi and _num_in(float(v), quote):
                    setattr(spec, field, float(v))
                else:
                    rejected.append(f"{field}={v} not supported by quote")
        for field in ("grade_number", "brand", "colour"):
            v = item.get(field)
            if v:
                if _norm(str(v)) in nq:
                    setattr(spec, field, str(v)[:60])
                else:
                    rejected.append(f"{field}={v!r} not in quote")
        form = item.get("form") if item.get("form") in E.MATERIAL_FORMS else None
        spec.form = form
        f = MaterialFinding(polymer=poly, grade_category=grade, application=app, relationship=rel, form=form,
                            evidence=quote, confidence=0.7 if review == "auto" else 0.5, review_status=review)
        for src_field, dst in (("available_quantity_mt", "available_quantity"), ("required_quantity_mt", "required_quantity")):
            v = item.get(src_field)
            if v is not None:
                if isinstance(v, (int, float)) and v > 0 and _num_in(float(v), quote):
                    setattr(f, dst, float(v))
                    f.quantity_unit = "MT"
                else:
                    rejected.append(f"{src_field}={v} not supported by quote")
        if spec.has_values():
            f.specs.append(spec)
        out.materials.append(f)
    for item in data.get("business_types", []) or []:
        quote = (item.get("evidence_quote") or "").strip()
        if item.get("category") not in E.COMPANY_TYPES:
            continue
        if len(_norm(quote)) < 8 or _norm(quote) not in src:
            rejected.append(f"business quote not found: {quote[:80]!r}")
            continue
        out.business_types.append(BusinessFinding(item["category"], quote, 0.65))
    return out, rejected


def classify_with_ai(db: Session, text: str) -> tuple[ClassificationResult | None, list[str]]:
    if not ai_available(db):
        return None, ["ai unavailable"]
    s = get_settings()
    from openai import OpenAI  # imported lazily so the platform runs without the package configured

    client = OpenAI(api_key=s.openai_api_key)
    snippet = text[: s.ai_max_input_chars]
    try:
        resp = client.chat.completions.create(
            model=s.openai_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": snippet}],
            response_format={"type": "json_schema", "json_schema": {"name": "plastics_extraction", "strict": True,
                                                                     "schema": SCHEMA}},
        )
    except Exception as exc:  # network, auth, quota - never break ingestion
        log.warning("OpenAI call failed: %s", exc)
        return None, [f"openai error: {exc}"]
    usage = getattr(resp, "usage", None)
    tin = getattr(usage, "prompt_tokens", 0) or 0
    tout = getattr(usage, "completion_tokens", 0) or 0
    db.add(ApiUsage(provider="openai", operation="classify", units=tin + tout, input_tokens=tin, output_tokens=tout,
                    estimated_cost_usd=round(tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT, 6)))
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return None, ["invalid JSON from model"]
    result, rejected = validate_ai_output(data, snippet)
    if rejected:
        log.info("AI output items rejected: %s", rejected[:10])
    return result, rejected


def merge_results(rule: ClassificationResult, ai: ClassificationResult | None) -> tuple[ClassificationResult, dict]:
    """Rules first; AI adds rows the rules missed and fills 'unknown' fields only where its quote supports them."""
    methods: dict = {}
    if ai is None:
        return rule, methods
    keys = {m.key for m in rule.materials}
    for m in ai.materials:
        if m.key in keys:
            continue
        # if rules have the same polymer with unknown grade/relationship, AI's more specific row supersedes it
        rule.materials = [r for r in rule.materials
                          if not (r.polymer == m.polymer and r.grade_category == "unknown" and r.relationship == "unknown"
                                  and r.application == "unknown")]
        rule.materials.append(m)
        methods[m.key] = "ai"
    have = {b.category for b in rule.business_types}
    for b in ai.business_types:
        if b.category not in have:
            rule.business_types.append(b)
            methods[("bt", b.category)] = "ai"
    return rule, methods
