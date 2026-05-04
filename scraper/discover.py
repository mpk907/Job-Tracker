"""Global discovery of new pharma/health companies.

Sources (no scraping logins required, all public):

  yc          — Y Combinator OSS API (~5,700 startups, ~190 health-hiring)
  hn          — Hacker News "Ask HN: Who is hiring" monthly threads,
                filtered by health/pharma keywords (global, tech-heavy)
  endpoints   — Endpoints News RSS (pharma/biotech industry)
  fiercebio   — FierceBiotech RSS (US biotech funding & launches)
  fiercehc    — FierceHealthcare RSS (US health systems & payers)
  mobihealth  — MobiHealthNews RSS (digital health globally)
  sifted      — Sifted RSS (European startup ecosystem)
  statnews    — STAT News RSS (life sciences journalism)
  healthitnews— Healthcare IT News RSS (health IT)
  conferences — curated list of major industry conference exhibitor pages

Companies extracted from news/HN are *candidates* — they go into
`data/candidates.json` for human review before being promoted to
`scraper/companies.py`. We deliberately don't auto-merge: a regex over
news headlines will produce false positives.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "candidates.json"
UA = "Mozilla/5.0 (compatible; PharmaJobTracker-Discovery/1.0)"
TIMEOUT = 30
log = logging.getLogger(__name__)

# Health/pharma keywords used to keep only relevant candidates ------------
HEALTH_RX = re.compile(
    r"\b(health|pharma(?:ceutical)?|biotech|biopharm|biolog|drug|clinical|"
    r"medical|medicine|patient|therapeutic|diagnostic|genomic|oncolog|immunolog|"
    r"vaccine|trial|life\s*science|medtech|wearable|telemed|telehealth|"
    r"digital\s*health|digital\s*therapeutic|ehr|emr|hipaa|fhir|hl7|cro|"
    r"ehealth|m[hH]ealth|gxp|gcp|gmp|fda|ema)\b", re.I,
)

# ============================================================
# Source 1 — Y Combinator
# ============================================================
YC_URL = "https://yc-oss.github.io/api/companies/all.json"

def fetch_yc(only_hiring: bool = True) -> list[dict]:
    r = requests.get(YC_URL, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    out = []
    for c in r.json():
        blob = " ".join([str(c.get("industry", "")), str(c.get("subindustry", "")),
                         " ".join(c.get("tags", [])), c.get("one_liner", "") or ""])
        if not HEALTH_RX.search(blob):
            continue
        if only_hiring and not c.get("isHiring"):
            continue
        out.append({
            "name":      c.get("name"),
            "website":   c.get("website"),
            "one_liner": c.get("one_liner"),
            "stage":     c.get("stage"),
            "batch":     c.get("batch"),
            "team_size": c.get("team_size"),
            "location":  c.get("all_locations"),
            "source":    "Y Combinator",
        })
    return out

# ============================================================
# Source 2 — Hacker News "Who is hiring" threads
# ============================================================
def fetch_hn(max_threads: int = 6) -> list[dict]:
    """Scan recent monthly Who-is-hiring threads via HN's Algolia API."""
    out = []
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": "Ask HN: Who is hiring", "tags": "story",
                    "hitsPerPage": max_threads},
            headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        threads = r.json().get("hits", [])
    except Exception as e:
        log.warning("HN thread search failed: %s", e)
        return out

    for t in threads:
        sid = t.get("objectID")
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={"tags": f"comment,story_{sid}", "hitsPerPage": 1000},
                headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            comments = r.json().get("hits", [])
        except Exception as e:
            log.warning("HN comments for %s failed: %s", sid, e)
            continue

        thread_url = f"https://news.ycombinator.com/item?id={sid}"
        for c in comments:
            txt = c.get("comment_text") or ""
            plain = re.sub("<[^<]+?>", " ", html.unescape(txt))
            if not HEALTH_RX.search(plain):
                continue
            # First "line" before <p> is typically: "COMPANY | LOC | ROLE"
            first = re.split(r"<p>|\s\|\s", txt, 1)[0]
            first = re.sub("<[^<]+?>", "", html.unescape(first)).strip()
            # Take the company name (first segment)
            name = re.split(r"\s*[\|–\-]\s*", first, 1)[0].strip()
            name = re.sub(r"\s+", " ", name)[:80]
            if 2 <= len(name) <= 80:
                out.append({
                    "name":      name,
                    "website":   "",
                    "one_liner": plain[:240].strip(),
                    "stage":     None,
                    "source":    "HN Hiring",
                    "source_url": f"{thread_url}#{c.get('objectID')}",
                })
        time.sleep(0.4)
    return out

# ============================================================
# Source 3 — RSS feeds (pharma & digital-health media)
# ============================================================
RSS_FEEDS = [
    ("Endpoints News",        "https://endpts.com/feed/"),
    ("FierceBiotech",         "https://www.fiercebiotech.com/rss/xml"),
    ("FierceHealthcare",      "https://www.fiercehealthcare.com/rss/xml"),
    ("FiercePharma",          "https://www.fiercepharma.com/rss/xml"),
    ("MobiHealthNews",        "https://www.mobihealthnews.com/feed"),
    ("Sifted",                "https://sifted.eu/feed"),
    ("STAT News",             "https://www.statnews.com/feed/"),
    ("Healthcare IT News",    "https://www.healthcareitnews.com/rss.xml"),
    ("RockHealth",            "https://rockhealth.com/feed/"),
    ("BioPharma Dive",        "https://www.biopharmadive.com/feeds/news/"),
    ("MedCity News",          "https://medcitynews.com/feed/"),
]

# Headline patterns that typically mention a company name
NAME_PATTERNS = [
    re.compile(r"\b([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,4})\s+(?:raises|secures|closes|nets|lands|bags|picks up|grabs)\s+\$", re.I),
    re.compile(r"\b([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,4})\s+(?:announces|launches|unveils|debuts|rolls out|introduces|partners with|acquires|acquired by|files for IPO|goes public)", re.I),
    re.compile(r"^([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,4}):", re.I),
]
# Words to strip from leading position of headlines (to avoid noise)
NOISE_PREFIX = re.compile(r"^(Watch|Listen|Read|Updated|Exclusive|Op-Ed|How|Why|What|When|FDA|EMA|US|UK|EU|Big\s+Pharma|Pharma|Biotech)\s*[:\-]?\s*", re.I)

def fetch_rss(name: str, url: str) -> list[dict]:
    out = []
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.content
    except Exception as e:
        log.warning("RSS %s failed: %s", name, e)
        return out

    # Many feeds use <atom:link> without declaring xmlns:atom — patch it in
    # before parsing to avoid "unbound prefix" errors.
    try:
        text = body.decode("utf-8", errors="replace")
        if "xmlns:atom" not in text and "<atom:" in text:
            text = text.replace("<rss ", '<rss xmlns:atom="http://www.w3.org/2005/Atom" ', 1)
        if "xmlns:dc" not in text and "<dc:" in text:
            text = text.replace("<rss ", '<rss xmlns:dc="http://purl.org/dc/elements/1.1/" ', 1)
        if "xmlns:content" not in text and "<content:" in text:
            text = text.replace("<rss ", '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" ', 1)
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.warning("RSS %s parse failed: %s", name, e)
        return out

    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for it in items[:80]:
        title = (it.findtext("title") or "").strip()
        link  = (it.findtext("link")  or "").strip()
        desc  = (it.findtext("description") or "").strip()
        if not title:
            continue
        plain = re.sub("<[^<]+?>", " ", html.unescape(title + " " + desc))
        if not HEALTH_RX.search(plain):
            continue
        clean_title = NOISE_PREFIX.sub("", html.unescape(title)).strip()
        for pat in NAME_PATTERNS:
            m = pat.search(clean_title)
            if not m:
                continue
            cand = m.group(1).strip(" .,:")
            # Reject obvious non-companies
            if cand.lower() in {"the", "a", "an", "this", "that", "these", "fda", "ema",
                                 "ftc", "ceo", "cfo", "cto"}:
                continue
            if 2 <= len(cand) <= 80:
                out.append({
                    "name":       cand,
                    "website":    "",
                    "one_liner":  clean_title[:240],
                    "source":     name,
                    "source_url": link,
                })
                break
    return out

# ============================================================
# Source 4 — Conferences (curated, surfaced as links)
# ============================================================
CONFERENCES = [
    {"name": "HIMSS Global Health Conference",  "url": "https://www.himssconference.com/en/exhibitors.html",
     "region": "Global / US", "focus": "Health IT"},
    {"name": "HLTH Conference",                 "url": "https://www.hlth.com/usa/exhibitors",
     "region": "US",          "focus": "Digital Health"},
    {"name": "JP Morgan Healthcare Conference", "url": "https://www.jpmorgan.com/insights/business/healthcare-conference",
     "region": "US",          "focus": "Investor"},
    {"name": "BIO International Convention",    "url": "https://convention.bio.org/",
     "region": "Global",      "focus": "Biotech"},
    {"name": "BIO-Europe / BIO-Europe Spring",  "url": "https://informaconnect.com/bioeurope/",
     "region": "EU",          "focus": "Biotech Partnering"},
    {"name": "DIA Global Annual Meeting",       "url": "https://www.diaglobal.org",
     "region": "Global",      "focus": "Pharma R&D"},
    {"name": "ASCO Annual Meeting",             "url": "https://www.asco.org/meetings",
     "region": "Global",      "focus": "Oncology"},
    {"name": "ESMO Congress",                   "url": "https://www.esmo.org/meetings",
     "region": "EU",          "focus": "Oncology"},
    {"name": "DMEA",                            "url": "https://www.dmea.de/en/",
     "region": "DACH",        "focus": "Health IT"},
    {"name": "Health 2.0 Europe",               "url": "https://www.health2con.com/",
     "region": "EU",          "focus": "Digital Health"},
    {"name": "Frontiers Health",                "url": "https://www.frontiers.health/",
     "region": "EU",          "focus": "Digital Health"},
    {"name": "Pharma Marketing Summit",         "url": "https://pharmamarketing.com/",
     "region": "US",          "focus": "Commercial"},
    {"name": "eyeforpharma / Reuters Pharma",   "url": "https://events.reutersevents.com/pharma",
     "region": "Global",      "focus": "Commercial"},
    {"name": "Bio-IT World Conference",         "url": "https://www.bio-itworldexpo.com/",
     "region": "US",          "focus": "Bio Informatics"},
    {"name": "ViVE Health",                     "url": "https://www.viveevent.com/",
     "region": "US",          "focus": "Digital Health"},
]


# ============================================================
# Aggregation + dedupe
# ============================================================
def aggregate(*sources: list[dict]) -> dict[str, dict]:
    """Dedupe by lowercase name; keep distinct source URLs as evidence."""
    by_name: dict[str, dict] = {}
    for src in sources:
        for c in src:
            name = (c.get("name") or "").strip()
            key = name.lower()
            if not key:
                continue
            if key not in by_name:
                by_name[key] = {
                    "name":     name,
                    "website":  c.get("website") or "",
                    "one_liner": c.get("one_liner") or "",
                    "stage":    c.get("stage"),
                    "batch":    c.get("batch"),
                    "team_size": c.get("team_size"),
                    "location": c.get("location"),
                    "sources":  [],
                    "evidence": [],
                }
            entry = by_name[key]
            tag = c.get("source") or "?"
            if tag not in entry["sources"]:
                entry["sources"].append(tag)
            if c.get("source_url"):
                entry["evidence"].append({"source": tag, "url": c["source_url"],
                                          "snippet": (c.get("one_liner") or "")[:160]})
    return by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-yc", action="store_true")
    ap.add_argument("--no-hn", action="store_true")
    ap.add_argument("--no-rss", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    sources = []
    if not args.no_yc:
        log.info("→ Y Combinator …")
        try:
            yc = fetch_yc()
            log.info("   %d YC health companies hiring", len(yc))
            sources.append(yc)
        except Exception as e:
            log.warning("YC failed: %s", e)
    if not args.no_hn:
        log.info("→ Hacker News Who-is-hiring …")
        try:
            hn = fetch_hn()
            log.info("   %d HN candidates", len(hn))
            sources.append(hn)
        except Exception as e:
            log.warning("HN failed: %s", e)
    if not args.no_rss:
        for nm, url in RSS_FEEDS:
            log.info("→ RSS %s …", nm)
            cs = fetch_rss(nm, url)
            log.info("   %d candidates", len(cs))
            sources.append(cs)
            time.sleep(0.3)

    merged = aggregate(*sources)
    candidates = sorted(merged.values(), key=lambda c: c["name"].lower())

    # Stats per source
    per_source = defaultdict(int)
    for c in candidates:
        for s in c["sources"]:
            per_source[s] += 1

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources":      dict(per_source),
        "count":        len(candidates),
        "candidates":   candidates,
        "conferences":  CONFERENCES,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # Also drop a copy into docs/ so the static frontend can read it
    (ROOT / "docs" / "candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    log.info("Wrote %d unique candidates from %d sources to %s",
             len(candidates), sum(per_source.values()), args.out)


if __name__ == "__main__":
    main()
