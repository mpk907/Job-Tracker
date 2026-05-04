"""ATS adapters. Each returns an iterable of raw job dicts that get
normalized in run.py into the common schema."""

from __future__ import annotations

import logging
import time
from typing import Iterator
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (compatible; PharmaJobTracker/1.0; "
    "+https://github.com/mpk907/job-tracker)"
)
TIMEOUT = 30


def _get(url: str, **kw):
    return requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=TIMEOUT, **kw)


def _post(url: str, json=None, **kw):
    return requests.post(url, json=json,
                         headers={"User-Agent": UA, "Accept": "application/json",
                                  "Content-Type": "application/json"},
                         timeout=TIMEOUT, **kw)


# ----- Greenhouse ---------------------------------------------------------
def fetch_greenhouse(slug: str) -> Iterator[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = _get(url)
    r.raise_for_status()
    for job in r.json().get("jobs", []):
        yield {
            "title":      job.get("title", ""),
            "location":   (job.get("location") or {}).get("name", ""),
            "url":        job.get("absolute_url", ""),
            "posted_at":  job.get("updated_at") or job.get("first_published"),
            "department": ", ".join(d["name"] for d in job.get("departments", [])),
            "external_id": str(job.get("id", "")),
        }


# ----- Lever --------------------------------------------------------------
def fetch_lever(slug: str) -> Iterator[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = _get(url)
    r.raise_for_status()
    for job in r.json():
        cats = job.get("categories", {}) or {}
        yield {
            "title":      job.get("text", ""),
            "location":   cats.get("location", "") or ", ".join(cats.get("allLocations", []) or []),
            "url":        job.get("hostedUrl", ""),
            "posted_at":  _epoch_ms_to_iso(job.get("createdAt")),
            "department": cats.get("team") or cats.get("department", ""),
            "external_id": job.get("id", ""),
        }


def _epoch_ms_to_iso(ms):
    if not ms:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))
    except Exception:
        return None


# ----- Ashby --------------------------------------------------------------
def fetch_ashby(slug: str) -> Iterator[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    r = _get(url)
    r.raise_for_status()
    for job in r.json().get("jobs", []):
        yield {
            "title":      job.get("title", ""),
            "location":   job.get("location", "") or job.get("locationName", ""),
            "url":        job.get("jobUrl") or job.get("applyUrl", ""),
            "posted_at":  job.get("publishedAt") or job.get("updatedAt"),
            "department": job.get("department", "") or job.get("team", ""),
            "external_id": job.get("id", ""),
        }


# ----- SmartRecruiters ----------------------------------------------------
def fetch_smartrecruiters(slug: str) -> Iterator[dict]:
    base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    offset, limit = 0, 100
    while True:
        r = _get(f"{base}?{urlencode({'limit': limit, 'offset': offset})}")
        r.raise_for_status()
        data = r.json()
        for job in data.get("content", []):
            loc = job.get("location") or {}
            yield {
                "title":      job.get("name", ""),
                "location":   ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
                "url":        (job.get("ref") or "").replace("api.smartrecruiters.com/v1/companies",
                                                              "jobs.smartrecruiters.com")
                              or f"https://jobs.smartrecruiters.com/{slug}/{job.get('id','')}",
                "posted_at":  job.get("releasedDate") or job.get("createdOn"),
                "department": (job.get("department") or {}).get("label", ""),
                "external_id": job.get("id", ""),
            }
        offset += limit
        if offset >= data.get("totalFound", 0):
            break


# ----- Workday ------------------------------------------------------------
# Workday's CXS API takes a `searchText` field that maps onto its native
# search. We split our digital keyword set into ~6 server-side queries so
# we only ever paginate over the small pre-filtered slice. Without this,
# tenants like CVS Health (14k+ jobs) would take 700+ requests.
WORKDAY_QUERIES = ["digital", "data", "engineer", "software", "product", "analytics"]
WORKDAY_MAX_PAGES = 25  # 25 pages * 20 jobs = 500 results per query


def fetch_workday(host: str, tenant: str, site: str) -> Iterator[dict]:
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    seen = set()
    for query in WORKDAY_QUERIES:
        offset, limit = 0, 20
        for _ in range(WORKDAY_MAX_PAGES):
            try:
                r = _post(url, json={"appliedFacets": {}, "limit": limit,
                                     "offset": offset, "searchText": query})
                r.raise_for_status()
            except Exception as e:
                log.warning("workday %s/%s '%s' offset=%d: %s",
                            tenant, site, query, offset, e)
                break
            data = r.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break
            for job in postings:
                bid = (job.get("bulletFields") or [""])[0]
                key = bid or job.get("externalPath", "") or job.get("title", "")
                if key in seen:
                    continue
                seen.add(key)
                ext = job.get("externalPath", "")
                yield {
                    "title":      job.get("title", ""),
                    "location":   job.get("locationsText", ""),
                    "url":        f"https://{host}{ext}" if ext else "",
                    "posted_at":  job.get("postedOn", ""),
                    "department": "",
                    "external_id": bid,
                }
            offset += limit
            if offset >= data.get("total", 0):
                break


# ----- Dispatch -----------------------------------------------------------
ADAPTERS = {
    "greenhouse":      lambda c: fetch_greenhouse(c["slug"]),
    "lever":           lambda c: fetch_lever(c["slug"]),
    "ashby":           lambda c: fetch_ashby(c["slug"]),
    "smartrecruiters": lambda c: fetch_smartrecruiters(c["slug"]),
    "workday":         lambda c: fetch_workday(c["host"], c["tenant"], c["site"]),
}


def fetch_company(company: dict) -> list[dict]:
    ats = company["ats"]
    if ats not in ADAPTERS:
        raise ValueError(f"Unknown ATS: {ats}")
    return list(ADAPTERS[ats](company))
