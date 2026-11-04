"""Connectors that need credentials, a contract, or a terms-of-use review before they can collect data.

They are fully wired into jobs/admin, but refuse to run (NotConfigured / TermsNotConfirmed) until set up.
None of them pretend to work: the Data Sources page shows exactly what is missing.

- TradeApiConnector: ImportYeti / Volza / Panjiva / TradeData.Pro. Their APIs are contract-specific, so the request
  is configured in sources.config["api"] (url, auth header, results path, field map) from the provider's docs.
  Without an API, import their permitted CSV/Excel exports (connectors/imports.py).
- DirectoryConnector: ENF, Plasticker, Plastics Markets, EPDA. Disabled until an admin records that the site's terms
  permit automated collection (sources.config["terms_confirmed"]) and configures CSS selectors for listing pages.
- KompassConnector: Kompass data via API contract only.
- ApolloConnector: decision-maker discovery through the official Apollo API.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import BaseConnector, JobStats, NotConfigured
from app.models import ApiUsage, Company, ScrapeJob, Source
from app.services.contacts import decision_role_for_title, department_for_title
from app.services.http import BlockedError, PoliteClient
from app.services.ingestion import (CompanyInput, ContactInput, ShipmentInput, ingest_company, ingest_shipment,
                                    store_raw, upsert_contact)
from app.services.normalize import extract_domain


def _dig(obj, path: str):
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)] if int(part) < len(obj) else None
        else:
            return None
    return obj


class TradeApiConnector(BaseConnector):
    job_types = ("fetch_shipments",)
    env_key_attr = ""

    def api_key(self) -> str | None:
        return getattr(get_settings(), self.env_key_attr, None)

    def status(self):
        cfg = (self.source.config or {}).get("api")
        if not self.api_key():
            return {"ready": False, "message": f"Awaiting credentials ({self.env_key_attr.upper()}). "
                                               "Meanwhile import permitted CSV/Excel exports."}
        if not cfg or not cfg.get("url"):
            return {"ready": False, "message": "API key set; configure sources.config.api (url, auth_header, results_path, "
                                               "fields) from the provider's API documentation."}
        return {"ready": True, "message": "configured"}

    def run(self, job_type: str, params: dict) -> JobStats:
        st = self.status()
        if not st["ready"]:
            raise NotConfigured(st["message"])
        cfg = self.source.config["api"]
        client = PoliteClient(min_delay=float(cfg.get("min_delay", 2)))
        headers = {cfg.get("auth_header", "Authorization"): cfg.get("auth_prefix", "") + self.api_key()}
        query = {**cfg.get("default_params", {}), **params.get("query", {})}
        r = client.api(cfg.get("method", "GET"), cfg["url"], params=query, headers=headers)
        r.raise_for_status()
        data = r.json()
        self.db.add(ApiUsage(provider=self.key, operation="fetch", units=1,
                             estimated_cost_usd=float(cfg.get("cost_per_request", 0))))
        fields = cfg.get("fields", {})
        for item in _dig(data, cfg.get("results_path", "")) or []:
            self.stats.found += 1
            raw, _ = store_raw(self.db, self.source, "shipment", item, source_url=cfg["url"], job=self.job)
            vals = {k: _dig(item, v) for k, v in fields.items()}
            try:
                from app.connectors.imports import parse_date

                vals["shipment_date"] = parse_date(vals.get("shipment_date"))
                _, created = ingest_shipment(self.db, self.source, ShipmentInput(**{k: v for k, v in vals.items() if v is not None}), raw)
                self.stats.created += int(created)
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"item failed: {exc}", "warning")
        if self.stats.created:
            from app.services.alerts import create_alert

            create_alert(self.db, "new_shipment", f"{self.stats.created} new shipment record(s) from {self.source.name}",
                         entity_type="source", entity_id=self.key)
        self.db.commit()
        return self.stats


class ImportYetiConnector(TradeApiConnector):
    key, env_key_attr = "importyeti", "importyeti_api_key"


class VolzaConnector(TradeApiConnector):
    key, env_key_attr = "volza", "volza_api_key"


class PanjivaConnector(TradeApiConnector):
    key, env_key_attr = "panjiva", "panjiva_api_key"


class TradeDataProConnector(TradeApiConnector):
    key, env_key_attr = "tradedata_pro", "tradedata_pro_api_key"


class DirectoryConnector(BaseConnector):
    """Config-driven listing-page collector, gated on terms confirmation.

    sources.config = {
      "terms_confirmed": true, "terms_confirmed_by": "...", "terms_confirmed_at": "...",
      "list_urls": ["https://.../category/ldpe?page=1", ...],
      "item_selector": ".company-card", "fields": {"name": ".title", "country": ".country", "description": ".desc",
                                                    "website": "a.website@href", "detail_url": "a.title@href"},
      "company_types": ["recycler"], "crawl_websites": true
    }
    """
    job_types = ("collect_directory",)
    requires_terms_confirmation = True

    def status(self):
        cfg = self.source.config or {}
        if not cfg.get("terms_confirmed"):
            return {"ready": False, "message": "Terms of use not yet reviewed/confirmed by an admin."}
        if not cfg.get("list_urls") or not cfg.get("item_selector"):
            return {"ready": False, "message": "Configure list_urls, item_selector and fields."}
        return {"ready": True, "message": "configured"}

    @staticmethod
    def _sel(node, spec: str | None):
        if not spec:
            return None
        css, _, attr = spec.partition("@")
        el = node.select_one(css) if css else node
        if not el:
            return None
        return (el.get(attr) if attr else el.get_text(" ", strip=True)) or None

    def parse_listing(self, html: str, page_url: str) -> list[dict]:
        cfg = self.source.config
        soup = BeautifulSoup(html, "lxml")
        out = []
        for node in soup.select(cfg["item_selector"]):
            item = {k: self._sel(node, v) for k, v in cfg.get("fields", {}).items()}
            if item.get("name"):
                item["page_url"] = page_url
                out.append(item)
        return out

    def run(self, job_type: str, params: dict) -> JobStats:
        self.ensure_allowed()
        st = self.status()
        if not st["ready"]:
            raise NotConfigured(st["message"])
        cfg = self.source.config
        client = PoliteClient()
        crawl_src = self.db.scalar(select(Source).where(Source.key == "company_website"))
        for url in cfg["list_urls"][: int(params.get("max_pages", 20))]:
            try:
                r = client.get(url)
            except BlockedError as exc:
                self.log(str(exc), "warning")
                self.stats.failed += 1
                break  # stop on block - never try to get around it
            if r.status_code != 200:
                self.stats.failed += 1
                continue
            for item in self.parse_listing(r.text, str(r.url)):
                self.stats.found += 1
                raw, _ = store_raw(self.db, self.source, "directory_listing", item, source_url=item["page_url"], job=self.job)
                out = ingest_company(self.db, self.source, CompanyInput(
                    name=item["name"], country=item.get("country"), city=item.get("city"), website=item.get("website"),
                    description=item.get("description"), classification_text=item.get("description"),
                    company_types=cfg.get("company_types", []), source_url=item.get("detail_url") or item["page_url"]),
                    raw=raw)
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created)
                if cfg.get("crawl_websites") and item.get("website") and crawl_src:
                    self.db.add(ScrapeJob(source_id=crawl_src.id, job_type="crawl_website", priority=60,
                                          params={"url": item["website"], "country": item.get("country")}))
            self.db.commit()
        return self.stats


class KompassConnector(DirectoryConnector):
    key = "kompass"
    requires_terms_confirmation = False

    def status(self):
        if not get_settings().kompass_api_key:
            return {"ready": False, "message": "Awaiting Kompass API contract (KOMPASS_API_KEY). Import permitted exports meanwhile."}
        return super().status()


class ApolloConnector(BaseConnector):
    """Decision-maker discovery through the official Apollo API.

    1. People API Search (no credits): people at the company's domain with buying/selling titles. Apollo returns
       these partly masked (no email, shortened last name).
    2. People Enrichment (uses Apollo credits): reveals name, email and LinkedIn for those people. Capped per run with
       params.max_enrich (default 25); a person is never enriched twice (tracked via raw records).
    Endpoints can be overridden in sources.config (search_url, enrich_url) if Apollo changes them.
    """
    key = "apollo"
    job_types = ("enrich_contacts",)
    SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
    ENRICH_URL = "https://api.apollo.io/api/v1/people/match"
    TITLES = ["procurement manager", "purchasing manager", "purchase manager", "raw material buyer", "purchase director",
              "sales manager", "export manager", "import manager", "commercial director", "managing director",
              "business development manager"]

    def status(self):
        if not get_settings().apollo_api_key:
            return {"ready": False, "message": "Awaiting APOLLO_API_KEY."}
        return {"ready": True, "message": "configured"}

    def _post(self, client, url, body):
        r = client.api("POST", url, json=body, headers={"X-Api-Key": get_settings().apollo_api_key,
                                                          "Content-Type": "application/json", "Cache-Control": "no-cache"})
        if r.status_code in (401, 403):
            raise NotConfigured(
                f"Apollo refused the key ({r.status_code}: {r.text[:200]}). Create the key with 'Set as master key' "
                "(or grant the People API Search and People Enrichment endpoints) and check your plan includes API access.")
        if r.status_code == 429:
            raise RuntimeError("Apollo rate limit / credit limit reached (429); will retry later")
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _clean_email(email):
        if not email or "not_unlocked" in email or "domain.com" in email or "@" not in email:
            return None
        return email

    def run(self, job_type: str, params: dict) -> JobStats:
        from app.models import Contact, RawRecord

        if not get_settings().apollo_api_key:
            raise NotConfigured("Awaiting APOLLO_API_KEY")
        cfg = self.source.config or {}
        search_url, enrich_url = cfg.get("search_url", self.SEARCH_URL), cfg.get("enrich_url", self.ENRICH_URL)
        enrich, max_enrich = params.get("enrich", True), int(params.get("max_enrich", 25))
        client = self._client if getattr(self, "_client", None) else PoliteClient(min_delay=1.0)
        has_person = select(Contact.company_id).where(Contact.contact_type == "individual")
        q = select(Company).where(Company.status == "active", Company.domain.is_not(None), Company.is_demo.is_(False))
        if params.get("company_ids"):
            q = q.where(Company.id.in_(params["company_ids"]))
        else:  # best leads that still lack a named contact first
            q = q.order_by(Company.id.in_(has_person), Company.lead_score.desc().nullslast()).limit(int(params.get("limit", 25)))
        enriched = 0
        for company in self.db.scalars(q).all():
            try:
                data = self._post(client, search_url, {"q_organization_domains_list": [company.domain],
                                                       "person_titles": params.get("titles", self.TITLES),
                                                       "page": 1, "per_page": int(params.get("per_company", 5))})
            except NotConfigured:
                raise
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"{company.domain}: search failed: {exc}", "warning")
                continue
            people = data.get("people") or []
            self.db.add(ApiUsage(provider="apollo", operation="people_search", units=1))
            store_raw(self.db, self.source, "people_search", {"domain": company.domain, "people": people},
                      source_url=search_url, job=self.job)
            for p in people:
                self.stats.found += 1
                pid = p.get("id")
                email, linkedin, name, title = self._clean_email(p.get("email")), p.get("linkedin_url"), p.get("name"), p.get("title")
                if not (email or linkedin) and enrich and pid and enriched < max_enrich:
                    done = self.db.scalar(select(RawRecord.id).where(RawRecord.source_id == self.source.id,
                                                                     RawRecord.record_type == "people_match",
                                                                     RawRecord.external_id == pid))
                    if not done:
                        try:
                            person = (self._post(client, enrich_url, {"id": pid, "reveal_personal_emails": False})
                                      .get("person") or {})
                        except NotConfigured:
                            raise
                        except Exception as exc:
                            self.log(f"enrich {pid} failed: {exc}", "warning")
                            person = {}
                        enriched += 1
                        self.db.add(ApiUsage(provider="apollo", operation="people_enrichment", units=1))
                        store_raw(self.db, self.source, "people_match", person or {"id": pid}, source_url=enrich_url,
                                  external_id=pid, job=self.job)
                        email = self._clean_email(person.get("email")) or email
                        linkedin = person.get("linkedin_url") or linkedin
                        name = person.get("name") or name
                        title = person.get("title") or title
                if not (email or linkedin):
                    continue
                if name and not (p.get("last_name") or "").strip() and name == p.get("name") and "." in (name.split()[-1] if name.split() else ""):
                    name = None  # masked search result name - don't store a shortened name as fact
                added = upsert_contact(self.db, company, ContactInput(
                    contact_type="individual", full_name=name, job_title=title, department=department_for_title(title),
                    email=email, linkedin_url=linkedin, decision_role=decision_role_for_title(title),
                    evidence=f"Apollo people search/enrichment for {company.domain}", source_url="https://app.apollo.io/"),
                    self.source, None)
                self.stats.created += int(added)
            self.db.commit()
        self.log(f"Apollo: {self.stats.found} people found, {enriched} enriched (credits), {self.stats.created} contacts added")
        return self.stats

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self._client = client


def make_directory(key: str):
    return type(f"{key.title().replace('_', '')}Connector", (DirectoryConnector,), {"key": key})
