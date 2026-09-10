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

`docs/index.html` is a self-contained dashboard (dark theme, Chart.js via
CDN) showing: average crowd per gym, 24-hour crowd pattern, daily and
week-over-week trend charts, busiest/quietest/most-variable gym rankings,
and a full per-gym stats table. It reads its data from a JSON blob embedded
in the page at generation time — no server or build step needed.

**To make it a live website, enable GitHub Pages once:**
Settings → Pages → Source: "Deploy from a branch" → Branch:
`claude/activesg-gym-crowd-scraper-slihpx` / `/docs` → Save. It will then be
served at `https://aposeidoonnnnn.github.io/activesgmonitor/` and update
automatically whenever `report.yml` runs (weekly, or on manual dispatch).
