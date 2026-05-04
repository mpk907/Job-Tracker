"""Weekly newsletter digest.

Diffs the latest scrape against last week's snapshot, then writes a
clean Markdown file to `digests/YYYY-Www.md` that you can paste straight
into Substack, Beehiiv, Buttondown, ConvertKit or LinkedIn.

Usage:
    python scraper/digest.py                 # diff against newest snapshot
    python scraper/digest.py --snapshot      # save current jobs.json as a
                                             # snapshot (no diff written)
    python scraper/digest.py --baseline FILE # diff against a specific file

The CI workflow runs `--snapshot` after every scrape and `python digest.py`
weekly on Sundays.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS_PATH = ROOT / "docs" / "jobs.json"
SNAP_DIR = ROOT / "data" / "snapshots"
DIGEST_DIR = ROOT / "digests"
log = logging.getLogger(__name__)

# Top-N per (type, seniority) so the email stays readable. Click "more" link
# takes the reader to the full filtered view on the site.
MAX_PER_GROUP = 8
SITE_BASE = "https://mpk907.github.io/Job-Tracker"

TYPE_ORDER = [
    "big_pharma", "specialist_pharma", "ai_biotech",
    "scaleup", "startup", "medtech",
    "cro_tech_provider", "agency", "payer", "provider", "health_corp", "unknown",
]
SENIORITY_ORDER = [
    "c_level", "vp", "director", "principal", "lead",
    "senior", "mid", "junior", "intern", "unknown",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def latest_snapshot() -> Path | None:
    if not SNAP_DIR.exists():
        return None
    snaps = sorted(SNAP_DIR.glob("*.json"))
    return snaps[-1] if snaps else None


def job_key(j: dict) -> tuple:
    """Stable identity for diffing. external_id is best when present."""
    if j.get("external_id"):
        return (j["company"].lower(), str(j["external_id"]))
    return (j["company"].lower(), j["title"].lower(), (j.get("location") or "").lower())


def find_new(current: list[dict], baseline: list[dict]) -> list[dict]:
    seen = {job_key(j) for j in baseline}
    return [j for j in current if job_key(j) not in seen]


def render_markdown(new_jobs: list[dict], baseline_date: str | None,
                    current: dict, week_label: str) -> str:
    type_labels = current.get("type_labels", {})
    sen_labels  = current.get("seniority_labels", {})

    by_tg = defaultdict(lambda: defaultdict(list))
    for j in new_jobs:
        by_tg[j["company_type"]][j["seniority"]].append(j)

    out = []
    out.append(f"# Pharma Digital Jobs — {week_label}\n")
    if baseline_date:
        out.append(f"_New roles posted between {baseline_date[:10]} and "
                   f"{current['generated_at'][:10]}._\n")
    out.append(f"**{len(new_jobs)} new digital roles** this week across "
               f"{len({j['company'] for j in new_jobs})} companies.\n")
    out.append(f"[→ Browse the full live tracker]({SITE_BASE})\n")
    out.append("---\n")

    if not new_jobs:
        out.append("_No new roles this week._\n")
        return "\n".join(out)

    # Section per company type, in our preferred order
    for tp in TYPE_ORDER:
        if tp not in by_tg:
            continue
        out.append(f"\n## {type_labels.get(tp, tp)}\n")
        for sen in SENIORITY_ORDER:
            if sen not in by_tg[tp]:
                continue
            jobs = sorted(by_tg[tp][sen],
                          key=lambda j: (j["company"].lower(), j["title"].lower()))
            out.append(f"\n**{sen_labels.get(sen, sen)}** ({len(jobs)})\n")
            for j in jobs[:MAX_PER_GROUP]:
                loc = j["location"] or "—"
                country = f" {j['country']}" if j.get("country") else ""
                title = j["title"].replace("|", "\\|")
                if j.get("url"):
                    out.append(f"- [{title}]({j['url']}) — **{j['company']}**{country} · {loc}")
                else:
                    out.append(f"- {title} — **{j['company']}**{country} · {loc}")
            if len(jobs) > MAX_PER_GROUP:
                out.append(f"- … and {len(jobs) - MAX_PER_GROUP} more — "
                           f"[see all]({SITE_BASE}?type={tp}&seniority={sen})")

    # Discovery candidates added this week (optional, if file exists)
    cand_path = ROOT / "docs" / "candidates.json"
    if cand_path.exists():
        try:
            cands = json.loads(cand_path.read_text())
            new_cands = cands.get("candidates", [])[:10]
            if new_cands:
                out.append("\n---\n\n## On the radar\n")
                out.append("_Auto-discovered companies worth a look:_\n")
                for c in new_cands:
                    src = ", ".join(c.get("sources", []))
                    out.append(f"- **{c['name']}** — {c.get('one_liner','')[:140]} _({src})_")
        except Exception:
            pass

    out.append("\n---\n")
    out.append(f"_Sourced from {current['total_companies']} ATS endpoints + 4 job boards. "
               f"[Add a missing company]({SITE_BASE}/#about)._")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true",
                    help="Save current jobs.json into the snapshot folder and exit.")
    ap.add_argument("--baseline", help="Path to a specific baseline jobs.json")
    ap.add_argument("--out-dir", default=str(DIGEST_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not JOBS_PATH.exists():
        log.error("No %s — run scraper/run.py first.", JOBS_PATH)
        return 1

    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    if args.snapshot:
        ts = dt.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        dst = SNAP_DIR / f"{ts}.json"
        shutil.copy2(JOBS_PATH, dst)
        log.info("Snapshot saved: %s", dst.relative_to(ROOT))
        return 0

    current = load_json(JOBS_PATH)
    baseline_path = Path(args.baseline) if args.baseline else latest_snapshot()
    if not baseline_path or not baseline_path.exists():
        log.warning("No baseline snapshot found — generating digest with all "
                    "current jobs treated as new (first run).")
        baseline = {"jobs": [], "generated_at": None}
    else:
        baseline = load_json(baseline_path)
        log.info("Baseline: %s (%d jobs)", baseline_path.name,
                 len(baseline.get("jobs", [])))

    new_jobs = find_new(current["jobs"], baseline.get("jobs", []))
    log.info("Found %d new jobs since baseline.", len(new_jobs))

    today = dt.date.today()
    iso = today.isocalendar()
    week_label = f"Week {iso.week}, {iso.year}"
    fname = f"{iso.year}-W{iso.week:02d}.md"

    md = render_markdown(new_jobs, baseline.get("generated_at"), current, week_label)
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / fname
    out.write_text(md)

    # Maintain a stable "latest" pointer for the frontend to load
    (out_dir / "latest.md").write_text(md)
    (out_dir / "index.json").write_text(json.dumps({
        "latest": fname,
        "generated_at": current["generated_at"],
        "new_jobs":  len(new_jobs),
        "all":       sorted(p.name for p in out_dir.glob("*.md") if p.name != "latest.md"),
    }, indent=2))
    log.info("Wrote %s (%d new jobs)", out, len(new_jobs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
