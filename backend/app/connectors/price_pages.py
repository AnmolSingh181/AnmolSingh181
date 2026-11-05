"""Price-list web pages (HTML tables), e.g. Plastemart's Indian producer polymer price lists.

Config-driven and conservative:
- Disabled until an admin confirms the site's terms of use (requires_terms_confirmation), robots.txt is respected,
  requests are rate-limited and identify the crawler (PoliteClient.get).
- Rows are mapped to price series by explicit rules (polymer / grade / producer regexes). Unmatched rows are only
  logged, never stored, so the log tells you how to extend the rules.
- A row is stored only when it has a price under a recognised price header AND a date (a date column, or an
  effective date such as "w.e.f. 1st Nov 2026" printed near the table). Implausible per-kg values are rejected.

Source config (Data sources -> edit config), all keys optional except pages:
  pages          [{"url": "...", "producer": "Reliance"}]   producer = context for rules when the page doesn't say
  table_selector CSS selector for tables (default "table")
  price_unit     "t" | "kg" (default: detected from header text, "/kg" -> kg, else t, i.e. INR/MT)
  undated        "skip" (default) | "collection_date"
  plausible_per_kg [min, max] in series currency (default [20, 1000])
  rules          [{"series_key": "...", "polymer": "LLDPE", "grade": "film|butene", "producer": "reliance|\\bril\\b"}]
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.connectors.base import BaseConnector, JobStats
from app.models import ApiUsage, PriceSeries
from app.services.http import PoliteClient
from app.services.ingestion import store_raw
from app.services.prices import PER_KG, _num, record_point

PRICE_HEADERS = re.compile(r"\b(price|rate|basic|list price|ex[- ]?works|inr|rs\.?|₹)\b", re.I)
DATE_HEADERS = re.compile(r"\b(date|w\.?\s?e\.?\s?f\.?|effective|valid)\b", re.I)
GRADE_HEADERS = re.compile(r"\b(grade|product|description|item|application|polymer)\b", re.I)
PRODUCER_HEADERS = re.compile(r"\b(producer|manufacturer|company|supplier|make)\b", re.I)
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
EFFECTIVE_RE = re.compile(
    rf"(?:w\.?\s?e\.?\s?f\.?|with effect from|effective(?: from)?|valid from|from)\s*:?\s*"
    rf"(\d{{1,2}}(?:st|nd|rd|th)?[\s.\-/]*(?:{MONTHS})[a-z]*[\s.,\-/]*\d{{2,4}}|\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}})",
    re.I)
POLYMER_RE = {
    "LLDPE": re.compile(r"\bl\.?l\.?d\.?p\.?e\b|linear low", re.I),
    "LDPE": re.compile(r"(?<!l)\bl\.?d\.?p\.?e\b|(?<!linear )low density", re.I),
    "HDPE": re.compile(r"\bh\.?d\.?p\.?e\b|high density", re.I),
    "PP": re.compile(r"\bp\.?p\b|polypropylene", re.I),
    "PVC": re.compile(r"\bp\.?v\.?c\b|vinyl", re.I),
}

# Default mapping to the seeded India producer-list series, using Reliance (RIL) as the benchmark producer.
DEFAULT_RULES = [
    {"series_key": "in_lldpe_film_list", "polymer": "LLDPE", "grade": r"film|butene|\bc4\b", "producer": r"reliance|\bril\b"},
    {"series_key": "in_hdpe_film_list", "polymer": "HDPE", "grade": r"film", "producer": r"reliance|\bril\b"},
    {"series_key": "in_ldpe_film_list", "polymer": "LDPE", "grade": r"film", "producer": r"reliance|\bril\b"},
    {"series_key": "in_pp_raffia_list", "polymer": "PP", "grade": r"raffia|tape", "producer": r"reliance|\bril\b"},
    {"series_key": "in_pvc_list", "polymer": "PVC", "grade": r"suspension|s-?pvc|k\s?-?6[5-7]|pipe", "producer": r"reliance|\bril\b"},
]


def parse_effective_date(text: str) -> date | None:
    from app.connectors.imports import parse_date

    m = EFFECTIVE_RE.search(text or "")
    if not m:
        return None
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", m.group(1), flags=re.I)
    raw = re.sub(r"[\s.,\-/]+", " ", raw).strip()
    raw = re.sub(r"\bsept\b", "Sep", raw, flags=re.I)
    for cand in (raw, raw.replace(" ", "-")):
        d = parse_date(cand)
        if d:
            return d
    try:  # "1 November 2026"
        from datetime import datetime

        return datetime.strptime(raw.title(), "%d %B %Y").date()
    except ValueError:
        pass
    parts = re.split(r"[./-]", m.group(1))
    if len(parts) == 3 and all(p.isdigit() for p in parts):  # Indian dd.mm.yyyy
        d, mo, y = (int(p) for p in parts)
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def parse_price_cell(text: str) -> tuple[float | None, float | None, float | None]:
    """'1,05,500' -> 105500; '105-110' / '105 to 110' -> mid 107.5 (low 105, high 110). Ignores currency marks."""
    t = re.sub(r"(rs\.?|inr|₹|/-|per\s*\w+|/\s*(mt|kg|t))", " ", text or "", flags=re.I)
    nums = [_num(n) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)]
    nums = [n for n in nums if n is not None and n > 0]
    if not nums:
        return None, None, None
    if len(nums) >= 2 and re.search(r"\d\s*(-|–|to)\s*\d", t):
        lo, hi = min(nums[:2]), max(nums[:2])
        return (lo + hi) / 2, lo, hi
    return nums[0], None, None


def _context(table) -> str:
    """Headings/captions just before the table: often carry the producer name and the w.e.f. date."""
    bits = []
    cap = table.find("caption")
    if cap:
        bits.append(cap.get_text(" ", strip=True))
    for el in table.find_all_previous(["h1", "h2", "h3", "h4", "h5", "strong", "b", "p"], limit=6):
        bits.append(el.get_text(" ", strip=True))
    return " | ".join(bits)[:1500]


def extract_rows(html: str, table_selector: str = "table") -> list[dict]:
    """Every data row of every table that has a recognisable price header."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for ti, table in enumerate(soup.select(table_selector)):
        rows = table.find_all("tr")
        header_idx, headers = None, []
        for i, tr in enumerate(rows[:5]):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if any(PRICE_HEADERS.search(c) for c in cells) and not all(_num(c) for c in cells if c):
                header_idx, headers = i, cells
                break
        if header_idx is None:
            continue
        price_cols = [j for j, h in enumerate(headers) if PRICE_HEADERS.search(h) and not DATE_HEADERS.search(h)]
        date_cols = [j for j, h in enumerate(headers) if DATE_HEADERS.search(h)]
        ctx = _context(table)
        for tr in rows[header_idx + 1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not any(cells):
                continue
            price_text = next((cells[j] for j in price_cols if j < len(cells) and re.search(r"\d", cells[j])), None)
            date_text = next((cells[j] for j in date_cols if j < len(cells) and cells[j]), None)
            out.append({"table": ti, "headers": headers, "cells": cells, "price_text": price_text,
                        "price_header": headers[price_cols[0]] if price_cols else "", "date_text": date_text,
                        "context": ctx})
    return out


class HtmlPriceTableConnector(BaseConnector):
    key = ""
    job_types = ("refresh",)
    requires_terms_confirmation = True

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient()

    def status(self) -> dict:
        cfg = self.source.config or {}
        if not cfg.get("terms_confirmed"):
            return {"ready": False, "message": "Review the site's terms of use and confirm them before enabling"}
        return {"ready": bool(self.pages()), "message": "ready" if self.pages() else "configure pages"}

    def pages(self) -> list[dict]:
        cfg = self.source.config or {}
        pages = cfg.get("pages")
        if pages:
            return [p if isinstance(p, dict) else {"url": p} for p in pages]
        return [{"url": u} for u in getattr(self, "default_pages", [])]

    def run(self, job_type: str, params: dict) -> JobStats:
        from app.connectors.imports import parse_date

        self.ensure_allowed()
        cfg = self.source.config or {}
        rules = cfg.get("rules") or DEFAULT_RULES
        series = {s.key: s for s in self.db.scalars(select(PriceSeries).where(
            PriceSeries.key.in_([r["series_key"] for r in rules]), PriceSeries.is_active)).all()}
        lo_ok, hi_ok = cfg.get("plausible_per_kg") or [20, 1000]
        unmatched: list[str] = []
        for page in self.pages():
            url = page["url"]
            try:
                r = self.client.get(url)
                r.raise_for_status()
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"{url}: {exc}", "warning")
                continue
            self.db.add(ApiUsage(provider=self.key, operation="page", units=1))
            html = r.text
            rr, _ = store_raw(self.db, self.source, "price_page", {"url": url}, raw_text=html[:500000],
                              source_url=url, job=self.job)
            rows = extract_rows(html, cfg.get("table_selector") or "table")
            page_date = parse_effective_date(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
            if not rows:
                self.log(f"{url}: no table with a price column found (page layout changed, login required, or "
                         "set table_selector)", "warning")
                continue
            claimed: set[tuple[str, date]] = set()
            for row in rows:
                text = " ".join(row["cells"])
                producer_ctx = f"{text} | {row['context']} | {page.get('producer', '')}"
                rule = next((ru for ru in rules
                             if (not ru.get("polymer") or POLYMER_RE.get(ru["polymer"], re.compile(re.escape(ru["polymer"]), re.I)).search(text))
                             and (not ru.get("grade") or re.search(ru["grade"], text, re.I))
                             and (not ru.get("producer") or re.search(ru["producer"], producer_ctx, re.I))), None)
                if not rule:
                    if len(unmatched) < 25:
                        unmatched.append(text[:120])
                    continue
                s = series.get(rule["series_key"])
                if not s:
                    continue
                price, low, high = parse_price_cell(row["price_text"] or "")
                obs = (parse_date(row["date_text"]) or parse_effective_date(f"wef {row['date_text']}")) \
                    if row["date_text"] else None
                obs = obs or parse_effective_date(row["context"]) or page_date
                if obs is None and cfg.get("undated") == "collection_date":
                    obs = date.today()
                if price is None or obs is None:
                    self.stats.failed += 1
                    self.log(f"skipped (no {'price' if price is None else 'date'}): {text[:120]}", "warning")
                    continue
                unit_in = cfg.get("price_unit") or ("kg" if re.search(r"kg", row["price_header"], re.I) else "t")
                if s.unit not in PER_KG:
                    continue
                factor = PER_KG[unit_in] / PER_KG[s.unit]
                val = price * factor
                per_kg = val * PER_KG[s.unit] / PER_KG["kg"]
                if not (lo_ok <= per_kg <= hi_ok):
                    self.stats.failed += 1
                    self.log(f"rejected implausible {per_kg:.2f}/kg for {s.key}: {text[:120]}", "warning")
                    continue
                if (s.key, obs) in claimed:  # first matching row per series and date wins
                    continue
                claimed.add((s.key, obs))
                out = record_point(self.db, s, obs, round(val, 4), low=round(low * factor, 4) if low else None,
                                   high=round(high * factor, 4) if high else None, source_url=url,
                                   note=f"{self.source.name}: {text[:200]}", raw_record_id=rr.id)
                self.stats.found += 1
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created and out.changed)
            self.db.commit()
            self.log(f"{url}: {len(rows)} table rows, {len(claimed)} mapped to series, page date {page_date}")
        if unmatched:
            self.log("Unmatched rows (extend config.rules to map them): " + " || ".join(unmatched))
        return self.stats


class PlastemartConnector(HtmlPriceTableConnector):
    key = "plastemart"
    default_pages = ["https://www.plastemart.com/polymer-price-list-pe-pp-pvc"]
