"""Adzuna API adapter — fills the gap for companies that hide behind anti-bot
or use proprietary career portals (Roche, Bayer, BI, BioNTech, Siemens
Healthineers, J&J, AbbVie, …).

Adzuna is a public free-tier API (sign-up at developer.adzuna.com).
Set ADZUNA_APP_ID and ADZUNA_APP_KEY in env / GitHub secrets.

We hit two kinds of queries:

1. **Broad country sweeps** — `country=de, what=pharma` returns hundreds
   of jobs from many companies in one call. We do a small set of these
   per country (pharma / biotech / clinical / digital health / medtech)
   and let our client-side `is_digital` + `is_health_related` filters do
   the rest. Most efficient use of the free 250 calls/day quota.

2. **Targeted company queries** — for the largest pharma whose careers
   pages we couldn't scrape directly (Roche, Bayer, BI, BioNTech …)
   we hit `country=X, company=NAME` so we never miss them even when
   broad sweeps overflow.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Iterator
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

UA = "PharmaJobTracker/1.0 (+https://github.com/mpk907/job-tracker)"
TIMEOUT = 25
# Free Adzuna tier ≈ 250 calls/day per app. Defaults below come in well
# under that:
#   targeted ~80 entries × avg ~2 countries × 1 page  ≈ 160 calls
#   topic    1 country × 1 topic × 1 page              ≈ 0–6 calls
#   reserve  ~80 calls/day for retries / next-day burst
MAX_PAGES = 1                # 50 results per (company,country) is plenty
RESULTS_PER_PAGE = 50
RATE_LIMIT_BUDGET = 220      # hard stop just below the daily limit

# Two-letter ISO country codes Adzuna supports & we care about.
DACH_AND_EU = ["ch", "de", "at", "fr", "nl", "be", "it", "es", "pl", "gb", "ie"]
ANGLO_LARGE = ["us", "ca", "au", "in", "sg"]

# Broad sweeps — one per (country, topic). 11×6 = 66 calls/day if all run.
# Override via ADZUNA_COUNTRIES env var (comma-separated).
DEFAULT_TOPICS = [
    "pharma",
    "biotech",
    "clinical trial",
    "digital health",
    "medical device",
    "life sciences",
]

# Targeted lookups for companies behind Incapsula / proprietary portals.
TARGETED = [
    # name (must match Adzuna's company.display_name reasonably)  | countries
    ("Roche",                 ["ch", "de", "us"]),
    ("Genentech",             ["us"]),
    ("Bayer",                 ["de", "us"]),
    ("Boehringer Ingelheim",  ["de", "us", "at"]),
    ("BioNTech",              ["de", "us"]),
    ("Siemens Healthineers",  ["de", "us"]),
    ("Johnson & Johnson",     ["us", "de", "ch"]),
    ("AbbVie",                ["us", "de", "ch"]),
    ("Bristol Myers Squibb",  ["us", "de", "ch"]),
    ("Novo Nordisk",          ["de", "us", "gb"]),
    ("Teva",                  ["de", "us"]),
    ("Vertex Pharmaceuticals","us", ),
    ("Regeneron",             ["us"]),
    ("Gilead",                ["us"]),
    ("Biogen",                ["us"]),
    ("UCB",                   ["be", "de", "us"]),
    ("Lundbeck",              ["de", "us"]),
    ("Ipsen",                 ["fr", "us"]),
    ("Genmab",                ["us"]),
    ("Galapagos",             ["be", "nl"]),
    ("CSL",                   ["au", "de", "us"]),
    ("IQVIA",                 ["us", "de", "ch"]),
    ("Parexel",               ["us", "de"]),
    ("Syneos Health",         ["us"]),
    ("ICON plc",              ["ie", "us"]),
    ("Veeva",                 ["us", "de"]),
    ("Medable",               ["us"]),
    ("Indegene",              ["in", "us"]),
    ("Medtronic",             ["us", "ie", "de"]),
    ("Abbott",                ["us", "de"]),
    ("GE Healthcare",         ["us", "de"]),
    ("Philips",               ["nl", "de", "us"]),
    ("Stryker",               ["us"]),
    ("Boston Scientific",     ["us", "de"]),
    ("Becton Dickinson",      ["us", "de"]),
    ("Dexcom",                ["us"]),
    ("Edwards Lifesciences",  ["us"]),
    ("Thermo Fisher",         ["us", "de", "ch"]),
    ("Illumina",              ["us", "de", "gb"]),
    ("Guardant Health",       ["us"]),
    ("Exact Sciences",        ["us"]),
    ("Hologic",               ["us"]),
    ("Olympus",               ["de", "us"]),
    ("Drägerwerk",            ["de"]),
    ("Smith Nephew",          ["gb", "us"]),
    ("Zimmer Biomet",         ["us", "de"]),
    ("Coloplast",             ["de"]),
    ("Carl Zeiss",            ["de"]),
    ("Brainlab",              ["de", "us"]),
    ("Charité",               ["de"]),
    ("Helios",                ["de"]),
    ("Asklepios",             ["de"]),
    ("Sana Kliniken",         ["de"]),
    ("UnitedHealth",          ["us"]),
    ("Optum",                 ["us"]),
    ("Cigna",                 ["us"]),
    ("Humana",                ["us"]),
    ("Elevance",              ["us"]),
    ("Centene",               ["us"]),
    ("McKesson",              ["us"]),
    ("Cardinal Health",       ["us"]),
    ("AOK",                   ["de"]),
    ("Techniker Krankenkasse","de"),
    ("Sun Pharma",            ["in"]),
    ("Cipla",                 ["in"]),
    ("Dr Reddys",             ["in"]),
    ("Lupin",                 ["in"]),
    ("Aurobindo",             ["in"]),
    ("Biocon",                ["in"]),
    ("Atai Life Sciences",    ["de", "us"]),
    ("Doctolib",              ["fr", "de"]),
    ("Babylon",               ["gb", "us"]),
    ("Doccla",                ["gb"]),
    ("Ada Health",            ["de"]),
    ("Caresyntax",            ["de"]),
    ("Climedo",               ["de"]),
    ("Heartbeat Medical",     ["de"]),
    ("Avi Medical",           ["de"]),
    ("Patient21",             ["de"]),
    ("Teleclinic",            ["de"]),
    ("Compugroup Medical",    ["de"]),
    ("Kry",                   ["de", "gb"]),
    ("Hinge Health",          ["us"]),
    ("Hims",                  ["us"]),
    ("Lyra Health",           ["us"]),
    ("Spring Health",         ["us"]),
    ("Calm",                  ["us"]),
    ("Headspace",             ["us"]),
    ("23andMe",               ["us"]),
    ("Aidoc",                 ["us"]),
    ("BenevolentAI",          ["gb"]),
    ("Exscientia",            ["gb"]),
    ("Atomwise",              ["us"]),
    ("Schrödinger",           ["us"]),
]


def _get(url: str, params: dict) -> requests.Response:
    return requests.get(url, params=params, headers={"User-Agent": UA},
                        timeout=TIMEOUT)


_LAND_RX = re.compile(r"^(https?://www\.adzuna\.[a-z.]+)/land/ad/(\d+)")


def _clean_url(url: str) -> str:
    """Adzuna's redirect_url comes in two flavours:

      /details/{id}            → public job-detail page, always renders
      /land/ad/{id}?se=…&v=…   → click-tracker page that 403s for bots and
                                  occasionally for real users when the
                                  tracker's signed token expires.

    Rewrite the second form to the first so apply links don't break.
    """
    m = _LAND_RX.match(url or "")
    return f"{m.group(1)}/details/{m.group(2)}" if m else url


def _normalize(j: dict) -> dict:
    company = (j.get("company") or {}).get("display_name") or "Via Adzuna"
    loc = (j.get("location") or {}).get("display_name") or ""
    smin = j.get("salary_min")
    smax = j.get("salary_max")
    return {
        "title":      (j.get("title") or "").strip(),
        "company":    company,
        "location":   loc,
        "url":        _clean_url(j.get("redirect_url", "")),
        "posted_at":  j.get("created"),
        "department": "",
        "tags":       (j.get("category") or {}).get("label", ""),
        "external_id": str(j.get("id", "")),
        "source":     "Adzuna",
        "salary_min": smin,
        "salary_max": smax,
        "salary_predicted": bool(j.get("salary_is_predicted")),
    }


_call_count = {"n": 0}


def _budget_left() -> bool:
    return _call_count["n"] < RATE_LIMIT_BUDGET


def _bump():
    _call_count["n"] += 1


def fetch_topic(country: str, topic: str, app_id: str, app_key: str) -> Iterator[dict]:
    """Broad keyword sweep per country."""
    base = f"https://api.adzuna.com/v1/api/jobs/{country}/search"
    for page in range(1, MAX_PAGES + 1):
        if not _budget_left():
            log.info("Adzuna budget exhausted (%d) — stopping topic sweep", _call_count["n"])
            return
        params = {"app_id": app_id, "app_key": app_key,
                  "results_per_page": RESULTS_PER_PAGE, "what": topic}
        try:
            r = _get(f"{base}/{page}", params); _bump()
            r.raise_for_status()
        except Exception as e:
            log.warning("adzuna %s/%s page %d: %s", country, topic, page, e)
            return
        results = r.json().get("results", [])
        for j in results:
            yield _normalize(j)
        if len(results) < RESULTS_PER_PAGE:
            return
        time.sleep(0.4)


def fetch_company(country: str, company: str, app_id: str, app_key: str) -> Iterator[dict]:
    """Targeted company query. Adzuna's company=NAME filter is exact-match
    against their per-country index; a company that exists in the CH index
    may return HTTP 400 in the US index. Treat 400 as a clean miss, not
    an error."""
    base = f"https://api.adzuna.com/v1/api/jobs/{country}/search"
    for page in range(1, MAX_PAGES + 1):
        if not _budget_left():
            log.info("Adzuna budget exhausted (%d) — stopping company lookups", _call_count["n"])
            return
        params = {"app_id": app_id, "app_key": app_key,
                  "results_per_page": RESULTS_PER_PAGE, "company": company}
        try:
            r = _get(f"{base}/{page}", params); _bump()
            if r.status_code == 400:
                log.debug("adzuna %s/company=%s: not in index", country, company)
                return
            r.raise_for_status()
        except Exception as e:
            log.warning("adzuna %s/company=%s page %d: %s", country, company, page, e)
            return
        results = r.json().get("results", [])
        for j in results:
            yield _normalize(j)
        if len(results) < RESULTS_PER_PAGE:
            return
        time.sleep(0.4)


def fetch_all() -> list[dict]:
    """Run topic sweeps + targeted lookups. Returns raw normalized rows."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        log.info("ADZUNA_APP_ID/ADZUNA_APP_KEY not set — skipping Adzuna.")
        return []

    # Default to a single broad topic per primary country to leave the
    # bulk of the budget for targeted company lookups.
    countries = (os.environ.get("ADZUNA_COUNTRIES")
                 or "ch,de,at,gb,us").split(",")
    countries = [c.strip().lower() for c in countries if c.strip()]
    topics = (os.environ.get("ADZUNA_TOPICS") or "pharma,digital health").split(",")
    topics = [t.strip() for t in topics if t.strip()]

    out: list[dict] = []

    log.info("Adzuna: %d countries × %d topics broad sweep", len(countries), len(topics))
    for country in countries:
        for topic in topics:
            n = 0
            for j in fetch_topic(country, topic, app_id, app_key):
                out.append(j); n += 1
            log.info("[ADZUNA topic %s/%s] +%d", country, topic, n)

    log.info("Adzuna: %d targeted company lookups", len(TARGETED))
    for company, target_countries in TARGETED:
        # tolerate the few entries above where target_countries is accidentally a string
        if isinstance(target_countries, str):
            target_countries = [target_countries]
        for country in target_countries:
            n = 0
            for j in fetch_company(country, company, app_id, app_key):
                out.append(j); n += 1
            if n:
                log.info("[ADZUNA %s in %s] +%d", company, country, n)

    log.info("Adzuna: %d raw rows total", len(out))
    return out
