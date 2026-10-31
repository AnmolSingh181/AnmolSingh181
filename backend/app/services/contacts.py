"""Contact extraction from public company pages + verification ladder.

Status ladder (never skipped, never faked):
discovered -> syntax_checked -> domain_checked -> email_verified (authorised provider only) / manually_verified
phone numbers: discovered -> phone_checked. Failures -> invalid. Stale (> refresh window) -> outdated.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiUsage, Contact, ContactVerification
from app.services.normalize import clean_text, extract_domain, normalize_email, normalize_phone

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b")
PHONE_CTX_RE = re.compile(
    r"(?:tel|phone|ph|mobile|mob|cell|whatsapp|fax|call(?:\s+us)?|contact)\s*(?:no\.?|number|#)?\s*[:.\-]?\s*"
    r"(\+?\(?\d[\d\s().\-/]{7,20}\d)", re.IGNORECASE)
LINKEDIN_COMPANY_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9_\-%.]+/?", re.IGNORECASE)
LINKEDIN_PERSON_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_\-%.]+/?", re.IGNORECASE)
BAD_EMAIL_PARTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "sentry", "wixpress", "example.com", "domain.com",
                   "yourcompany", "email.com", "@2x")

TITLE_KEYWORDS = {
    "Procurement": ["procurement", "purchas", "buyer", "sourcing", "supply chain"],
    "Sales": ["sales", "business development", "commercial", "marketing", "account manager"],
    "Export/Import": ["export", "import", "international trade", "logistics"],
    "Management": ["managing director", "director", "ceo", "chief executive", "founder", "owner", "president",
                   "general manager", "partner", "proprietor", "chairman"],
}
DECISION_TITLE_RE = re.compile(
    r"\b(procurement|purchas\w*|raw\s+material\s+buyer|buyer|sourcing|sales|export|import|commercial|managing\s+director|"
    r"business\s+development|director|ceo|owner|founder|general\s+manager|president|proprietor)\b", re.IGNORECASE)
# "Name - Title" / "Name, Title" / "Title: Name" on a single line, title must contain a known role word
PERSON_LINE_RE = re.compile(
    r"^(?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3})\s*[,–\-|:]\s*"
    r"([A-Za-z&/ ]{3,60}(?:Manager|Director|Head|Officer|Executive|CEO|Founder|Owner|President|Buyer|Partner|Proprietor|Chairman)[A-Za-z&/ ]{0,40})$")


@dataclass
class ExtractedContact:
    contact_type: str
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    linkedin_url: str | None = None
    evidence: str = ""
    source_url: str | None = None


@dataclass
class ExtractedCompanyInfo:
    name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    linkedin_url: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    contacts: list[ExtractedContact] = field(default_factory=list)


def department_for_title(title: str | None) -> str | None:
    if not title:
        return None
    t = title.lower()
    for dept, kws in TITLE_KEYWORDS.items():
        if any(k in t for k in kws):
            return dept
    return None


def decision_role_for_title(title: str | None) -> str:
    """Title-based inference only ever yields 'likely'; confirmation requires manual verification."""
    return "likely_decision_maker" if title and DECISION_TITLE_RE.search(title) else "unknown_authority"


def _valid_email(e: str) -> bool:
    el = e.lower()
    return not any(b in el for b in BAD_EMAIL_PARTS) and len(el) <= 254


def _jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                if "@graph" in obj and isinstance(obj["@graph"], list):
                    stack.extend(obj["@graph"])
                out.append(obj)
            elif isinstance(obj, list):
                stack.extend(obj)
    return out


def extract_from_html(html: str, url: str | None = None) -> ExtractedCompanyInfo:
    soup = BeautifulSoup(html, "lxml")
    info = ExtractedCompanyInfo()
    emails: dict[str, str] = {}
    phones: dict[str, str] = {}

    for obj in _jsonld_objects(soup):
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(t in ("Organization", "Corporation", "LocalBusiness", "Store", "WholesaleStore") for t in types if t):
            info.name = info.name or (obj.get("legalName") or obj.get("name"))
            if obj.get("email"):
                emails.setdefault(str(obj["email"]).removeprefix("mailto:"), "JSON-LD Organization.email")
            if obj.get("telephone"):
                phones.setdefault(str(obj["telephone"]), "JSON-LD Organization.telephone")
            addr = obj.get("address")
            if isinstance(addr, dict):
                info.address = clean_text(", ".join(str(addr.get(k)) for k in ("streetAddress", "addressLocality",
                                                                                "addressRegion", "postalCode", "addressCountry") if addr.get(k)))
                info.city = addr.get("addressLocality")
                info.state = addr.get("addressRegion")
                info.postal_code = addr.get("postalCode")
                c = addr.get("addressCountry")
                info.country = c.get("name") if isinstance(c, dict) else c
            same = obj.get("sameAs") or []
            for s in same if isinstance(same, list) else [same]:
                if isinstance(s, str) and LINKEDIN_COMPANY_RE.match(s):
                    info.linkedin_url = s
            for person in (obj.get("employee") or obj.get("member") or []) if isinstance(obj.get("employee") or obj.get("member"), list) else []:
                if isinstance(person, dict) and person.get("name") and (person.get("email") or person.get("telephone")):
                    title = person.get("jobTitle")
                    info.contacts.append(ExtractedContact(
                        contact_type="individual", full_name=person["name"], job_title=title,
                        department=department_for_title(title), email=person.get("email"), phone=person.get("telephone"),
                        evidence="JSON-LD employee", source_url=url))
        if "Person" in types and obj.get("name") and (obj.get("email") or obj.get("telephone")):
            title = obj.get("jobTitle")
            info.contacts.append(ExtractedContact(
                contact_type="individual", full_name=obj["name"], job_title=title, department=department_for_title(title),
                email=obj.get("email"), phone=obj.get("telephone"), evidence="JSON-LD Person", source_url=url))

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            e = href[7:].split("?")[0]
            emails.setdefault(e, f"mailto link: {clean_text(a.get_text())[:80]}")
        elif href.lower().startswith("tel:"):
            phones.setdefault(href[4:], f"tel link: {clean_text(a.get_text())[:80]}")
        elif LINKEDIN_COMPANY_RE.match(href) and not info.linkedin_url:
            info.linkedin_url = LINKEDIN_COMPANY_RE.match(href).group(0)

    for s in soup(["script", "style", "noscript", "svg"]):
        s.decompose()
    text = soup.get_text("\n")
    for m in EMAIL_RE.finditer(text):
        emails.setdefault(m.group(0), clean_text(text[max(0, m.start() - 60):m.end() + 20]))
    for m in PHONE_CTX_RE.finditer(text):
        phones.setdefault(m.group(1).strip(), clean_text(m.group(0)))

    # Individual people: only lines that explicitly pair a person name with a job title, and that carry an email
    # or phone within the next two lines. No guessing of email patterns.
    lines = [clean_text(l) for l in text.split("\n")]
    lines = [l for l in lines if l]
    for i, line in enumerate(lines):
        m = PERSON_LINE_RE.match(line)
        if not m:
            continue
        nearby = " ".join(lines[i + 1:i + 3])
        em = EMAIL_RE.search(nearby)
        ph = PHONE_CTX_RE.search(nearby)
        if not (em or ph):
            continue
        title = m.group(2).strip()
        info.contacts.append(ExtractedContact(
            contact_type="individual", full_name=m.group(1).strip(), job_title=title, department=department_for_title(title),
            email=em.group(0) if em else None, phone=ph.group(1) if ph else None,
            evidence=f"{line} | {nearby}"[:400], source_url=url))

    person_emails = {(c.email or "").lower() for c in info.contacts}
    for e, ev in emails.items():
        if _valid_email(e) and normalize_email(e) and e.lower() not in person_emails:
            info.emails.append(e)
            info.contacts.append(ExtractedContact(contact_type="general", email=e, evidence=ev, source_url=url))
    for p, ev in phones.items():
        if len(re.sub(r"\D", "", p)) >= 8:
            info.phones.append(p)
            info.contacts.append(ExtractedContact(contact_type="general", phone=p, evidence=ev, source_url=url))
    return info


# ------------------------------------------------------------------ verification
def _record(db: Session, contact: Contact, check: str, result: str, status: str, details: dict,
            provider: str | None = None, user_id=None) -> None:
    db.add(ContactVerification(contact_id=contact.id, check_type=check, result=result, status_after=status,
                               details=details, provider=provider, checked_by=user_id))
    contact.verification_status = status
    contact.last_verified_at = datetime.now(timezone.utc)


def check_syntax(db: Session, contact: Contact) -> bool:
    from email_validator import EmailNotValidError, validate_email

    if not contact.email:
        return False
    try:
        validate_email(contact.email, check_deliverability=False)
        _record(db, contact, "syntax", "pass", "syntax_checked", {})
        return True
    except EmailNotValidError as exc:
        _record(db, contact, "syntax", "fail", "invalid", {"error": str(exc)})
        return False


def check_domain(db: Session, contact: Contact) -> str:
    """MX lookup. 'unknown' if DNS is unreachable (status unchanged)."""
    import dns.exception
    import dns.resolver

    domain = extract_domain(contact.email)
    if not domain:
        return "unknown"
    try:
        answers = dns.resolver.resolve(contact.email.split("@", 1)[1], "MX", lifetime=6)
        mx = sorted(str(r.exchange).rstrip(".") for r in answers)
        _record(db, contact, "domain_mx", "pass", "domain_checked", {"mx": mx[:5]})
        return "pass"
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        _record(db, contact, "domain_mx", "fail", "invalid", {"error": "no MX / domain does not exist"})
        return "fail"
    except (dns.exception.DNSException, OSError) as exc:
        db.add(ContactVerification(contact_id=contact.id, check_type="domain_mx", result="unknown",
                                   status_after=contact.verification_status, details={"error": str(exc)[:200]}))
        return "unknown"


def check_phone(db: Session, contact: Contact, country_prefix: str | None = None) -> bool:
    norm = normalize_phone(contact.phone, country_prefix)
    if norm and 8 <= len(norm) <= 15:
        contact.phone_normalized = norm
        if not contact.email:  # phone-only contacts advance on phone check
            _record(db, contact, "phone_format", "pass", "phone_checked", {"normalized": norm})
        else:
            db.add(ContactVerification(contact_id=contact.id, check_type="phone_format", result="pass",
                                       status_after=contact.verification_status, details={"normalized": norm}))
        return True
    _record(db, contact, "phone_format", "fail", "invalid" if not contact.email else contact.verification_status,
            {"raw": contact.phone})
    return False


def check_with_provider(db: Session, contact: Contact) -> str:
    """ZeroBounce (authorised provider). Returns 'awaiting_credentials' when no key is configured."""
    s = get_settings()
    if not s.zerobounce_api_key:
        return "awaiting_credentials"
    import httpx

    try:
        r = httpx.get("https://api.zerobounce.net/v2/validate",
                      params={"api_key": s.zerobounce_api_key, "email": contact.email, "ip_address": ""}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("ZeroBounce error: %s", exc)
        return "error"
    db.add(ApiUsage(provider="zerobounce", operation="validate", units=1, estimated_cost_usd=0.008))
    status = (data.get("status") or "").lower()
    if status == "valid":
        _record(db, contact, "provider_email", "pass", "email_verified", {"status": status}, provider="zerobounce")
        return "pass"
    if status in ("invalid", "spamtrap", "abuse", "do_not_mail"):
        _record(db, contact, "provider_email", "fail", "invalid", {"status": status, "sub_status": data.get("sub_status")},
                provider="zerobounce")
        return "fail"
    db.add(ContactVerification(contact_id=contact.id, check_type="provider_email", result="unknown",
                               status_after=contact.verification_status, details={"status": status}, provider="zerobounce"))
    return "unknown"


def verify_contact(db: Session, contact: Contact, country_prefix: str | None = None, use_provider: bool = True,
                   use_dns: bool = True) -> str:
    if contact.email:
        if check_syntax(db, contact) and use_dns:
            if check_domain(db, contact) == "pass" and use_provider:
                check_with_provider(db, contact)
    if contact.phone:
        check_phone(db, contact, country_prefix)
    return contact.verification_status


def mark_outdated(db: Session, max_age_days: int = 180) -> int:
    """Contacts not re-seen or re-verified within max_age_days become 'outdated' (kept for history)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    from sqlalchemy import update

    res = db.execute(update(Contact).where(
        Contact.verification_status.notin_(["invalid", "outdated", "manually_verified"]),
        Contact.updated_at < cutoff,
        (Contact.last_verified_at.is_(None)) | (Contact.last_verified_at < cutoff)).values(verification_status="outdated"))
    return res.rowcount or 0
