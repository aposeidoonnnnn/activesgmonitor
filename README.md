# ActiveSG Gym/Pool Crowd Monitor

Scrapes crowd levels from https://activesg.gov.sg/gym-pool-crowd every 15
minutes and logs them to `data/crowd_log.csv`.

## Status (verified, not assumed)

- **Cloudflare: confirmed passed.** A manual `workflow_dispatch` run on
  GitHub Actions (run #1, 2026-09-10) navigated to the live page and
  extracted real data with no challenge page — see
  `debug/last_success.html`/`.png` for the exact DOM that was captured.
  This branch is also the repo's default branch, so the 15-minute
  `schedule` cron will run unattended from here.
- **Real data confirmed**: 30 actual ActiveSG gyms (Ang Mo Kio, Bishan,
  Yishun, Tampines, etc.) with plausible crowd percentages (18-79%),
  committed to `data/crowd_log.csv`.
- The site is a Chakra UI app; each facility renders as
  `div.chakra-card > div.chakra-card__body > (name, "NN% full" badge)`.
  The first run's selector (`[class*='card']`) matched both the outer and
  inner div (both class names contain "card"), producing exact duplicate
  rows — fixed by de-duplicating results before writing to CSV. The first
  run's 60 raw rows were cleaned to 30 unique rows in this commit.
- `generate_report.py` has been tested against real collected data.
  Analysis includes per-gym average/peak/min/variability, busiest and
  quietest hour per gym, a 24-hour crowd profile, weekday vs weekend
  comparison, busiest/quietest/most-variable gym rankings, and daily +
  week-over-week trend with direction.
- **Dashboard website confirmed rendering correctly** — verified with a
  real headless-Chromium screenshot against the live collected data (bar
  chart per gym, hourly pattern, daily and weekly trend charts, rankings,
  full table all populated correctly). The only issue hit during testing
  was this build environment's own network policy blocking the Chart.js
  CDN — irrelevant for real visitors on GitHub Pages, confirmed by
  re-testing with a locally-hosted copy of the exact same file.
- **Data source**: `data/crowd_log.csv` is a merge of GitHub Actions' and
  a Mac (launchd, see `MAC_SETUP.md`) data, deduplicated by exact
  (timestamp, gym_name, crowd_value). The Mac has been the primary
  source in practice — GitHub Actions' `schedule` trigger has fired far
  less often than every 15 minutes despite correct YAML/permissions/
  billing (see commit history around 2026-09-10/11 for the debugging).
- **Known data quality caveat**: every gym shows a minimum reading of
  0%. Most of this is real — gyms are genuinely near-empty right at 7am
  opening and in the last ~45 min before 10pm closing, and this pattern
  repeats across many different gyms on many different days. But three
  specific gyms (Enabling Village, Delta, Queenstown) were flatlined at
  exactly 0% for a full ~13-hour stretch on 2026-09-14 (a Monday) while
  showing normal values on 2026-09-13 and 2026-09-15 — confirmed not a
  scraper bug (the scraper faithfully recorded what the page showed),
  but unclear whether it reflects real facility closures that day or a
  stale reading on ActiveSG's own site. Not scrubbed from the data since
  that couldn't be confirmed either way — worth knowing about if you see
  a gym's stats look off.

## Files

- `scrape.py` — Playwright-based scraper, appends to `data/crowd_log.csv`.
- `generate_report.py` — reads the CSV and writes `reports/report.md`
  (`--html` for an HTML copy, `--website` for the dashboard) with the full
  analysis described above.
- `.github/workflows/scrape.yml` — runs the scraper every 15 minutes,
  7am-10pm Singapore time (ActiveSG's typical opening hours), via GitHub
  Actions and commits the CSV back. Includes a 30-day cutoff based on
  `data/start_date.txt` (auto-created on first run: 2026-09-10T08:19:57Z,
  so it self-disables around 2026-10-10). **Known issue**: the `schedule`
  trigger has proven intermittent on this account (fired once, then went
  silent for hours, despite YAML/permissions/billing all checking out
  fine) — see `MAC_SETUP.md` for the reliable fallback running in
  parallel.
- `.github/workflows/report.yml` — runs `generate_report.py --html --website`
  **once a week** (Monday 02:00 UTC) against the full accumulated CSV and
  commits `reports/` + `docs/` back. Weekly rather than every 15 minutes so
  the website shows a stable snapshot and Pages doesn't redeploy 96
  times/day; trigger it manually any time via Actions → "ActiveSG Gym
  Crowd Report & Dashboard" → Run workflow.
- `docs/index.html` — the dashboard website (see "Website" below).
- `MAC_SETUP.md` — launchd-based fallback if GitHub Actions gets
  Cloudflare-blocked (GitHub's runner IPs are well-known datacenter ranges,
  which some sites block harder than residential IPs).

## GitHub Actions notes

- This repo was empty when this branch was first pushed, so GitHub set
  `claude/activesg-gym-crowd-scraper-slihpx` as the default branch
  automatically — the `schedule` cron (which only fires for workflow files
  on the default branch) is active.
- After the first push, the workflow didn't show up in the Actions tab or
  API for several minutes (`list_workflows` returned 0 results) even
  though the YAML was valid and Actions was enabled in repo settings. A
  trivial follow-up commit to the workflow file made GitHub re-index it
  immediately. If you ever add a new workflow file and it doesn't appear
  in the Actions tab, try a small follow-up commit before assuming
  something is misconfigured.

## Running locally

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scrape.py
```

## Generating a report

```bash
python generate_report.py --html --website
```

Writes `reports/report.md`, `reports/report.html`, `reports/report_data.json`,
and `docs/index.html`.

## Website

`docs/index.html` is a self-contained dashboard (dark theme, Chart.js)
with two tabs:
- **Overview**: average crowd per gym, a day-trend chart (7am-9:45pm SGT,
  15-min resolution), day-of-week pattern, week-over-week trend,
  busiest/quietest/most-variable gym rankings, and a full per-gym stats
  table.
- **By Gym**: click any gym (horizontally scrollable pill tabs) to see
  its own day-trend and day-of-week charts, stats, and a "predicted
  crowd right now" card based on the historical average for the current
  SGT day-of-week + hour.

All times are displayed in Singapore time (SGT, UTC+8) even though
`data/crowd_log.csv` stores UTC — SGT is what matters for opening hours
and the audience's clock. Scrape events where every single gym reads 0%
simultaneously are excluded from the report/dashboard (treated as the
site showing a "closed" state rather than real crowd data); partial
near-zero readings at open/close are left in since those are genuine
gym behavior, not an artifact.

**On "live" data**: the page fetches `report_data.json` (same folder)
on every load, so it always shows whatever data is currently committed
to the repo rather than a stale snapshot from whenever the page was last
generated. This is *not* a live scrape of activesg.gov.sg on page
open — that site is Cloudflare-protected and needs a real headless
browser to load, which a static page can't run client-side (would hit
CORS and the same Cloudflare wall `scrape.py` exists to get around).
The "predicted crowd" feature is a historical-pattern lookup (same
day-of-week + hour average), not a live reading.

Chart.js is vendored locally as `docs/chart.umd.js` rather than loaded
from a CDN. It was originally CDN-loaded, but a real visitor reported a
blank dashboard (all stat cards worked, all charts/lists/tables empty —
the exact signature of the `Chart` global not existing, i.e. the CDN
script failed to load, most likely blocked by a browser extension or
network policy on their end). Vendoring it removes that whole class of
failure for any visitor, at the cost of a ~200KB static file checked
into the repo.

**To make it a live website, enable GitHub Pages once:**
Settings → Pages → Source: "Deploy from a branch" → Branch:
`claude/activesg-gym-crowd-scraper-slihpx` / `/docs` → Save. It will then be
served at `https://aposeidoonnnnn.github.io/activesgmonitor/` and update
automatically whenever `report.yml` runs (weekly, or on manual dispatch).
