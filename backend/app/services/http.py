"""Polite HTTP client: robots.txt, per-host rate limiting, identification, challenge-page detection.
It never attempts to bypass CAPTCHAs, logins or anti-bot protections - such pages raise BlockedError."""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = ("cf-chl", "challenge-platform", "g-recaptcha", "hcaptcha", "captcha", "verify you are human",
                     "access denied", "attention required", "please enable cookies", "ddos-guard", "px-captcha")


class BlockedError(Exception):
    """robots.txt disallow, auth wall, CAPTCHA or anti-bot challenge - stop, do not retry."""


class PoliteClient:
    def __init__(self, min_delay: float | None = None, user_agent: str | None = None, timeout: float | None = None,
                 respect_robots: bool = True, transport: httpx.BaseTransport | None = None):
        s = get_settings()
        self.min_delay = s.crawler_min_delay_seconds if min_delay is None else min_delay
        self.user_agent = user_agent or s.crawler_user_agent
        self.respect_robots = respect_robots
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.client = httpx.Client(timeout=timeout or s.crawler_timeout_seconds, follow_redirects=True,
                                   headers={"User-Agent": self.user_agent, "Accept-Language": "en;q=0.9,*;q=0.5"},
                                   transport=transport)
        self.requests_made = 0

    def close(self):
        self.client.close()

    def _wait(self, host: str):
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < self.min_delay:
                time.sleep(self.min_delay - delta)
        self._last[host] = time.monotonic()

    def robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait(p.netloc)
                r = self.client.get(urljoin(base, "/robots.txt"))
                self.requests_made += 1
                if r.status_code in (401, 403):
                    rp.parse(["User-agent: *", "Disallow: /"])
                elif r.status_code >= 400:
                    rp.parse([])
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp = None  # unreachable robots: treat as allowed only if the page itself is reachable
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self.robots(url)
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def sitemaps(self, url: str) -> list[str]:
        rp = self.robots(url)
        return list(rp.site_maps() or []) if rp else []

    def get(self, url: str, check_robots: bool = True, **kw) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise BlockedError(f"robots.txt disallows {url}")
        self._wait(urlparse(url).netloc)
        r = self.client.get(url, **kw)
        self.requests_made += 1
        if r.status_code in (401, 407):
            raise BlockedError(f"authentication required at {url}")
        if r.status_code in (403, 429, 503):
            body = r.text[:5000].lower() if "text" in r.headers.get("content-type", "") else ""
            if any(m in body for m in CHALLENGE_MARKERS) or r.status_code in (403, 429):
                raise BlockedError(f"access blocked ({r.status_code}) at {url}")
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            head = r.text[:4000].lower()
            if any(m in head for m in ("cf-chl", "challenge-platform", "px-captcha", "ddos-guard")):
                raise BlockedError(f"anti-bot challenge at {url}")
        return r

    def api(self, method: str, url: str, **kw) -> httpx.Response:
        """Official API calls (no robots check), still rate-limited."""
        self._wait(urlparse(url).netloc)
        r = self.client.request(method, url, **kw)
        self.requests_made += 1
        return r
