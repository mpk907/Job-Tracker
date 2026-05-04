"""Generic remote job boards. We query them with digital-pharma keywords
and then keep only entries whose title/description signal a health context."""

from __future__ import annotations

import logging
import time
from typing import Iterator
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; PharmaJobTracker/1.0)"
TIMEOUT = 20

SEARCH_TERMS = [
    "pharma", "biotech", "clinical", "health", "medical", "life sciences",
    "digital health", "medtech", "drug discovery", "genomics", "bioinformatic",
]


def _get(url, **kw):
    return requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=TIMEOUT, **kw)


def fetch_remotive() -> Iterator[dict]:
    seen = set()
    for term in SEARCH_TERMS:
        try:
            r = _get(f"https://remotive.com/api/remote-jobs?{urlencode({'search': term})}")
            r.raise_for_status()
        except Exception as e:
            log.warning("remotive '%s' failed: %s", term, e)
            continue
        for j in r.json().get("jobs", []):
            jid = j.get("id")
            if jid in seen:
                continue
            seen.add(jid)
            yield {
                "title":      j.get("title", ""),
                "company":    j.get("company_name", ""),
                "location":   j.get("candidate_required_location", "Remote"),
                "url":        j.get("url", ""),
                "posted_at":  j.get("publication_date"),
                "tags":       " ".join(j.get("tags", []) or []),
                "external_id": str(jid),
                "source":     "Remotive",
            }
        time.sleep(0.3)


def fetch_remoteok() -> Iterator[dict]:
    """RemoteOK doesn't take a free-text search; we pull tag pages."""
    seen = set()
    for tag in ("health", "medical", "biotech", "pharma"):
        try:
            r = _get(f"https://remoteok.com/api?tags={tag}")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("remoteok '%s' failed: %s", tag, e)
            continue
        for j in data:
            if not isinstance(j, dict) or "id" not in j:
                continue
            if j["id"] in seen:
                continue
            seen.add(j["id"])
            yield {
                "title":      j.get("position", ""),
                "company":    j.get("company", ""),
                "location":   j.get("location", "Remote"),
                "url":        j.get("url") or j.get("apply_url", ""),
                "posted_at":  j.get("date"),
                "tags":       " ".join(j.get("tags", []) or []),
                "external_id": str(j.get("id")),
                "source":     "RemoteOK",
            }
        time.sleep(0.3)


def fetch_arbeitnow() -> Iterator[dict]:
    """Arbeitnow has no industry filter; we filter downstream by keyword."""
    for page in range(1, 6):
        try:
            r = _get(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("arbeitnow page %d failed: %s", page, e)
            break
        items = data.get("data", [])
        if not items:
            break
        for j in items:
            yield {
                "title":      j.get("title", ""),
                "company":    j.get("company_name", ""),
                "location":   j.get("location", "Remote"),
                "url":        j.get("url", ""),
                "posted_at":  j.get("created_at"),
                "tags":       " ".join(j.get("tags", []) or []),
                "external_id": j.get("slug", ""),
                "source":     "Arbeitnow",
            }
        time.sleep(0.3)


def fetch_themuse() -> Iterator[dict]:
    """The Muse public API. Healthcare category covers most of what we want."""
    for page in range(0, 5):
        try:
            r = _get(f"https://www.themuse.com/api/public/jobs?category=Healthcare&page={page}")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("themuse page %d failed: %s", page, e)
            break
        items = data.get("results", [])
        if not items:
            break
        for j in items:
            company = (j.get("company") or {}).get("name", "")
            locs = ", ".join(l.get("name", "") for l in j.get("locations", []) or [])
            yield {
                "title":      j.get("name", ""),
                "company":    company,
                "location":   locs or "Unspecified",
                "url":        (j.get("refs") or {}).get("landing_page", ""),
                "posted_at":  j.get("publication_date"),
                "tags":       ", ".join(t.get("name", "") for t in j.get("tags", []) or []),
                "external_id": str(j.get("id", "")),
                "source":     "TheMuse",
            }
        time.sleep(0.3)


BOARD_FETCHERS = [
    ("Remotive",  fetch_remotive),
    ("RemoteOK",  fetch_remoteok),
    ("Arbeitnow", fetch_arbeitnow),
    ("TheMuse",   fetch_themuse),
]
