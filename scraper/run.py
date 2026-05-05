"""Entry point: scrape every company + every job board, classify, write
docs/jobs.json (used by the static frontend)."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path

from companies import COMPANIES, WATCHLIST, TYPE_LABELS
from classify import (
    classify_seniority, classify_company_type, is_digital, is_health_related,
    SENIORITY_RANK, SENIORITY_LABELS,
)
from sources import fetch_company
from boards import BOARD_FETCHERS
from adzuna import fetch_all as fetch_adzuna_all

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "jobs.json"
MAX_WORKERS = 8


def normalize_company_job(raw: dict, company: dict) -> dict | None:
    title = (raw.get("title") or "").strip()
    if not title:
        return None
    if not is_digital(title, raw.get("department", "")):
        return None
    seniority = classify_seniority(title)
    return _row(
        title=title,
        company=company["name"],
        company_type=company["type"],
        country=company.get("country"),
        location=raw.get("location") or "",
        department=raw.get("department") or "",
        seniority=seniority,
        url=raw.get("url", ""),
        posted_at=raw.get("posted_at"),
        external_id=raw.get("external_id", ""),
        source="ATS",
    )


def normalize_board_job(raw: dict) -> dict | None:
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    if not title or not company:
        return None
    # 1) only digital roles
    if not is_digital(title, raw.get("tags", "")):
        return None
    # 2) only health-context (board has every industry)
    if not is_health_related(title, company, raw.get("tags", "")):
        return None
    company_type = classify_company_type(company)
    seniority = classify_seniority(title)
    return _row(
        title=title,
        company=company,
        company_type=company_type,
        country=None,
        location=raw.get("location") or "",
        department="",
        seniority=seniority,
        url=raw.get("url", ""),
        posted_at=raw.get("posted_at"),
        external_id=raw.get("external_id", ""),
        source=raw.get("source", "Board"),
    )


def normalize_adzuna_job(raw: dict) -> dict | None:
    """Adzuna rows behave like board rows but we filter for digital + health."""
    title = (raw.get("title") or "").strip()
    company = (raw.get("company") or "").strip()
    if not title or not company:
        return None
    if not is_digital(title, raw.get("tags", "")):
        return None
    # Adzuna already targets pharma/health queries but topic sweeps catch
    # broader posts; require health context to keep noise out.
    if not is_health_related(title, company, raw.get("tags", "")):
        return None
    return _row(
        title=title,
        company=company,
        company_type=classify_company_type(company),
        country=None,
        location=raw.get("location") or "",
        department="",
        seniority=classify_seniority(title),
        url=raw.get("url", ""),
        posted_at=raw.get("posted_at"),
        external_id=raw.get("external_id", ""),
        source="Adzuna",
    )


def _row(*, title, company, company_type, country, location, department,
         seniority, url, posted_at, external_id, source) -> dict:
    return {
        "title":           title,
        "company":         company,
        "company_type":    company_type,
        "type_label":      TYPE_LABELS.get(company_type, company_type),
        "country":         country,
        "location":        (location or "").strip() or "Unspecified",
        "department":      (department or "").strip(),
        "seniority":       seniority,
        "seniority_rank":  SENIORITY_RANK[seniority],
        "seniority_label": SENIORITY_LABELS[seniority],
        "url":             url,
        "posted_at":       posted_at,
        "external_id":     external_id,
        "source":          source,
    }


def scrape_company(company: dict):
    t0 = time.time()
    try:
        raw = fetch_company(company)
        normalized = [n for r in raw if (n := normalize_company_job(r, company))]
        log.info("[ATS    %-22s] %4d raw → %3d digital (%.1fs)",
                 company["name"], len(raw), len(normalized), time.time() - t0)
        return company, normalized, None
    except Exception as e:
        log.warning("[ATS    %-22s] FAILED: %s", company["name"], e)
        return company, [], e


def scrape_board(name_fetcher):
    name, fetcher = name_fetcher
    t0 = time.time()
    try:
        raw = list(fetcher())
        normalized = [n for r in raw if (n := normalize_board_job(r))]
        log.info("[BOARD  %-22s] %4d raw → %3d digital+health (%.1fs)",
                 name, len(raw), len(normalized), time.time() - t0)
        return name, normalized, None
    except Exception as e:
        log.warning("[BOARD  %-22s] FAILED: %s", name, e)
        return name, [], e


def dedupe(jobs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for j in jobs:
        key = (j["company"].lower().strip(), j["title"].lower().strip(),
               (j["location"] or "").lower().strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--limit", type=int, help="Process only N companies (debug)")
    parser.add_argument("--no-boards", action="store_true", help="Skip generic job boards")
    parser.add_argument("--no-ats", action="store_true", help="Skip ATS scrapes")
    parser.add_argument("--no-adzuna", action="store_true", help="Skip Adzuna API")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Silence requests/urllib3 connection chatter
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    targets = COMPANIES[: args.limit] if args.limit else COMPANIES
    all_jobs: list[dict] = []
    errors: list[dict] = []
    company_stats: list[dict] = []

    if not args.no_ats:
        with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for company, jobs, err in pool.map(scrape_company, targets):
                all_jobs.extend(jobs)
                company_stats.append({"name": company["name"], "type": company["type"],
                                      "jobs": len(jobs), "ok": err is None})
                if err:
                    errors.append({"source": company["name"], "error": str(err)})

    if not args.no_boards:
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            for name, jobs, err in pool.map(scrape_board, BOARD_FETCHERS):
                all_jobs.extend(jobs)
                company_stats.append({"name": f"[Board] {name}", "type": "board",
                                      "jobs": len(jobs), "ok": err is None})
                if err:
                    errors.append({"source": name, "error": str(err)})

    if not args.no_adzuna:
        try:
            t0 = time.time()
            raw = fetch_adzuna_all()
            adz_jobs = [n for r in raw if (n := normalize_adzuna_job(r))]
            log.info("[ADZUNA total            ] %4d raw → %3d digital+health (%.1fs)",
                     len(raw), len(adz_jobs), time.time() - t0)
            all_jobs.extend(adz_jobs)
            company_stats.append({"name": "[Adzuna]", "type": "aggregator",
                                  "jobs": len(adz_jobs), "ok": True})
        except Exception as e:
            log.warning("Adzuna fetch failed: %s", e)
            errors.append({"source": "Adzuna", "error": str(e)})

    all_jobs = dedupe(all_jobs)
    # Sort: seniority desc, then company A→Z, then title
    all_jobs.sort(key=lambda j: (-j["seniority_rank"], j["company"].lower(), j["title"].lower()))

    out = {
        "generated_at":     dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total_companies":  len(targets),
        "total_boards":     0 if args.no_boards else len(BOARD_FETCHERS),
        "successful":       len(company_stats) - len(errors),
        "total_jobs":       len(all_jobs),
        "errors":           errors,
        "watchlist":        [{**w, "type_label": TYPE_LABELS.get(w["type"], w["type"])}
                             for w in WATCHLIST],
        "type_labels":      TYPE_LABELS,
        "seniority_labels": SENIORITY_LABELS,
        "seniority_order":  [k for k, _ in sorted(SENIORITY_RANK.items(), key=lambda kv: -kv[1])],
        "company_stats":    company_stats,
        "jobs":             all_jobs,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log.info("Wrote %d jobs to %s", out["total_jobs"], args.out)
    if errors:
        log.info("Errors (%d):", len(errors))
        for e in errors[:20]:
            log.info("  - %s: %s", e["source"], e["error"])


if __name__ == "__main__":
    sys.exit(main())
