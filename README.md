# ActiveSG Gym/Pool Crowd Monitor

Scrapes crowd levels from https://activesg.gov.sg/gym-pool-crowd every 15
minutes and logs them to `data/crowd_log.csv`.

## Status (be honest about what's verified)

- **Selectors are best-effort, not confirmed against the live DOM.** The
  build environment used to write this code has no general internet access
  (its outbound network is locked to an allowlist that excludes the target
  site, and even excludes downloading the Chromium browser binary
  Playwright needs), so `scrape.py` could not be run against the real page
  before being committed. See `debug/` after the first real run —
  `debug/last_success.html`/`.png` (or `last_failure.*` if extraction
  failed) will show exactly what the live page renders, and the selector
  logic in `scrape.py` should be tightened against that.
- **Cloudflare pass/fail has not yet been verified.** That will only be
  known once a real run happens, either via GitHub Actions
  (`workflow_dispatch` or the schedule, once merged to the default branch)
  or manually. Check `data/run_log.txt` after a run — it logs `SUCCESS`,
  `BLOCKED` (Cloudflare challenge detected), or `FAIL` (page loaded but no
  data found) for every attempt.
- `generate_report.py` has been tested against synthetic sample data and
  produces correct output (verified locally, not with real crowd data yet).

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

## Important GitHub Actions caveat

GitHub only fires the `schedule` (cron) trigger for the workflow file as it
exists on the **default branch** of the repo. If `.github/workflows/scrape.yml`
only lives on a feature branch, the cron will not run — only manual
`workflow_dispatch` runs will. Merge this to the default branch (or open a
PR) if you want the unattended 15-minute schedule to actually run.

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
