"""Official trade statistics: US Census International Trade API and UN Comtrade.

These give country-level flows by HS code (market analysis), not company names.
HS 3901.10 = PE SG<0.94 (LDPE + some LLDPE), 3901.20 = PE SG>=0.94 (HDPE), 3901.40 = ethylene-alpha-olefin
copolymers SG<0.94 (mostly LLDPE), 3915.10 = PE waste/scrap. Off-grade/near-prime have no customs code.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.config import get_settings
from app.connectors.base import BaseConnector, JobStats
from app.data.reference import HS_MATERIAL_MAP
from app.models import ApiUsage, Country
from app.services.http import PoliteClient
from app.services.ingestion import resolve_country, store_raw, upsert_trade_statistic

DEFAULT_HS = ["390110", "390120", "390140", "391510"]


def _f(v):
    try:
        return float(v) if v not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _months_back(n: int) -> list[str]:
    """Census data lags ~2 months; start 2 months back."""
    out, y, m = [], date.today().year, date.today().month
    m -= 2
    for _ in range(n):
        while m <= 0:
            m += 12
            y -= 1
        out.append(f"{y}-{m:02d}")
        m -= 1
    return out


class UsCensusConnector(BaseConnector):
    key = "us_census"
    job_types = ("trade_stats",)
    BASE = "https://api.census.gov/data/timeseries/intltrade"

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient(min_delay=1.0)

    def parse(self, rows: list[list], flow: str, period: str, url: str) -> int:
        if not rows or len(rows) < 2:
            return 0
        header = rows[0]
        n = 0
        for r in rows[1:]:
            d = dict(zip(header, r))
            hs = d.get("I_COMMODITY") or d.get("E_COMMODITY")
            cty_code, cty_name = d.get("CTY_CODE", ""), (d.get("CTY_NAME") or "").strip()
            if cty_code in ("-", "") or cty_name.upper().startswith("TOTAL"):
                partner = "W"
            else:
                partner = resolve_country(self.db, cty_name.title()) or resolve_country(self.db, cty_name)
                if not partner:
                    continue  # regional groupings (EU, Pacific Rim, ...) are skipped
            value = _f(d.get("GEN_VAL_MO") or d.get("ALL_VAL_MO"))
            qty = _f(d.get("GEN_QY1_MO") or d.get("QTY_1_MO"))
            created = upsert_trade_statistic(
                self.db, self.source, reporter_country="US", partner_country=partner, partner_name=cty_name.title(),
                flow=flow, hs_code=hs, hs_description=d.get("I_COMMODITY_SDESC") or d.get("E_COMMODITY_SDESC"),
                period=period, value_usd=value, quantity=qty, quantity_unit=d.get("UNIT_QY1"), source_url=url)
            n += 1
            self.stats.created += int(created)
            self.stats.updated += int(not created)
        return n

    def run(self, job_type: str, params: dict) -> JobStats:
        cfg = self.source.config or {}
        hs_codes = params.get("hs_codes") or cfg.get("hs_codes") or DEFAULT_HS
        periods = params.get("periods") or _months_back(int(params.get("months", 3)))
        flows = params.get("flows", ["import", "export"])
        key = get_settings().census_api_key
        for flow in flows:
            endpoint = f"{self.BASE}/{'imports' if flow == 'import' else 'exports'}/hs"
            pre = "I" if flow == "import" else "E"
            fields = ["CTY_CODE", "CTY_NAME", f"{pre}_COMMODITY", f"{pre}_COMMODITY_SDESC",
                      "GEN_VAL_MO" if flow == "import" else "ALL_VAL_MO"]
            qty_fields = cfg.get(f"{flow}_quantity_fields", ["GEN_QY1_MO", "UNIT_QY1"] if flow == "import" else ["QTY_1_MO", "UNIT_QY1"])
            for hs in hs_codes:
                for period in periods:
                    p = {"get": ",".join(fields + qty_fields), "time": period, f"{pre}_COMMODITY": hs}
                    if key:
                        p["key"] = key
                    try:
                        r = self.client.api("GET", endpoint, params=p)
                        if r.status_code == 400 and qty_fields:  # variable not available - retry without quantities
                            p["get"] = ",".join(fields)
                            r = self.client.api("GET", endpoint, params=p)
                        if r.status_code == 204 or not r.text.strip():
                            self.log(f"no data {flow} {hs} {period}")
                            continue
                        r.raise_for_status()
                        rows = r.json()
                    except Exception as exc:
                        self.stats.failed += 1
                        self.log(f"census {flow} {hs} {period} failed: {exc}", "warning")
                        continue
                    self.db.add(ApiUsage(provider="us_census", operation=f"{flow}_hs", units=1))
                    store_raw(self.db, self.source, "trade_stats", {"flow": flow, "hs": hs, "period": period, "rows": rows},
                              source_url=str(r.url), job=self.job)
                    self.stats.found += self.parse(rows, flow, period, str(r.url).split("&key=")[0])
                    self.db.commit()
        return self.stats


class ComtradeConnector(BaseConnector):
    key = "un_comtrade"
    job_types = ("trade_stats",)

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient(min_delay=1.5)

    def parse(self, data: dict, url: str) -> int:
        m49_to_iso = {c.m49_code: c.code for c in self.db.scalars(select(Country)).all() if c.m49_code}
        n = 0
        for d in data.get("data", []) or []:
            rep = m49_to_iso.get(d.get("reporterCode")) or (d.get("reporterISO") or "")[:3]
            pc = d.get("partnerCode")
            partner = "W" if pc == 0 else (m49_to_iso.get(pc) or (d.get("partnerISO") or "")[:3])
            if not rep or not partner:
                continue
            flow = {"M": "import", "X": "export"}.get(d.get("flowCode"))
            if not flow:
                continue
            created = upsert_trade_statistic(
                self.db, self.source, reporter_country=rep, partner_country=partner, partner_name=d.get("partnerDesc"),
                flow=flow, hs_code=str(d.get("cmdCode")), hs_description=d.get("cmdDesc"), period=str(d.get("period")),
                value_usd=_f(d.get("primaryValue")), net_weight_kg=_f(d.get("netWgt")), quantity=_f(d.get("qty")),
                quantity_unit=d.get("qtyUnitAbbr"), source_url=url)
            n += 1
            self.stats.created += int(created)
            self.stats.updated += int(not created)
        return n

    def run(self, job_type: str, params: dict) -> JobStats:
        key = get_settings().comtrade_api_key
        reporters = params.get("reporters")
        if not reporters:
            reporters = [c.m49_code for c in self.db.scalars(select(Country).where(Country.is_active)).all() if c.m49_code]
        hs = params.get("hs_codes") or (self.source.config or {}).get("hs_codes") or DEFAULT_HS
        period = str(params.get("period") or (date.today().year - 1))
        freq = "M" if len(period) == 6 else "A"
        base = (f"https://comtradeapi.un.org/data/v1/get/C/{freq}/HS" if key
                else f"https://comtradeapi.un.org/public/v1/preview/C/{freq}/HS")
        headers = {"Ocp-Apim-Subscription-Key": key} if key else {}
        for rep in reporters:
            p = {"reporterCode": rep, "period": period, "cmdCode": ",".join(hs), "flowCode": "M,X"}
            if params.get("partners", "world") == "world":
                p["partnerCode"] = "0"
            try:
                r = self.client.api("GET", base, params=p, headers=headers)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"comtrade reporter {rep} failed: {exc}", "warning")
                continue
            self.db.add(ApiUsage(provider="un_comtrade", operation="get", units=1))
            store_raw(self.db, self.source, "trade_stats", {"reporter": rep, "period": period, "data": data.get("data", [])},
                      source_url=str(r.url), job=self.job)
            self.stats.found += self.parse(data, str(r.url))
            self.db.commit()
        if not key:
            self.log("Used public preview endpoint (max 500 rows/request). Set COMTRADE_API_KEY for full access.")
        return self.stats


def hs_material(hs: str) -> str | None:
    return HS_MATERIAL_MAP.get((hs or "")[:6], (None, False))[0]
