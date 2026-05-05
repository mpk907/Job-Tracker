"""BioNTech adapter — needs ScrapingBee because careers.biontech.com is
behind a strict TLS/SNI bot wall that even rejects a vanilla headless
Chromium.

Strategy:

1. Pull the sitemap (or its index) through Stealth.
2. Filter to job-detail URLs.
3. For each URL we can extract the title from the slug; location comes
   from a follow-up GET on a small sample (capped to keep credit usage
   sane).

Without ``SCRAPINGBEE_API_KEY`` the adapter is a no-op.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Iterator
from urllib.parse import unquote

from stealth import is_enabled, stealth_get

log = logging.getLogger(__name__)

SITEMAP_URLS = [
    "https://careers.biontech.com/sitemap.xml",
    "https://careers.biontech.com/sitemap_index.xml",
    "https://careers.biontech.com/de/sitemap.xml",
    "https://careers.biontech.com/en/sitemap.xml",
]

# Job-detail URL patterns BioNTech is known to use. The slug carries the
# title (slightly URL-encoded). We'll cover both /de/ and /en/ paths.
_JOB_URL_RX = re.compile(
    r"^https://careers\.biontech\.com/(?:en|de|gb)/jobs?/([0-9A-Z_-]+)/(.+?)/?$",
    re.I,
)
_LOC_FROM_HTML_RX = [
    re.compile(r"\"jobLocation\"[^}]+\"addressLocality\"\s*:\s*\"([^\"]+)\"", re.I),
    re.compile(r"<meta[^>]+property=[\"']og:locality[\"'][^>]+content=[\"']([^\"']+)", re.I),
]
_SLUG_TO_TITLE_RX = re.compile(r"[-_]+")
_LOC_LINE_RX = re.compile(r"location[^<]{0,40}<[^>]+>\s*([A-Z][a-zA-ZäöüÄÖÜ ,/-]+)", re.I)


def _slug_to_title(slug: str) -> str:
    s = unquote(slug)
    return re.sub(r"\s{2,}", " ", _SLUG_TO_TITLE_RX.sub(" ", s)).strip()


def _extract_loc(html: str) -> str:
    for rx in _LOC_FROM_HTML_RX:
        m = rx.search(html)
        if m:
            return m.group(1).strip()
    m = _LOC_LINE_RX.search(html)
    return m.group(1).strip() if m else ""


def _extract_urls(sitemap_xml: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", sitemap_xml or "")


def fetch_biontech(max_jobs: int = 500, max_enrich: int = 30) -> Iterator[dict]:
    if not is_enabled():
        log.info("biontech: SCRAPINGBEE_API_KEY not set — skipping.")
        return

    seen: set[str] = set()
    enriched = 0

    # 1) Find a working sitemap (premium proxy needed for Cloudflare-edge).
    sitemap_xml = None
    for sm in SITEMAP_URLS:
        body = stealth_get(sm, premium=True)
        if body and "<loc>" in body:
            sitemap_xml = body
            log.info("biontech: sitemap source = %s", sm)
            break
    if not sitemap_xml:
        log.warning("biontech: no sitemap reachable")
        return

    # 2) The top-level sitemap is often an index pointing at child files.
    candidate_urls: list[str] = []
    for url in _extract_urls(sitemap_xml):
        if url.endswith(".xml") and "sitemap" in url.lower():
            child = stealth_get(url, premium=True)
            if child:
                candidate_urls.extend(_extract_urls(child))
                time.sleep(0.5)
        else:
            candidate_urls.append(url)

    # 3) Filter, dedupe, optionally enrich.
    for url in candidate_urls:
        m = _JOB_URL_RX.match(url)
        if not m:
            continue
        ext_id, slug = m.group(1), m.group(2)
        if ext_id in seen:
            continue
        seen.add(ext_id)
        title = _slug_to_title(slug)
        if not title:
            continue

        location = ""
        if enriched < max_enrich:
            html = stealth_get(url, render_js=True, premium=True, wait_ms=2000)
            enriched += 1
            if html:
                location = _extract_loc(html)
            time.sleep(0.4)

        yield {
            "title":       title,
            "location":    location,
            "url":         url,
            "posted_at":   None,
            "department":  "",
            "external_id": ext_id,
        }
        if len(seen) >= max_jobs:
            return
