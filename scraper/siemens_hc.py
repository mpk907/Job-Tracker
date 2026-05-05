"""Siemens Healthineers adapter — needs ScrapingBee because the careers
portal (jobs.siemens-healthineers.com, served by Avature) is a React SPA
that lazy-loads jobs through a tokenised XHR. We render the page with
JS enabled and parse the resulting DOM.

Strategy:

1. Hit ``/en_US/searchjobs`` with ``render_js=true`` and ``wait_for`` on
   the first job card to let the SPA finish hydrating.
2. Extract job cards from the rendered HTML via regex on the
   anchor pattern Avature emits.
3. Paginate by appending ``?fc=1&fc_id=N&page=N`` until we stop seeing new
   IDs (capped to keep credit use sane).

Without ``SCRAPINGBEE_API_KEY`` the adapter is a no-op.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Iterator

from stealth import is_enabled, stealth_get

log = logging.getLogger(__name__)

LANDING = "https://jobs.siemens-healthineers.com/en_US/searchjobs/"
# Per-page URL pattern Avature assigns to job-card links.
_JOB_LINK_RX = re.compile(
    r'href=["\'](https://jobs\.siemens-healthineers\.com/en_US/[^"\']*?/(\d+)/?)["\']',
    re.I,
)
# Title text usually sits inside the anchor: <a ...><span ...>Title</span>
_TITLE_RX = re.compile(r'<a[^>]+href=["\'][^"\']*\b(\d+)\b[^"\']*["\'][^>]*>(?:[^<]*<[^>]+>)*([^<]+)<', re.I)
_LOC_NEAR_RX = re.compile(r'(?:location|standort|city)[^<]{0,30}<[^>]+>\s*([^<\n]{2,80})', re.I)

PAGE_TEMPLATE = ("https://jobs.siemens-healthineers.com/en_US/searchjobs/"
                 "?folderRecordsPerPage=20&page={page}")


def fetch_siemens_hc(max_pages: int = 5, max_jobs: int = 200) -> Iterator[dict]:
    if not is_enabled():
        log.info("siemens-healthineers: SCRAPINGBEE_API_KEY not set — skipping.")
        return

    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        url = PAGE_TEMPLATE.format(page=page)
        log.info("siemens-hc: page %d", page)

        # Wait for at least one job-detail anchor to render before returning
        html = stealth_get(
            url, render_js=True, premium=True,
            wait_for="a[href*='/en_US/'][href*='/job']",
            wait_ms=4000,
        )
        if not html:
            return

        new_this_page = 0
        # Build a {id: anchor_url} map first
        url_by_id: dict[str, str] = {}
        for full, jid in _JOB_LINK_RX.findall(html):
            url_by_id.setdefault(jid, full)

        # Then pair titles with ids using a second regex pass
        title_by_id: dict[str, str] = {}
        for jid, title in _TITLE_RX.findall(html):
            title = re.sub(r"\s+", " ", title).strip()
            if title and 4 <= len(title) <= 160:
                title_by_id.setdefault(jid, title)

        for jid, link in url_by_id.items():
            if jid in seen:
                continue
            title = title_by_id.get(jid)
            if not title:
                continue
            seen.add(jid); new_this_page += 1
            yield {
                "title":       title,
                "location":    "",        # location lives on the detail page; skip for now
                "url":         link,
                "posted_at":   None,
                "department":  "",
                "external_id": jid,
            }
            if len(seen) >= max_jobs:
                return

        log.info("siemens-hc: page %d -> %d new (%d total)",
                 page, new_this_page, len(seen))
        if new_this_page == 0:
            return
        time.sleep(0.5)
