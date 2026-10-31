"""Rule-based material / business classifier.

Principles
- Only explicit statements are captured. Every finding keeps an evidence snippet copied from the source text.
- Specifications (MFI, density, grade number, quantity, price) are extracted only when the literal value is present.
- Anything ambiguous is returned with review_status='needs_review' or relationship='unknown'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.data.reference import COUNTRIES
from app.services.dictionary import compiled

WINDOW = 160  # chars of context on each side of a polymer mention used for grade/intent detection

BRANDS = [
    "SABIC", "Borouge", "ExxonMobil", "Exxon", "Dow", "Reliance", "Sinopec", "PetroChina", "Qatar Petrochemical", "QAPCO",
    "Lotte", "LG Chem", "Braskem", "LyondellBasell", "Ineos", "INEOS", "Chevron Phillips", "Formosa", "Hanwha", "SCG",
    "Tasnee", "Sipchem", "Haldia", "GAIL", "OPaL", "IRPC", "PTT", "Borealis", "TotalEnergies", "Total", "Nova Chemicals",
    "Westlake", "Equate", "Petro Rabigh", "Kazanorgsintez", "Sibur", "Long Son", "Hyosung", "Daelim", "Lyondell",
]
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")\b")
_BRAND_GRADE_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")\s+(?:(?:m?LLDPE|LDPE|HDPE)\s+)?"
    r"(?:grade\s+)?([A-Z]{0,4}[\s-]?\d[A-Z0-9\-\.]{1,12})\b"
)
_GRADE_NO_RE = re.compile(r"\bgrade\s*(?:no\.?|number|code|#|:)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\./]{2,20})", re.IGNORECASE)
_MFI_RE = re.compile(
    r"\b(?:MFI|MFR|melt\s+(?:flow\s+)?(?:index|rate))\b\s*(?:\(([^)]{0,30})\))?\s*[:=\-–]?\s*(?:of\s+|is\s+|approx\.?\s+|~\s*)?"
    r"(\d{1,3}(?:[.,]\d{1,3})?)\s*(?:g\s*/\s*10\s*min)?\s*(?:\(?\s*@?\s*(\d{3}\s*°?\s*C\s*/\s*\d+(?:\.\d+)?\s*kg)\s*\)?)?",
    re.IGNORECASE,
)
_DENSITY_RE = re.compile(
    r"\bdensity\b\s*(?:\([^)]{0,20}\))?\s*[:=\-–]?\s*(?:of\s+|is\s+|approx\.?\s+|~\s*)?(0[.,]9\d{1,3}|9\d{2})\s*"
    r"(g\s*/\s*cm3|g\s*/\s*cm³|g\s*/\s*cc|kg\s*/\s*m3|kg\s*/\s*m³)?",
    re.IGNORECASE,
)
_DENSITY_UNIT_RE = re.compile(r"\b(0[.,]9\d{1,3})\s*(?:g\s*/\s*(?:cm3|cm³|cc))", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(USD|US\$|EUR|INR|AED|SAR|CNY|RMB|VND|\$|€|₹)\s?(\d{1,3}(?:[,\s]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?:/|per)\s*(MT|metric\s+ton(?:ne)?|ton(?:ne)?|kg|lb)\b(?:\s+(FOB|CIF|CFR|EXW|DAP|DDP|FCA))?",
    re.IGNORECASE,
)
_QTY_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(MT|mts|metric\s+tons?|tons?|tonnes?)\b(?:\s*(?:per|/|a|each)\s*(month|year|week|annum))?",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(r"^.{0,25}?\b(?:per|/|a|each|every)\s*(month|year|week|annum)\b", re.IGNORECASE)
_QTY_AVAILABLE = re.compile(r"\b(available|supply|capacity|stock|offer|production|sell)\b", re.IGNORECASE)
_QTY_REQUIRED = re.compile(r"\b(required|requirement|need|buy|purchase|wanted|looking\s+for|consumption)\b", re.IGNORECASE)
_ORIGIN_RE = re.compile(r"\b(?:origin|country\s+of\s+origin|made\s+in)\s*[:\-]?\s*([A-Z][A-Za-z\.\s]{2,30})", re.IGNORECASE)
_PACKAGING_RE = re.compile(
    r"\b(\d{2}\s*kg\s*(?:bags?|sacks?)|jumbo\s+bags?|big\s+bags?|FIBC|octabins?|gaylords?|bulk\s+(?:bags?|silo|trucks?)|pallets?)\b",
    re.IGNORECASE,
)
_CURRENCY = {"$": "USD", "US$": "USD", "€": "EUR", "₹": "INR", "RMB": "CNY"}
_UNIT = {"metric ton": "MT", "metric tonne": "MT", "ton": "MT", "tonne": "MT", "mt": "MT", "kg": "kg", "lb": "lb"}


@dataclass
class Spec:
    evidence: str
    grade_number: str | None = None
    brand: str | None = None
    mfi: float | None = None
    mfi_conditions: str | None = None
    density: float | None = None
    colour: str | None = None
    form: str | None = None
    origin_country: str | None = None
    packaging: str | None = None

    def has_values(self) -> bool:
        return any(v is not None for k, v in self.__dict__.items() if k != "evidence")


@dataclass
class MaterialFinding:
    polymer: str
    grade_category: str = "unknown"
    application: str = "unknown"
    relationship: str = "unknown"
    form: str | None = None
    evidence: str = ""
    confidence: float = 0.5
    review_status: str = "auto"
    available_quantity: float | None = None
    required_quantity: float | None = None
    quantity_unit: str | None = None
    quantity_period: str | None = None
    specs: list[Spec] = field(default_factory=list)

    @property
    def key(self) -> tuple:
        return (self.polymer, self.grade_category, self.application, self.relationship)


@dataclass
class BusinessFinding:
    category: str
    evidence: str
    confidence: float


@dataclass
class PriceFinding:
    polymer: str | None
    price: float
    currency: str
    unit: str
    incoterm: str | None
    evidence: str


@dataclass
class ClassificationResult:
    materials: list[MaterialFinding] = field(default_factory=list)
    business_types: list[BusinessFinding] = field(default_factory=list)
    prices: list[PriceFinding] = field(default_factory=list)

    @property
    def inconclusive(self) -> bool:
        """True when rules found no polymer, or only 'unknown' grade/relationship everywhere."""
        if not self.materials:
            return True
        return all(m.relationship == "unknown" and m.grade_category == "unknown" for m in self.materials)


def _snippet(text: str, start: int, end: int, pad: int = 120) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    out = text[s:e].strip()
    return ("…" if s > 0 else "") + re.sub(r"\s+", " ", out) + ("…" if e < len(text) else "")


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        for i in range(s, e):
            chars[i] = " "
    return "".join(chars)


def find_polymers(text: str) -> list[tuple[str, int, int]]:
    """Return (polymer_code, start, end) for each mention. LLDPE is matched first and masked."""
    pats = compiled()["polymers"]
    found: list[tuple[str, int, int]] = []
    working = text
    for code in ["LLDPE", "LDPE", "HDPE", "PE_OTHER"]:
        for rx in pats.get(code, []):  # mask after every pattern so overlapping patterns count once
            spans = [(m.start(), m.end()) for m in rx.finditer(working)]
            found.extend((code, a, b) for a, b in spans)
            working = _mask(working, spans)
    for rx in pats.get("PE_SCRAP", []):
        for m in rx.finditer(text):
            found.append(("PE_SCRAP", m.start(), m.end()))
    return sorted(found, key=lambda x: x[1])


def _matches(section: str, text: str) -> list[tuple[str, re.Match]]:
    out = []
    for key, rxs in compiled()[section].items():
        for rx in rxs:
            m = rx.search(text)
            if m:
                out.append((key, m))
                break
    return out


def _parse_number(s: str) -> float:
    s = s.strip().replace(" ", "")
    if "," in s and "." not in s:
        head, _, tail = s.rpartition(",")
        # "0,918" / "2,5" -> decimal comma; "1,200" -> thousands separator
        return float(f"{head}.{tail}") if (len(tail) != 3 or head in ("0", "")) else float(s.replace(",", ""))
    return float(s.replace(",", ""))


def country_from_text(value: str) -> str | None:
    v = value.strip().lower().rstrip(".")
    for code, name, *_rest in COUNTRIES:
        aliases = _rest[5]
        names = [name.lower()] + [a.lower() for a in aliases]
        for n in names:
            if v == n or v.startswith(n + " ") or v.startswith(n + ",") or re.match(rf"^{re.escape(n)}\b", v):
                return code
    return None


def extract_specs(segment: str) -> Spec:
    spec = Spec(evidence=segment)
    m = _MFI_RE.search(segment)
    if m:
        try:
            val = _parse_number(m.group(2))
            if 0 <= val < 200:
                spec.mfi = val
                spec.mfi_conditions = (m.group(3) or m.group(1) or None)
                if spec.mfi_conditions:
                    spec.mfi_conditions = re.sub(r"\s+", "", spec.mfi_conditions)[:60]
        except ValueError:
            pass
    m = _DENSITY_RE.search(segment) or _DENSITY_UNIT_RE.search(segment)
    if m:
        raw = m.group(1).replace(",", ".")
        try:
            val = float(raw)
            if val > 100:  # kg/m3
                val = val / 1000
            if 0.85 < val < 1.0:
                spec.density = round(val, 4)
        except ValueError:
            pass
    m = _BRAND_GRADE_RE.search(segment)
    if m and re.search(r"\d", m.group(2)):
        spec.brand, spec.grade_number = m.group(1), m.group(2).strip()
    else:
        mb = _BRAND_RE.search(segment)
        if mb:
            spec.brand = mb.group(1)
    if not spec.grade_number:
        m = _GRADE_NO_RE.search(segment)
        if m and re.search(r"\d", m.group(1)):
            spec.grade_number = m.group(1).rstrip(".,")
    m = compiled()["colours"].search(segment)
    if m:
        spec.colour = m.group(1).lower()
    forms = _matches("forms", segment)
    if forms:
        spec.form = forms[0][0]
    m = _ORIGIN_RE.search(segment)
    if m:
        spec.origin_country = country_from_text(m.group(1))
    m = _PACKAGING_RE.search(segment)
    if m:
        spec.packaging = m.group(1)
    return spec


def _segments(text: str) -> list[tuple[int, int]]:
    """Sentence-ish segments (newline, bullet, period+space, pipe)."""
    spans, start = [], 0
    for m in re.finditer(r"(\n+|(?<=[.!?;])\s+(?=[A-Z0-9])|\s\|\s|•|·)", text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


_CLAUSE_SEP = re.compile(r"\s+(?:and|&|as\s+well\s+as|plus|along\s+with)\s+|[,;/]\s*", re.IGNORECASE)


def _split_groups(segment: str, base: int, mentions: list[tuple[str, int, int]]) -> list[tuple[str, set[str]]]:
    """Split a multi-polymer sentence into clause groups, one per polymer mention.
    Separators inside parentheses are ignored. Clauses without a polymer attach to the previous group."""
    if len({m[0] for m in mentions}) <= 1 and len(mentions) <= 1:
        return [(segment, {m[0] for m in mentions})]
    depth, cuts, last = 0, [], 0
    i = 0
    while i < len(segment):
        ch = segment[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            m = _CLAUSE_SEP.match(segment, i)
            if m and m.end() > m.start():
                cuts.append((last, m.start()))
                last = m.end()
                i = m.end()
                continue
        i += 1
    cuts.append((last, len(segment)))
    groups: list[list] = []
    for cs, ce in cuts:
        polys = {c for c, a, b in mentions if cs <= a - base < ce}
        piece = segment[cs:ce]
        if polys or not groups:
            groups.append([piece, set(polys)])
        else:
            groups[-1][0] += ", " + piece
    # leading clause without polymer (e.g. "We supply") merges into first polymer group
    if len(groups) > 1 and not groups[0][1]:
        first = groups.pop(0)
        groups[0][0] = first[0] + " " + groups[0][0]
    return [(g[0], g[1]) for g in groups]


def classify_text(text: str) -> ClassificationResult:
    result = ClassificationResult()
    if not text or not text.strip():
        return result
    text = text[:200_000]
    mentions = find_polymers(text)
    segs = _segments(text)
    seg_infos = []
    for s, e in segs:
        ms = [m for m in mentions if s <= m[1] < e]
        if ms and e - s > 800:  # very long block: one window per mention
            for m in ms:
                ws, we = max(s, m[1] - WINDOW), min(e, m[2] + WINDOW)
                seg_infos.append((ws, we, [m]))
        else:
            seg_infos.append((s, e, ms))

    findings: dict[tuple, MaterialFinding] = {}
    for idx, (s, e, seg_mentions) in enumerate(seg_infos):
        if not seg_mentions:
            continue
        segment = text[s:e]
        # up to 3 following sentences without polymer mentions carry specs/prices/quantities
        cont_parts = []
        for s2, e2, m2 in seg_infos[idx + 1: idx + 4]:
            if m2:
                break
            cont_parts.append(text[s2:e2])
        continuation = " ".join(cont_parts)
        # intent fallback: only a preceding heading-like sentence without its own polymer ("We supply:")
        prev = seg_infos[idx - 1] if idx > 0 else None
        heading = text[prev[0]:prev[1]] if prev and not prev[2] and (prev[1] - prev[0]) < 120 else ""

        intents = {k for k, _ in _matches("intent", segment)} or {k for k, _ in _matches("intent", heading)}
        is_producer = any(k == "manufacturer" for k, _ in _matches("business_types", segment))
        if is_producer:
            rel = "manufacturer"
        elif intents == {"seller"}:
            rel = "seller"
        elif intents == {"buyer"}:
            rel = "buyer"
        elif intents == {"buyer", "seller"}:
            rel = "both"
        else:
            rel = "unknown"

        groups = _split_groups(segment, s, seg_mentions)
        single = len(groups) == 1
        for gtext, gpolys in groups:
            if gpolys - {"PE_SCRAP", "PE_OTHER"}:
                gpolys = gpolys - {"PE_SCRAP"}
            if not gpolys:
                continue
            own_grades = [g for g, _ in _matches("grades", gtext)]
            own_apps = [a for a, _ in _matches("applications", gtext)]
            attr_text = gtext if (own_grades or own_apps) else segment
            grades = own_grades if (own_grades or own_apps) else [g for g, _ in _matches("grades", attr_text)]
            apps = own_apps if (own_grades or own_apps) else [a for a, _ in _matches("applications", attr_text)]
            if {"pcr", "pir", "reprocessed"} & set(grades) and "recycled" in grades:
                grades.remove("recycled")
            if "scrap" in grades and {"recycled", "pcr", "pir", "reprocessed"} & set(grades):
                grades.remove("scrap")
            if "coating" in apps and "extrusion" in apps:
                apps.remove("extrusion")
            grades, apps = grades or ["unknown"], apps or ["unknown"]

            spec_text = gtext + (" " + continuation if single and continuation else "")
            spec = extract_specs(spec_text)
            avail = req = unit = period = None
            for qm in _QTY_RE.finditer(spec_text):
                around = spec_text[max(0, qm.start() - 60):qm.end() + 30]
                qty = float(qm.group(1).replace(",", ""))
                if _QTY_REQUIRED.search(around):
                    req = qty
                elif _QTY_AVAILABLE.search(around):
                    avail = qty
                else:
                    continue
                pm_ = _PERIOD_RE.match(spec_text[qm.end():qm.end() + 40])
                unit, period = "MT", (qm.group(3) or (pm_.group(1).lower() if pm_ else None))
                break

            evidence = re.sub(r"\s+", " ", (segment + (" " + continuation if continuation else ""))).strip()[:900]
            spec.evidence = re.sub(r"\s+", " ", spec_text).strip()[:900]
            for poly in sorted(gpolys):
                for g in grades:
                    for a in apps:
                        conf = 0.55 + (0.15 if g != "unknown" else 0) + (0.1 if a != "unknown" else 0) \
                            + (0.15 if rel != "unknown" else 0)
                        review = "needs_review" if g == "non_prime_unspecified" else "auto"
                        f = MaterialFinding(polymer=poly, grade_category=g, application=a, relationship=rel,
                                            form=spec.form, evidence=evidence, confidence=min(conf, 0.95),
                                            review_status=review)
                        if len(gpolys) == 1:
                            f.available_quantity, f.required_quantity = avail, req
                            if avail or req:
                                f.quantity_unit, f.quantity_period = unit, period
                            if spec.has_values():
                                f.specs.append(spec)
                        existing = findings.get(f.key)
                        if existing:
                            existing.confidence = min(0.97, max(existing.confidence, f.confidence) + 0.03)
                            existing.specs.extend(f.specs)
                            for attr in ("available_quantity", "required_quantity", "quantity_unit", "quantity_period", "form"):
                                if getattr(existing, attr) is None and getattr(f, attr) is not None:
                                    setattr(existing, attr, getattr(f, attr))
                        else:
                            findings[f.key] = f

        price_text = segment + (" " + continuation if continuation else "")
        seg_polys = {m[0] for m in seg_mentions} - {"PE_OTHER"}
        for pm in _PRICE_RE.finditer(price_text):
            try:
                price = _parse_number(pm.group(2))
            except ValueError:
                continue
            cur = _CURRENCY.get(pm.group(1), _CURRENCY.get(pm.group(1).upper(), pm.group(1).upper()))
            unit_raw = re.sub(r"\s+", " ", pm.group(3).lower())
            result.prices.append(PriceFinding(
                polymer=next(iter(seg_polys)) if len(seg_polys) == 1 else None,
                price=price, currency=cur[:3], unit=_UNIT.get(unit_raw, unit_raw),
                incoterm=pm.group(4).upper() if pm.group(4) else None,
                evidence=_snippet(price_text, pm.start(), pm.end(), 100)))

    # Collapse: if a polymer has a specific finding, drop its fully-unknown duplicate row
    by_poly: dict[str, list[MaterialFinding]] = {}
    for f in findings.values():
        by_poly.setdefault(f.polymer, []).append(f)
    for poly, fs in by_poly.items():
        specific = [f for f in fs if (f.grade_category, f.application, f.relationship) != ("unknown", "unknown", "unknown")]
        keep = specific or fs[:1]
        for f in keep:
            if not specific and fs:
                # merge specs from all unknown rows into the single kept row
                for other in fs[1:]:
                    f.specs.extend(other.specs)
            result.materials.append(f)
    for f in result.materials:
        # deduplicate identical specs
        uniq, seen = [], set()
        for sp in f.specs:
            sig = (sp.grade_number, sp.mfi, sp.density, sp.colour, sp.brand)
            if sig not in seen:
                seen.add(sig)
                uniq.append(sp)
        f.specs = uniq

    # Business types across the full text
    btypes: dict[str, BusinessFinding] = {}
    for key, rxs in compiled()["business_types"].items():
        hits = []
        for rx in rxs:
            hits.extend(rx.finditer(text))
        if hits:
            first = min(hits, key=lambda m: m.start())
            conf = min(0.9, 0.5 + 0.1 * len(hits))
            btypes[key] = BusinessFinding(key, _snippet(text, first.start(), first.end()), conf)
    # A converter that also says "manufacturer" of finished goods is NOT a resin manufacturer:
    # the manufacturer patterns are resin-specific, so nothing to undo here. Producer is an alias.
    if "manufacturer" in btypes:
        btypes.setdefault("producer", BusinessFinding("producer", btypes["manufacturer"].evidence, btypes["manufacturer"].confidence))
    result.business_types = list(btypes.values())
    return result
