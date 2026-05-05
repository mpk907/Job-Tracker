"""Bayer adapter.

`talent.bayer.com` runs Bayer's own talent platform (built on top of
Phenom Cloud). The page renders empty HTML and lazy-loads jobs via
`/api/apply/v2/jobs/{tenant_id}/jobs?domain=bayer.com&offset=N`.

That endpoint is *publicly* fetchable (no auth, no cookie) and returns
clean JSON. We just paginate it.

Schema in `positions[*]`:
  id, name, posting_name, location, locations[], department, business_unit,
  t_create, t_update, ats_job_id, display_job_id, type, job_description,
  canonicalPositionUrl …

We ignore noise (apprentice/cleanroom roles get filtered later by our
shared `is_digital()` heuristic in run.py).
"""

from __future__ import annotations

import logging
import time
from typing import Iterator

import requests

log = logging.getLogger(__name__)

UA = "PharmaJobTracker/1.0 (+https://github.com/mpk907/job-tracker)"
TIMEOUT = 25

# This is the Bayer career-portal tenant id; baked into talent.bayer.com.
# If Bayer ever rotates it, the page source still exposes the new value
# so we can refresh.
TENANT_ID = "562949976948234"
BASE = f"https://talent.bayer.com/api/apply/v2/jobs/{TENANT_ID}/jobs"

PAGE_SIZE = 10        # the API ignores higher limits
MAX_PAGES = 200       # 2,000 jobs cap; Bayer publishes ~1,500 globally


def _get(params):
    return requests.get(BASE, params=params,
                        headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=TIMEOUT)


def fetch_bayer() -> Iterator[dict]:
    """Paginate Bayer's positions endpoint until we run out of results."""
    seen_ids: set = set()
    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        try:
            r = _get({"domain": "bayer.com", "limit": PAGE_SIZE, "offset": offset})
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            log.warning("bayer page %d (offset=%d) failed: %s", page, offset, e)
            return

        positions = payload.get("positions", []) or []
        if not positions:
            return

        new = 0
        for p in positions:
            pid = p.get("id") or p.get("ats_job_id")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            new += 1

            # location comes as "City,Region,Country" (comma-separated)
            loc = (p.get("location") or "").replace(",", ", ")
            url = (p.get("canonicalPositionUrl")
                   or f"https://talent.bayer.com/careers/job/{pid}")

            yield {
                "title":       (p.get("posting_name") or p.get("name") or "").strip(),
                "location":    loc,
                "url":         url,
                "posted_at":   _epoch_to_iso(p.get("t_create")),
                "department":  p.get("department") or p.get("business_unit") or "",
                "external_id": str(p.get("display_job_id") or pid),
            }

        # The API repeats results when you go past the end → stop when no new ids
        if new == 0:
            return
        time.sleep(0.2)


def _epoch_to_iso(ts):
    if not ts:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
    except Exception:
        return None
