"""Normalisation helpers for entity resolution."""
import hashlib
import re
import unicodedata
from functools import lru_cache
from urllib.parse import urlparse

import tldextract

from app.services.dictionary import get_dictionary

# Legal-form suffixes and generic words across our markets (US, CN, VN, AE, SA, IN, EU, TR, SEA)
LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "co", "corp", "corporation", "company", "plc", "lp", "llp",
    "pvt", "private", "pte", "pty", "gmbh", "ag", "kg", "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "oy", "ab", "as",
    "fze", "fzco", "fzc", "fzllc", "fz", "est", "establishment", "wll", "jsc", "jsco", "tnhh", "cty", "cong", "ty",
    "mtv", "cp", "sdn", "bhd", "tbk", "pt", "as", "sti", "ltd sti", "kk", "group", "holding", "holdings", "the",
    "and", "of", "intl", "international",
}
# Words that carry little identity information; removed only for the fuzzy "core" comparison
GENERIC_WORDS = {
    "trading", "traders", "trade", "industries", "industry", "industrial", "enterprises", "enterprise", "global",
    "plastics", "plastic", "polymers", "polymer", "chemicals", "chemical", "petrochemical", "petrochemicals",
    "general", "import", "export", "imports", "exports", "impex", "overseas", "solutions", "services", "products",
    "manufacturing", "mfg", "resources", "materials", "commodities", "recycling", "packaging",
}

_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # offline: bundled public suffix snapshot


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_company_name(name: str | None) -> str:
    if not name:
        return ""
    s = strip_accents(name).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)              # drop bracketed notes e.g. "(formerly ...)"
    s = re.sub(r"[^\w\s]", " ", s)              # punctuation
    s = re.sub(r"\b(?:co|pvt|pte|sdn)\s+(?:ltd|bhd)\b", " ", s)
    tokens = [t for t in s.split() if t]
    # strip trailing legal suffixes repeatedly, and leading "cong ty"/"the"
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    while tokens and tokens[0] in {"the", "cong", "ty", "cty", "tnhh", "mtv", "cp", "pt", "ms", "m", "s"}:
        tokens.pop(0)
    return " ".join(tokens).strip()


def core_name(normalized: str) -> str:
    tokens = [t for t in normalized.split() if t not in GENERIC_WORDS and t not in LEGAL_SUFFIXES]
    return " ".join(tokens) or normalized


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urlparse(url)
    if not p.netloc or "." not in p.netloc:
        return None
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}" if p.path not in ("", "/") else f"{p.scheme.lower()}://{p.netloc.lower()}"


def extract_domain(url_or_email: str | None) -> str | None:
    if not url_or_email:
        return None
    v = url_or_email.strip().lower()
    if "@" in v and "://" not in v:
        v = v.split("@", 1)[1]
    if "://" not in v:
        v = "http://" + v
    host = urlparse(v).hostname
    if not host:
        return None
    ext = _tld(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return host.removeprefix("www.")


@lru_cache
def generic_domains() -> frozenset[str]:
    return frozenset(get_dictionary().get("generic_domains", []))


def is_generic_domain(domain: str | None) -> bool:
    return bool(domain) and domain in generic_domains()


def company_domain(website: str | None, email: str | None = None) -> str | None:
    """Domain usable as a company identifier (excludes webmail / marketplaces / social)."""
    for v in (website, email):
        d = extract_domain(v)
        if d and not is_generic_domain(d):
            return d
    return None


def normalize_phone(phone: str | None, country_prefix: str | None = None) -> str | None:
    """Digits-only international form, e.g. '+971 (4) 123-4567' -> '97141234567'."""
    if not phone:
        return None
    raw = phone.strip()
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw.split("ext")[0].split("x ")[0])
    if digits.startswith("00"):
        digits, has_plus = digits[2:], True
    if not has_plus and country_prefix:
        if digits.startswith("0"):
            digits = country_prefix + digits.lstrip("0")
        elif not (digits.startswith(country_prefix) and len(digits) > 10):
            digits = country_prefix + digits
    if len(digits) < 8 or len(digits) > 15:
        return None
    return digits


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = email.strip().lower().removeprefix("mailto:").split("?")[0]
    return e if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e) else None


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()
