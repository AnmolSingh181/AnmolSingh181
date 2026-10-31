"""Company website crawler.

For a company domain it fetches (robots.txt permitting) the home page plus the most relevant internal pages
(about, products, materials, services, contact, company profile) discovered from links and sitemaps,
stores each page as a raw record, then extracts and classifies the combined text.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.config import get_settings
from app.connectors.base import BaseConnector, JobStats
from app.models import Company
from app.services.contacts import extract_from_html
from app.services.http import BlockedError, PoliteClient
from app.services.ingestion import CompanyInput, ContactInput, ingest_company, store_raw
from app.services.normalize import clean_text, extract_domain, normalize_url

PAGE_KEYWORDS = [
    ("contact", 10), ("about", 9), ("product", 9), ("material", 8), ("polymer", 8), ("resin", 8), ("polyethylene", 8),
    ("ldpe", 8), ("hdpe", 8), ("lldpe", 8), ("recycl", 7), ("service", 5), ("profile", 6), ("company", 5),
    ("who-we-are", 7), ("what-we-do", 6), ("trading", 6), ("supply", 4), ("export", 4), ("import", 4), ("team", 4),
    ("grade", 5), ("catalog", 5), ("lien-he", 8), ("gioi-thieu", 7), ("san-pham", 7), ("lianxi", 6), ("guanyu", 5),
]
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|css|js)(\?|$)", re.I)
SKIP_PATH = re.compile(r"/(cart|checkout|login|signin|sign-in|register|account|wp-admin|wp-login|privacy|cookie|terms|tag|"
                       r"author|feed|search)\b", re.I)
CCTLD_COUNTRY = {"ae": "AE", "sa": "SA", "vn": "VN", "cn": "CN", "in": "IN", "us": "US", "tr": "TR", "th": "TH", "my": "MY",
                 "id": "ID", "kr": "KR", "de": "DE", "nl": "NL", "om": "OM", "qa": "QA", "kw": "KW", "bh": "BH", "pk": "PK",
                 "bd": "BD", "eg": "EG", "uk": "GB", "be": "BE", "it": "IT", "es": "ES", "pl": "PL", "fr": "FR", "sg": "SG",
                 "tw": "TW", "jp": "JP", "mx": "MX", "ca": "CA", "br": "BR"}


def score_link(url: str, text: str) -> int:
    u, t = url.lower(), text.lower()
    return sum(w for kw, w in PAGE_KEYWORDS if kw in u or kw in t)


def page_text(soup: BeautifulSoup) -> str:
    for s in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        s.decompose()
    for nav in soup.find_all(["nav", "footer"]):
        # keep footer text (often holds address/contact) but drop menus
        if nav.name == "nav":
            nav.decompose()
    text = soup.get_text("\n")
    lines = [clean_text(l) for l in text.split("\n")]
    return "\n".join(l for l in lines if l)


def company_name_from(soup: BeautifulSoup, jsonld_name: str | None, domain: str) -> str:
    if jsonld_name:
        return clean_text(jsonld_name)
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return clean_text(og["content"])
    if soup.title and soup.title.string:
        parts = [p.strip() for p in re.split(r"\s[|\-–—:»]\s", soup.title.string) if p.strip()]
        generic = re.compile(r"^(home|homepage|welcome|index|official site|official website)$", re.I)
        parts = [p for p in parts if not generic.match(p)]
        if parts:
            # the shortest part that is not a slogan is usually the brand
            return min(parts, key=len)[:200] if len(parts) > 1 else parts[0][:200]
    return domain.split(".")[0].replace("-", " ").title()


def parse_sitemap(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return []
    return [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]


class WebsiteConnector(BaseConnector):
    key = "company_website"
    job_types = ("crawl_website", "refresh_websites")

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self._client = client

    @property
    def client(self) -> PoliteClient:
        if self._client is None:
            self._client = PoliteClient()
        return self._client

    def run(self, job_type: str, params: dict) -> JobStats:
        if job_type == "refresh_websites":
            return self._refresh(params)
        url = params.get("url")
        if not url:
            raise ValueError("crawl_website requires params.url")
        self.crawl(url, country_hint=params.get("country"), discovery_query=params.get("query"))
        return self.stats

    def _refresh(self, params: dict) -> JobStats:
        from datetime import timedelta

        from sqlalchemy import or_, select

        days = int(params.get("older_than_days", 45))
        limit = int(params.get("limit", 50))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = self.db.scalars(select(Company).where(
            Company.status == "active", Company.website.is_not(None), Company.is_demo.is_(False),
            or_(Company.website_last_crawled_at.is_(None), Company.website_last_crawled_at < cutoff))
            .order_by(Company.lead_score.desc().nullslast()).limit(limit)).all()
        for c in rows:
            try:
                self.crawl(c.website, country_hint=c.country_code)
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"refresh failed for {c.website}: {exc}", "warning")
                self.db.rollback()
        return self.stats

    def fetch_html(self, url: str) -> tuple[str | None, str]:
        r = self.client.get(url)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return None, str(r.url)
        html = r.text
        s = get_settings()
        if s.playwright_enabled and len(BeautifulSoup(html, "lxml").get_text(strip=True)) < 300:
            html = self._render(str(r.url)) or html
        return html, str(r.url)

    def _render(self, url: str) -> str | None:
        """Optional JS rendering for thin pages (same robots/rate-limit rules already applied)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        try:
            with sync_playwright() as p:
                b = p.chromium.launch()
                page = b.new_page(user_agent=self.client.user_agent)
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
                b.close()
                return html
        except Exception as exc:
            self.log(f"render failed {url}: {exc}", "warning")
            return None

    def candidate_pages(self, base_url: str, soup: BeautifulSoup) -> list[str]:
        host = urlparse(base_url).netloc.removeprefix("www.")
        scored: dict[str, int] = {}
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"].split("#")[0])
            p = urlparse(href)
            if p.scheme not in ("http", "https") or p.netloc.removeprefix("www.") != host:
                continue
            if SKIP_EXT.search(p.path) or SKIP_PATH.search(p.path):
                continue
            sc = score_link(href, a.get_text(" "))
            if sc > 0:
                scored[href.rstrip("/")] = max(scored.get(href.rstrip("/"), 0), sc)
        try:
            for sm in (self.client.sitemaps(base_url) or [urljoin(base_url, "/sitemap.xml")])[:2]:
                r = self.client.get(sm)
                if r.status_code == 200:
                    for loc in parse_sitemap(r.text)[:500]:
                        p = urlparse(loc)
                        if p.netloc.removeprefix("www.") == host and not SKIP_EXT.search(p.path):
                            sc = score_link(loc, "")
                            if sc >= 6:
                                scored.setdefault(loc.rstrip("/"), sc - 1)
        except BlockedError:
            pass
        except Exception as exc:
            self.log(f"sitemap read failed: {exc}", "warning")
        base_norm = base_url.rstrip("/")
        ranked = sorted((u for u in scored if u != base_norm), key=lambda u: -scored[u])
        return ranked[: max(0, get_settings().crawler_max_pages_per_site - 1)]

    def crawl(self, url: str, country_hint: str | None = None, discovery_query: str | None = None) -> str | None:
        url = normalize_url(url)
        if not url:
            raise ValueError("invalid url")
        domain = extract_domain(url)
        self.stats.found += 1
        try:
            html, final_url = self.fetch_html(url)
        except BlockedError as exc:
            self.log(str(exc), "warning")
            self.stats.failed += 1
            return None
        if not html:
            self.log(f"no HTML at {url}", "warning")
            self.stats.failed += 1
            return None
        pages = [(final_url, html)]
        soup = BeautifulSoup(html, "lxml")
        for purl in self.candidate_pages(final_url, soup):
            try:
                h, fu = self.fetch_html(purl)
                if h:
                    pages.append((fu, h))
            except BlockedError as exc:
                self.log(str(exc), "warning")
            except Exception as exc:
                self.log(f"page fetch failed {purl}: {exc}", "warning")
        return self.process_pages(domain, pages, country_hint=country_hint, discovery_query=discovery_query)

    def process_pages(self, domain: str, pages: list[tuple[str, str]], country_hint: str | None = None,
                      discovery_query: str | None = None, is_demo: bool = False) -> str | None:
        """Turn fetched pages into one company record. Separated from fetching so it is testable offline."""
        now = datetime.now(timezone.utc)
        texts, contacts, raws = [], [], []
        name = description = None
        info_all = None
        for purl, html in pages:
            soup = BeautifulSoup(html, "lxml")
            info = extract_from_html(html, purl)
            if info_all is None:
                info_all = info
                desc = soup.find("meta", attrs={"name": "description"})
                description = clean_text(desc["content"]) if desc and desc.get("content") else None
                name = company_name_from(soup, info.name, domain)
            else:
                for attr in ("linkedin_url", "address", "city", "state", "postal_code", "country"):
                    if not getattr(info_all, attr) and getattr(info, attr):
                        setattr(info_all, attr, getattr(info, attr))
            txt = page_text(BeautifulSoup(html, "lxml"))
            texts.append(f"[{purl}]\n{txt}")
            raw, _ = store_raw(self.db, self.source, "web_page", {"url": purl, "domain": domain,
                                                                  "query": discovery_query},
                               raw_text=txt[:100_000], source_url=purl, job=self.job, is_demo=is_demo)
            raws.append(raw)
            for c in info.contacts:
                contacts.append(ContactInput(contact_type=c.contact_type, full_name=c.full_name, job_title=c.job_title,
                                             department=c.department, email=c.email, phone=c.phone,
                                             linkedin_url=c.linkedin_url, evidence=c.evidence, source_url=c.source_url))
        if not info_all:
            return None
        tld = domain.rsplit(".", 1)[-1] if domain else ""
        country = info_all.country or CCTLD_COUNTRY.get(tld) or country_hint
        combined = "\n\n".join(texts)
        out = ingest_company(self.db, self.source, CompanyInput(
            name=name or domain, country=country, city=info_all.city, state=info_all.state,
            address=info_all.address, postal_code=info_all.postal_code, website=f"https://{domain}" if domain else None,
            email=None, phone=None, linkedin_url=info_all.linkedin_url, description=description,
            classification_text=combined, contacts=contacts, source_url=pages[0][0], external_id=domain,
            collected_at=now, is_demo=is_demo), raw=raws[0])
        for r in raws[1:]:
            r.processing_status, r.processed_at = "processed", now
        company = self.db.get(Company, out.company_id)
        company.website_last_crawled_at = now
        if out.created:
            self.stats.created += 1
        else:
            self.stats.updated += 1
        self.log(f"{domain}: {'created' if out.created else 'updated'} ({out.match_method}), "
                 f"{out.materials_added} material rows, {out.contacts_added} contacts, {len(pages)} pages")
        self.db.commit()
        return out.company_id
