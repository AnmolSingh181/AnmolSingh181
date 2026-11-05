"""Market price connectors.

- FredConnector      key-free (public CSV) or FRED API: US PPI resin indices, crude/gas, and H.10 FX rates.
- DceConnector       Dalian Commodity Exchange official API (key + secret): LLDPE / PP / PVC futures settlements.
- PriceFeedConnector any CSV/JSON URL configured on a series (subscription API, team-maintained sheet).

Every connector writes through services.prices.record_point, keeps the raw payload in raw_records, and only stores
values that appear in the source response.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.connectors.base import BaseConnector, JobStats, NotConfigured
from app.data.reference import FX_SERIES
from app.models import ApiUsage, FxRate, PricePoint, PriceSeries, Source
from app.services.http import PoliteClient
from app.services.ingestion import store_raw
from app.services.prices import _num, record_point, upsert_fx
from app.services.settings_store import get_setting


def _secret(name: str) -> str | None:
    """Process environment first, then backend/.env (pydantic settings do not export .env into os.environ)."""
    v = os.environ.get(name)
    if v:
        return v
    v = getattr(get_settings(), name.lower(), None)
    if v:
        return v
    from dotenv import dotenv_values

    return dotenv_values(".env").get(name) or None


def _series_for(db, source: Source, keys: list[str] | None = None) -> list[PriceSeries]:
    q = select(PriceSeries).where(PriceSeries.source_id == source.id, PriceSeries.is_active)
    if keys:
        q = q.where(PriceSeries.key.in_(keys))
    return list(db.scalars(q.order_by(PriceSeries.id)).all())


def _last_date(db, series_id: int) -> date | None:
    v = db.scalar(select(func.max(PricePoint.observed_at)).where(PricePoint.series_id == series_id))
    return v.date() if v else None


def _start_date(db, series: PriceSeries, params: dict, overlap_days: int) -> date:
    """Re-fetch a small overlap window so publisher revisions are picked up; backfill on first run."""
    if params.get("start"):
        return date.fromisoformat(str(params["start"]))
    last = _last_date(db, series.id)
    if last:
        return last - timedelta(days=overlap_days)
    return date.fromisoformat(get_setting(db, "price_tracking").get("history_start", "2021-01-01"))


# ------------------------------------------------------------------ FRED
class FredConnector(BaseConnector):
    key = "fred"
    job_types = ("refresh", "fetch_series", "fx")
    CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    API_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient(min_delay=0.5)
        self.api_key = _secret("FRED_API_KEY")

    @staticmethod
    def parse_csv(text: str) -> list[tuple[date, float]]:
        """fredgraph.csv: header 'observation_date,<ID>' (older files: 'DATE,<ID>'); missing values are '.'."""
        out = []
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header or len(header) < 2 or header[0].strip().lower() not in ("observation_date", "date"):
            raise ValueError(f"unexpected FRED CSV header: {header}")
        for row in reader:
            if len(row) < 2:
                continue
            v = _num(row[1])
            try:
                d = date.fromisoformat(row[0].strip())
            except ValueError:
                continue
            if v is not None:
                out.append((d, v))
        return out

    @staticmethod
    def parse_json(data: dict) -> list[tuple[date, float]]:
        out = []
        for o in data.get("observations", []) or []:
            v = _num(o.get("value"))
            if v is not None and o.get("date"):
                out.append((date.fromisoformat(o["date"]), v))
        return out

    def fetch(self, series_id: str, start: date) -> tuple[list[tuple[date, float]], str, str]:
        if self.api_key:
            params = {"series_id": series_id, "api_key": self.api_key, "file_type": "json",
                      "observation_start": start.isoformat()}
            r = self.client.api("GET", self.API_URL, params=params)
            r.raise_for_status()
            public_url = f"https://fred.stlouisfed.org/series/{series_id}"
            return self.parse_json(r.json()), r.text, public_url
        r = self.client.api("GET", self.CSV_URL, params={"id": series_id, "cosd": start.isoformat()})
        r.raise_for_status()
        return self.parse_csv(r.text), r.text, f"https://fred.stlouisfed.org/series/{series_id}"

    def run_fx(self, params: dict) -> None:
        wanted = params.get("currencies") or list(FX_SERIES)
        start = date.fromisoformat(str(params["fx_start"])) if params.get("fx_start") else None
        for cur in wanted:
            sid, invert = FX_SERIES.get(cur, (None, False))
            if not sid:
                continue
            last = self.db.scalar(select(func.max(FxRate.rate_date)).where(FxRate.currency == cur))
            st = start or ((last - timedelta(days=10)) if last else
                           date.fromisoformat(get_setting(self.db, "price_tracking").get("history_start", "2021-01-01")))
            try:
                obs, _, _ = self.fetch(sid, st)
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"FX {cur} ({sid}) failed: {exc}", "warning")
                continue
            self.db.add(ApiUsage(provider="fred", operation="fx", units=1))
            n = 0
            for d, v in obs:
                if v <= 0:
                    continue
                created = upsert_fx(self.db, cur, d, (1 / v) if invert else v, f"fred:{sid}")
                n += 1
                self.stats.created += int(created)
            self.stats.found += n
            self.log(f"FX {cur}: {n} daily rates from {sid}")
            self.db.commit()

    def run_series(self, params: dict) -> None:
        for s in _series_for(self.db, self.source, params.get("series_keys")):
            if not s.external_code:
                continue
            start = _start_date(self.db, s, params, overlap_days=120 if s.frequency == "monthly" else 14)
            try:
                obs, raw, url = self.fetch(s.external_code, start)
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"{s.key} ({s.external_code}) failed: {exc}", "warning")
                continue
            self.db.add(ApiUsage(provider="fred", operation="series", units=1))
            rr, _ = store_raw(self.db, self.source, "price_series",
                              {"series": s.external_code, "start": start.isoformat(), "rows": len(obs)},
                              raw_text=raw[:200000], source_url=url, job=self.job)
            for d, v in obs:
                out = record_point(self.db, s, d, v, source_url=url, raw_record_id=rr.id)
                self.stats.found += 1
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created and out.changed)
            self.log(f"{s.key}: {len(obs)} observations since {start}")
            self.db.commit()

    def run(self, job_type: str, params: dict) -> JobStats:
        if job_type in ("refresh", "fx"):
            self.run_fx(params)
        if job_type in ("refresh", "fetch_series"):
            self.run_series(params)
        if not self.api_key:
            self.log("Used FRED public CSV download (no key). Set FRED_API_KEY to use the official JSON API.")
        return self.stats


# ------------------------------------------------------------------ DCE
class DceConnector(BaseConnector):
    """DCE official data API. Endpoints per DCE's API (token: /dceapi/cms/auth/accessToken with header `apikey` and
    body {"secret"}; day quotes: /dceapi/forward/publicweb/dailystat/dayQuotes with Bearer token). Paths and the
    base URL can be overridden in the source config if DCE changes them."""

    key = "dce"
    job_types = ("refresh",)
    TOKEN_PATH = "/dceapi/cms/auth/accessToken"
    QUOTES_PATH = "/dceapi/forward/publicweb/dailystat/dayQuotes"

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient(min_delay=1.0)
        cfg = self.source.config or {}
        self.base = (cfg.get("base_url") or "http://www.dce.com.cn").rstrip("/")
        self.token_path = cfg.get("token_path") or self.TOKEN_PATH
        self.quotes_path = cfg.get("quotes_path") or self.QUOTES_PATH
        self.api_key = _secret("DCE_API_KEY")
        self.secret = _secret("DCE_SECRET")
        self.token: str | None = None

    def status(self) -> dict:
        ok = bool(self.api_key and self.secret)
        return {"ready": ok, "message": "ready" if ok else "Set DCE_API_KEY and DCE_SECRET"}

    @staticmethod
    def _ok(env: dict) -> bool:
        return str(env.get("code", "200")) in ("200", "0") or env.get("success") is True

    def get_token(self) -> str:
        r = self.client.api("POST", self.base + self.token_path, json={"secret": self.secret},
                            headers={"apikey": self.api_key, "Content-Type": "application/json"})
        r.raise_for_status()
        env = r.json()
        data = env.get("data") or {}
        tok = (data.get("token") or data.get("accessToken") or data.get("access_token")) if isinstance(data, dict) \
            else None
        if not self._ok(env) or not tok:
            raise NotConfigured(f"DCE token request rejected: {env.get('msg') or env}")
        return tok

    def day_quotes(self, variety: str, trade_date: date) -> list[dict]:
        body = {"varietyId": variety, "tradeDate": trade_date.strftime("%Y%m%d"), "tradeType": "1", "lang": "en"}
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self.token}", "apikey": self.api_key, "tradeType": "1",
                       "lang": "en", "Content-Type": "application/json"}
            r = self.client.api("POST", self.base + self.quotes_path, json=body, headers=headers)
            r.raise_for_status()
            env = r.json()
            if str(env.get("code")) == "402" and attempt == 0:  # token expired
                self.token = self.get_token()
                continue
            if not self._ok(env):
                raise RuntimeError(f"DCE dayQuotes {variety} {body['tradeDate']}: {env.get('msg') or env.get('code')}")
            data = env.get("data")
            if isinstance(data, dict):  # some responses wrap the list
                data = data.get("list") or data.get("rows") or data.get("data") or []
            return data or []
        return []

    @staticmethod
    def main_contract(rows: list[dict], variety: str) -> dict | None:
        """Most-traded contract = highest open interest among real contracts (subtotal rows have no contract id)."""
        best, best_oi = None, -1.0
        for q in rows:
            cid = str(q.get("contractId") or q.get("contract_id") or "").strip()
            if not cid or not cid.lower().startswith(variety.lower()) or not re.search(r"\d{3,4}$", cid):
                continue
            oi = _num(q.get("openInterest")) or 0.0
            if oi > best_oi:
                best, best_oi = q, oi
        return best

    def run(self, job_type: str, params: dict) -> JobStats:
        if not (self.api_key and self.secret):
            raise NotConfigured("DCE API needs DCE_API_KEY and DCE_SECRET (register for the DCE data API on dce.com.cn)")
        self.ensure_allowed()
        self.token = self.get_token()
        backfill = int(params.get("backfill_days", 30))
        for s in _series_for(self.db, self.source, params.get("series_keys")):
            variety = (s.external_code or "").strip()
            if not variety:
                continue
            if params.get("start"):
                start = date.fromisoformat(str(params["start"]))
            else:  # 2-day overlap re-reads the latest settlements; gaps (worker down) refill up to 120 days
                last = _last_date(self.db, s.id)
                start = max(last - timedelta(days=2) if last else date.today() - timedelta(days=backfill),
                            date.today() - timedelta(days=120))
            d = start
            while d <= date.today():
                if d.weekday() < 5:  # exchange closed at weekends; holidays return no rows
                    try:
                        rows = self.day_quotes(variety, d)
                    except Exception as exc:
                        self.stats.failed += 1
                        self.log(f"{s.key} {d}: {exc}", "warning")
                        d += timedelta(days=1)
                        continue
                    self.db.add(ApiUsage(provider="dce", operation="dayQuotes", units=1))
                    q = self.main_contract(rows, variety)
                    if q:
                        price = _num(q.get("clearPrice")) or _num(q.get("close")) or _num(q.get("lastPrice"))
                        if price:
                            rr, _ = store_raw(self.db, self.source, "price_quote", {"variety": variety,
                                              "date": d.isoformat(), "quote": q}, source_url=self.base, job=self.job)
                            out = record_point(self.db, s, d, price, low=_num(q.get("low")), high=_num(q.get("high")),
                                               volume=_num(q.get("volumn") or q.get("volume")),
                                               open_interest=_num(q.get("openInterest")),
                                               contract=str(q.get("contractId")), source_url="http://www.dce.com.cn/",
                                               note="DCE settlement price, main contract", raw_record_id=rr.id)
                            self.stats.found += 1
                            self.stats.created += int(out.created)
                            self.stats.updated += int(not out.created and out.changed)
                    self.db.commit()
                d += timedelta(days=1)
            self.log(f"{s.key}: fetched {variety} quotes from {start}")
        return self.stats


# ------------------------------------------------------------------ generic feed
_ENV_RE = re.compile(r"\$\{ENV:([A-Z0-9_]+)\}")


def _expand_env(v: str) -> str:
    def rep(m):
        val = _secret(m.group(1))
        if val is None:
            raise NotConfigured(f"environment variable {m.group(1)} is not set")
        return val
    return _ENV_RE.sub(rep, v)


def _dig(obj, path: str | None):
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)]
        else:
            return None
    return obj


class PriceFeedConnector(BaseConnector):
    """Polls `config.feed_url` of each active series attached to this source.

    Series config keys:
      feed_url      CSV or JSON URL (may contain ${ENV:VAR} placeholders)
      format        csv | json (default: guessed from content type)
      json_path     dotted path to the list of records in a JSON response (e.g. "data.prices")
      date_field / price_field / low_field / high_field   column or key names (defaults: date, price, low, high)
      date_format   strptime format if dates are not ISO / common formats
      filter        {"field": "grade", "equals": "LLDPE film"}  keep only matching rows
      headers       {"Authorization": "Bearer ${ENV:MY_FEED_TOKEN}"}
      scale         multiply prices by this (e.g. 0.001 when a feed publishes per tonne but the series is per kg)
    """

    key = "price_feed"
    job_types = ("refresh",)

    def __init__(self, *a, client: PoliteClient | None = None, **kw):
        super().__init__(*a, **kw)
        self.client = client or PoliteClient(min_delay=1.0)

    def records(self, cfg: dict, content_type: str, text: str) -> list[dict]:
        fmt = cfg.get("format") or ("json" if "json" in content_type or text.lstrip()[:1] in "[{" else "csv")
        if fmt == "json":
            import json

            data = _dig(json.loads(text), cfg.get("json_path"))
            if not isinstance(data, list):
                raise ValueError("JSON feed: json_path does not point to a list of records")
            return [r for r in data if isinstance(r, dict)]
        from app.connectors.imports import read_table

        return read_table(text.encode("utf-8"), "feed.csv")[1]

    def parse_rows(self, cfg: dict, rows: list[dict]) -> list[dict]:
        from app.connectors.imports import parse_date

        flt = cfg.get("filter") or {}
        df, pf = cfg.get("date_field", "date"), cfg.get("price_field", "price")
        lf, hf = cfg.get("low_field", "low"), cfg.get("high_field", "high")
        scale = float(cfg.get("scale", 1) or 1)
        out = []
        for r in rows:
            if flt and str(r.get(flt.get("field"), "")).strip().lower() != str(flt.get("equals", "")).strip().lower():
                continue
            raw_d = r.get(df)
            d = None
            if cfg.get("date_format") and raw_d:
                try:
                    d = datetime.strptime(str(raw_d).strip(), cfg["date_format"]).date()
                except ValueError:
                    d = None
            d = d or parse_date(raw_d)
            p = _num(r.get(pf))
            if not d or p is None or p <= 0:
                continue
            lo, hi = _num(r.get(lf)), _num(r.get(hf))
            out.append({"date": d, "price": p * scale, "low": lo * scale if lo else None,
                        "high": hi * scale if hi else None})
        return out

    def run(self, job_type: str, params: dict) -> JobStats:
        series = [s for s in _series_for(self.db, self.source, params.get("series_keys"))
                  if (s.config or {}).get("feed_url")]
        if not series:
            self.log("No active series has a feed_url configured - nothing to poll.")
            return self.stats
        for s in series:
            cfg = s.config or {}
            try:
                url = _expand_env(cfg["feed_url"])
                headers = {k: _expand_env(str(v)) for k, v in (cfg.get("headers") or {}).items()}
                r = self.client.api("GET", url, headers=headers)
                r.raise_for_status()
                rows = self.parse_rows(cfg, self.records(cfg, r.headers.get("content-type", ""), r.text))
            except NotConfigured as exc:
                self.stats.failed += 1
                self.log(f"{s.key}: {exc}", "warning")
                continue
            except Exception as exc:
                self.stats.failed += 1
                self.log(f"{s.key}: feed failed: {exc}", "warning")
                continue
            public_url = _ENV_RE.sub("***", cfg["feed_url"])
            rr, _ = store_raw(self.db, self.source, "price_feed", {"series": s.key, "rows": len(rows)},
                              raw_text=r.text[:200000], source_url=public_url, job=self.job)
            for row in rows:
                out = record_point(self.db, s, row["date"], row["price"], low=row["low"], high=row["high"],
                                   source_url=cfg.get("source_page") or public_url, raw_record_id=rr.id)
                self.stats.found += 1
                self.stats.created += int(out.created)
                self.stats.updated += int(not out.created and out.changed)
            self.log(f"{s.key}: {len(rows)} rows from feed")
            self.db.commit()
        return self.stats
