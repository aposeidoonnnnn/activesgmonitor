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
- `generate_report.py` has been tested against synthetic sample data and
  produces correct output; it will be re-verified against real data once
  a few days of scheduled runs accumulate.

## Files

- `scrape.py` — Playwright-based scraper, appends to `data/crowd_log.csv`.
- `generate_report.py` — reads the CSV and writes a markdown (`--html` for
  an HTML copy too) summary: per-gym average/peak, best/worst hours, daily
  trend.
- `.github/workflows/scrape.yml` — runs the scraper every 15 minutes via
  GitHub Actions and commits the CSV back. Includes a 7-day cutoff based on
  `data/start_date.txt` (auto-created on first run).
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
python generate_report.py --html
```

Writes `reports/report.md` and `reports/report.html`.
