"""Anti-bot-aware HTTP fetch via ScrapingBee.

Some careers sites (BioNTech behind Cloudflare, Siemens Healthineers behind
Avature's anti-bot edge) refuse plain `requests` and even fail on a vanilla
headless browser. ScrapingBee handles JS rendering, residential IPs and
fingerprinting for us.

Set ``SCRAPINGBEE_API_KEY`` (repo secret + local env var) to activate.
Without the key, ``stealth_get`` returns ``None`` and any caller should
treat the source as "not available this run".

Free tier: 1,000 credits. A JS-rendered call ≈ 5 credits, so stay under
~25 calls/day to comfortably fit a daily cron in the free tier.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger(__name__)

API_BASE = "https://app.scrapingbee.com/api/v1/"
TIMEOUT  = 60          # ScrapingBee can take a while when rendering JS
DEFAULT_PARAMS = {
    "render_js":     "false",
    "premium_proxy": "false",
    "country_code":  "de",
}


def is_enabled() -> bool:
    return bool(os.environ.get("SCRAPINGBEE_API_KEY"))


def stealth_get(url: str, *, render_js: bool = False,
                premium: bool = False,
                country: str = "de",
                wait_for: Optional[str] = None,
                wait_ms: Optional[int] = None) -> Optional[str]:
    """Fetch ``url`` through ScrapingBee. Returns response text or None.

    - ``render_js``: run the page's JS before returning (5 credits)
    - ``premium``  : route through residential IP pool (more expensive,
                     bypasses Cloudflare-tier bot walls)
    - ``country``  : ISO country code for proxy egress
    - ``wait_for`` : CSS selector to wait for before returning
    - ``wait_ms``  : extra wait in ms after page load
    """
    key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not key:
        return None

    params = {
        "api_key":       key,
        "url":           url,
        "render_js":     "true" if render_js else "false",
        "premium_proxy": "true" if premium else "false",
        "country_code":  country,
    }
    if wait_for:
        params["wait_for"] = wait_for
    if wait_ms:
        params["wait"] = str(wait_ms)

    try:
        r = requests.get(API_BASE, params=params, timeout=TIMEOUT)
    except Exception as e:
        log.warning("scrapingbee %s failed: %s", url, e)
        return None
    if r.status_code != 200:
        log.warning("scrapingbee %s -> HTTP %d (%s)", url, r.status_code,
                    r.text[:160].replace("\n", " "))
        return None
    return r.text
