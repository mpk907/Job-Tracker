# Pharma Digital Job Tracker

A daily-refreshed feed of digital, data, AI, software, product and adjacent
technology roles across the global pharma value chain — Big Pharma,
specialist pharma, AI-first biotech, digital-health scaleups & startups,
CROs, MedTech, payers and pharma marketing agencies.

> Status: live. Powered by GitHub Actions + GitHub Pages, no servers, no API
> keys. Add a company by opening a one-line PR.

## What you get

| Tab        | What's in it                                                         |
|------------|----------------------------------------------------------------------|
| **Jobs**       | All currently-open digital roles, sortable by seniority/type/posted, with full-text search and faceted filters. |
| **Watchlist**  | Companies without a public ATS feed — links straight to their careers pages. |
| **Discovery**  | Auto-discovered candidate companies from a global scan (YC, HN hiring threads, 11 pharma/health media RSS feeds) plus 15 industry conferences. |
| **About**      | What "digital" means here, how the data is collected. |

## Architecture

```
Job-Tracker/
├── scraper/
│   ├── companies.py    Curated company list (60+ with ATS APIs, 200+ in WATCHLIST)
│   ├── sources.py      Adapters: Greenhouse, Lever, Ashby, SmartRecruiters, Workday
│   ├── boards.py       Generic boards: Remotive, RemoteOK, Arbeitnow, The Muse
│   ├── classify.py     Seniority + digital-keyword + health-context + company-type heuristics
│   ├── discover.py     Global scan: YC + HN + 11 RSS feeds + conferences → candidates.json
│   └── run.py          Entry point — writes docs/jobs.json
├── docs/               Static frontend served by GitHub Pages
│   ├── index.html      Tabs: Jobs, Watchlist, Discovery, About
│   ├── app.js          Vanilla JS — filters, sort, pagination
│   └── style.css       Dark theme + light auto via prefers-color-scheme
├── .github/workflows/
│   └── update.yml      Daily cron: scrape → discover → commit → deploy Pages
└── requirements.txt    Just `requests`
```

## Data sources

### Direct ATS APIs (preferred — accurate, near-real-time)

| ATS              | Endpoint pattern                                                       | Companies covered |
|------------------|------------------------------------------------------------------------|-------------------|
| Greenhouse       | `boards-api.greenhouse.io/v1/boards/{slug}/jobs`                       | ~40 (most digital-health scaleups) |
| Lever            | `api.lever.co/v0/postings/{slug}?mode=json`                            | ~5                |
| Ashby            | `api.ashbyhq.com/posting-api/job-board/{slug}`                         | ~6 (newer startups) |
| SmartRecruiters  | `api.smartrecruiters.com/v1/companies/{slug}/postings`                 | ~1                |
| Workday          | `POST {tenant}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`        | ~10 (Big Pharma)  |

### Generic job boards (filtered by health/pharma keywords)

- **Remotive** — `remotive.com/api/remote-jobs?search=…`
- **RemoteOK** — `remoteok.com/api?tags=health|medical|biotech|pharma`
- **Arbeitnow** — `www.arbeitnow.com/api/job-board-api` (EU-strong)
- **The Muse** — `www.themuse.com/api/public/jobs?category=Healthcare`

Each board entry passes two filters: (1) digital-keyword match in title/tags
and (2) health-context match. The result keeps the original company name
and a heuristic guesses its bucket (Big Pharma, Scaleup, etc).

### Discovery (`scraper/discover.py`)

Daily global scan that surfaces *candidate* companies — not auto-merged into
the live tracker, but visible on the **Discovery** tab so a human can promote
them via PR. Sources:

- **Y Combinator** OSS API — every YC startup tagged health/biotech/pharma
- **Hacker News** — comments in monthly *Ask HN: Who is hiring* threads,
  filtered by health keywords (catches lots of EU/global startups)
- **Pharma & health media RSS** — Endpoints News, FierceBiotech, FiercePharma,
  FierceHealthcare, MobiHealthNews, Sifted, STAT News, BioPharma Dive,
  MedCity News, Healthcare IT News, RockHealth Insights — company names
  extracted from "X raises $Y", "X launches", "X acquires" headlines
- **Industry conferences** (curated list of links to exhibitor pages):
  HIMSS, HLTH, JPM Healthcare, BIO International, BIO-Europe, DIA, ASCO,
  ESMO, DMEA, Health 2.0 Europe, Frontiers Health, Bio-IT World, ViVE…

## Adding a new company

1. **Find its ATS slug.** Visit the company's careers page. The URL almost
   always contains the slug:
   - `boards.greenhouse.io/<SLUG>` → Greenhouse
   - `jobs.lever.co/<SLUG>` → Lever
   - `jobs.ashbyhq.com/<SLUG>` → Ashby
   - `jobs.smartrecruiters.com/<SLUG>` → SmartRecruiters
   - `<TENANT>.wdN.myworkdayjobs.com/.../<TENANT>/<SITE>` → Workday
2. **Add an entry to `scraper/companies.py`:**
   ```python
   {"name": "Sword Health", "type": "scaleup", "country": "PT",
    "ats": "lever", "slug": "swordhealth"},
   ```
3. **Open a PR.** The next nightly run will pick it up.

If a company has no public ATS endpoint, drop it in the `WATCHLIST` block
with a direct careers URL — it'll still appear under the *Watchlist* tab.

## Running locally

```bash
pip install -r requirements.txt
python scraper/run.py        # → docs/jobs.json
python scraper/discover.py   # → docs/candidates.json (+ data/candidates.json)

# Serve the static site
python -m http.server 8000 --directory docs
open http://localhost:8000
```

Useful flags:

```bash
python scraper/run.py --limit 5       # only first 5 ATS companies (debug)
python scraper/run.py --no-boards     # skip generic job boards
python scraper/run.py -v              # verbose logging
python scraper/discover.py --no-rss   # YC + HN only (faster)
```

## Weekly newsletter

Every Sunday 07:00 UTC the workflow runs `scraper/digest.py`, which:

1. Diffs the current `docs/jobs.json` against the most recent snapshot in
   `data/snapshots/`.
2. Writes `digests/YYYY-Www.md` (and `latest.md` + `index.json`).
3. Optionally posts the digest as a Buttondown draft if a
   `BUTTONDOWN_API_KEY` secret is set on the repo.

**Manual paste workflow** (no setup):
- Open `digests/latest.md`, copy, paste into Substack/Beehiiv/ConvertKit/
  LinkedIn/email and hit publish.

**Auto-publish via Buttondown** (one-time setup):
1. Get an API key from buttondown.email (Settings → Programming).
2. Repo → Settings → Secrets → Actions → add `BUTTONDOWN_API_KEY`.
3. Drafts now appear in your Buttondown dashboard each Sunday — review and
   send. To skip the review step, change `--publish draft` to
   `--publish send` in the workflow.

## Deployment

The GitHub Action in `.github/workflows/update.yml` runs every day at
06:00 UTC:

1. `python scraper/run.py` → fresh `docs/jobs.json`
2. `python scraper/discover.py` → fresh `docs/candidates.json`
3. Commits the JSON back to the branch
4. Publishes `docs/` to GitHub Pages

To enable Pages: **Repo Settings → Pages → Source: GitHub Actions**.

## What counts as "digital"?

A title or department matching at least one of: `digital`, `data`,
`analytics`, `AI/ML/LLM/NLP`, `software/engineer/developer`, `cloud`,
`product manager`, `UX/UI/designer`, `bioinformatics`, `computational`,
`biostatistics`, `MLOps`, `digital health`, `digital therapeutic`,
`telehealth`, `RWD/RWE`, `wearable`, `IoT`, `decentralized trial`,
`MarTech / omnichannel / Veeva / CRM`. Full keyword list in
`scraper/classify.py`.

## License & disclaimer

This project is not affiliated with any of the listed companies. Data may
be incomplete or stale; always verify openings on the company's own
careers page before applying. Code: MIT.
