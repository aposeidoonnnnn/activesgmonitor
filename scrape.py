#!/usr/bin/env python3
"""Scrape gym/pool crowd levels from activesg.gov.sg and append to CSV.

This site is behind Cloudflare bot protection and is a client-rendered SPA,
so it must be driven with a real headless browser (Playwright) that executes
JS, not requests/BeautifulSoup.

Because the exact DOM structure of the live page was not available to build
against, extraction uses a resilient, multi-strategy approach:
  1. Try a list of plausible CSS selectors for "card"-like facility blocks.
  2. Fall back to scanning all leaf text nodes for a crowd-indicator pattern
     (a percentage like "42%" or a level word like "Not Crowded") and pairing
     it with the nearest preceding text that looks like a facility name.

On the FIRST successful run, and on ANY run where zero gyms are extracted or
a Cloudflare challenge is detected, a screenshot + full HTML dump are saved
to debug/ so selectors can be refined against real data. Debug files are
overwritten each time (not accumulated) to avoid bloating the repo.
"""
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://activesg.gov.sg/gym-pool-crowd"
ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "data" / "crowd_log.csv"
LOG_PATH = ROOT / "data" / "run_log.txt"
DEBUG_DIR = ROOT / "debug"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Candidate selectors for a single facility "card". Tried in order; first
# selector that yields any matches wins for the structured pass.
CARD_SELECTOR_CANDIDATES = [
    "[class*='card']",
    "[class*='facility']",
    "[class*='crowd']",
    "[class*='venue']",
    "li",
    "article",
]

# A crowd indicator is either a percentage or one of the known level words
# ActiveSG has historically used.
CROWD_PATTERN = re.compile(
    r"(\d{1,3}\s?%|not\s+crowded|slightly\s+crowded|moderately\s+crowded|"
    r"crowded|low|moderate|high)",
    re.IGNORECASE,
)

CLOUDFLARE_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "cf-browser-verification",
    "cf_chl_",
)


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"{timestamp} {message}"
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", newline="") as f:
        f.write(line + "\n")


def dump_debug(page, tag: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{tag}.png"), full_page=True)
    except Exception as exc:  # noqa: BLE001
        log(f"WARN could not save debug screenshot: {exc}")
    try:
        (DEBUG_DIR / f"{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log(f"WARN could not save debug html: {exc}")


def looks_like_cloudflare_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CLOUDFLARE_MARKERS)


def extract_via_cards(page) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for selector in CARD_SELECTOR_CANDIDATES:
        try:
            elements = page.query_selector_all(selector)
        except Exception:  # noqa: BLE001
            continue
        candidate_results = []
        for el in elements:
            try:
                text = el.inner_text().strip()
            except Exception:  # noqa: BLE001
                continue
            if not text or len(text) > 200:
                continue
            match = CROWD_PATTERN.search(text)
            if not match:
                continue
            crowd_value = match.group(1).strip()
            name = text[: match.start()].strip(" \n\t-:|")
            name = name.splitlines()[-1].strip() if name else ""
            if name:
                candidate_results.append((name, crowd_value))
        if candidate_results:
            results = candidate_results
            break
    return results


def extract_via_text_scan(page) -> list[tuple[str, str]]:
    try:
        body_text = page.inner_text("body")
    except Exception:  # noqa: BLE001
        return []
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    results: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        match = CROWD_PATTERN.fullmatch(line) or CROWD_PATTERN.fullmatch(
            line.rstrip("%") + "%" if line.rstrip().endswith("%") else line
        )
        if match and i > 0:
            name = lines[i - 1]
            if 2 <= len(name) <= 80 and not CROWD_PATTERN.fullmatch(name):
                results.append((name, line))
    return results


def scrape() -> list[tuple[str, str]]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="en-SG",
        )
        page = context.new_page()
        log(f"Navigating to {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)

        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:  # noqa: BLE001
            log("WARN networkidle wait timed out, continuing anyway")

        html = page.content()
        if looks_like_cloudflare_challenge(html):
            log("BLOCKED Cloudflare challenge page detected after initial load; "
                "waiting 10s and retrying once")
            page.wait_for_timeout(10_000)
            html = page.content()

        if looks_like_cloudflare_challenge(html):
            dump_debug(page, "last_failure")
            log("BLOCKED Cloudflare challenge still present, giving up this run")
            browser.close()
            return []

        # Give the SPA extra time to hydrate/render crowd data client-side.
        page.wait_for_timeout(5_000)

        results = extract_via_cards(page)
        if not results:
            results = extract_via_text_scan(page)

        if not results:
            dump_debug(page, "last_failure")
            log("FAIL no gym crowd data extracted; see debug/last_failure.html")
        elif not (ROOT / "debug" / "last_success.html").exists():
            dump_debug(page, "last_success")
            log(f"SUCCESS first successful run, extracted {len(results)} gyms; "
                "saved debug/last_success.* for selector review")
        else:
            log(f"SUCCESS extracted {len(results)} gyms")

        browser.close()
        return results


def append_to_csv(rows: list[tuple[str, str]]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not CSV_PATH.exists()
    timestamp = datetime.now(timezone.utc).isoformat()
    with CSV_PATH.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "gym_name", "crowd_value"])
        for name, value in rows:
            writer.writerow([timestamp, name, value])


def main() -> int:
    rows = scrape()
    if not rows:
        log("No rows scraped this run; CSV not updated")
        return 1
    append_to_csv(rows)
    log(f"Appended {len(rows)} rows to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
