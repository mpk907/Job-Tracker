"""Sitemap-based scraper for companies whose careers pages run on Phenom
People (Roche, AbbVie, Eli Lilly et al). The widget API on those sites
needs reverse-engineered tenant headers, but the sitemap is open and
spells the job title into the URL slug, e.g.

    /global/en/job/ROCHGLOBAL202602103822EXTERNALENGLOBAL/Senior-AI-Scientist-Drug-Product

We only get title + URL out of the sitemap; location and department come
from a single follow-up GET when needed. To stay polite we cap the per-
company URL count and put a small delay between page fetches.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Iterator
from urllib.parse import unquote

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; PharmaJobTracker/1.0)"
TIMEOUT = 25

# Companies whose careers-site sitemap exposes job slugs.
# `url_pattern` is `(id, slug)` capture — order matches what _slug_to_title
# expects to receive from group 2.
SITEMAP_SOURCES = [
    {
        "name":     "Roche",
        "type":     "big_pharma",
        "country":  "CH",
        "sitemaps": [
            "https://careers.roche.com/global/en/sitemap1.xml",
            "https://careers.roche.com/global/en/sitemap2.xml",
            "https://careers.roche.com/global/en/sitemap3.xml",
        ],
        # /global/en/job/{ID}/{slug}
        "url_pattern":  r"^https://careers\.roche\.com/global/en/job/([^/]+)/(.+)$",
    },
    {
        "name":     "AbbVie",
        "type":     "big_pharma",
        "country":  "US",
        "sitemaps": [
            "https://careers.abbvie.com/en/vacanciessitemap.xml",
        ],
        # /en/job/{slug}-jid-{id}
        "url_pattern":  r"^https://careers\.abbvie\.com/en/job/(.+)-jid-(\d+)/?$",
        "id_group":     2,
        "slug_group":   1,
    },
    {
        "name":     "Johnson & Johnson",
        "type":     "big_pharma",
        "country":  "US",
        "sitemaps": [
            "https://www.careers.jnj.com/sitemap.xml",
        ],
        # only the English locale to avoid the same job being yielded
        # 8× from different language paths
        "url_pattern":  r"^https://www\.careers\.jnj\.com/en/jobs/([^/]+)/(.+?)/?$",
    },
]


_SLUG_TO_TITLE = re.compile(r"[-_]+")


def _slug_to_title(slug: str) -> str:
    """Transform 'Senior-AI-Scientist-Drug-Product' → 'Senior AI Scientist Drug Product'."""
    s = unquote(slug)
    s = _SLUG_TO_TITLE.sub(" ", s).strip()
    # Collapse repeated spaces left from leading hyphens etc
    s = re.sub(r"\s{2,}", " ", s)
    return s


_LOC_RX_LIST = [
    re.compile(r"<meta[^>]+property=[\"']og:locality[\"'][^>]+content=[\"']([^\"']+)", re.I),
    re.compile(r"\"jobLocation\"[^}]+\"addressLocality\"\s*:\s*\"([^\"]+)\"", re.I),
    re.compile(r"<meta[^>]+name=[\"']location[\"'][^>]+content=[\"']([^\"']+)", re.I),
]


def _enrich_location(url: str) -> str:
    """Single follow-up GET to read the location from the job page meta."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception:
        return ""
    text = r.text
    for rx in _LOC_RX_LIST:
        m = rx.search(text)
        if m:
            return m.group(1).strip()
    return ""


def _fetch_sitemap_urls(sitemap_url: str) -> list[str]:
    """Pulls <loc> URLs out of an XML sitemap (no XML parser needed)."""
    try:
        r = requests.get(sitemap_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log.warning("sitemap %s failed: %s", sitemap_url, e)
        return []
    return re.findall(r"<loc>([^<]+)</loc>", r.text)


def fetch_sitemap_jobs(source: dict, *, max_jobs: int = 800,
                       enrich_locations: bool = True,
                       max_enrich: int = 200) -> Iterator[dict]:
    """Yield raw job rows for one Phenom-style sitemap source."""
    seen = set()
    pat = re.compile(source["url_pattern"])
    id_group   = source.get("id_group", 1)
    slug_group = source.get("slug_group", 2)
    enriched = 0
    matched = 0

    for sm in source["sitemaps"]:
        urls = _fetch_sitemap_urls(sm)
        for url in urls:
            m = pat.match(url)
            if not m:
                continue
            ext_id = m.group(id_group)
            slug   = m.group(slug_group)
            if ext_id in seen:
                continue
            seen.add(ext_id)
            matched += 1
            title = _slug_to_title(slug)
            if not title:
                continue

            location = ""
            if enrich_locations and enriched < max_enrich:
                location = _enrich_location(url)
                enriched += 1
                time.sleep(0.15)

            yield {
                "title":      title,
                "location":   location,
                "url":        url,
                "posted_at":  None,
                "department": "",
                "external_id": ext_id,
            }
            if matched >= max_jobs:
                return


def fetch_all_sitemaps(*, enrich_locations: bool = True) -> Iterator[tuple[dict, list[dict]]]:
    """Yields (source_meta, [raw_rows]) for each configured sitemap source."""
    for source in SITEMAP_SOURCES:
        rows = list(fetch_sitemap_jobs(source, enrich_locations=enrich_locations))
        yield source, rows
