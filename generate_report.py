#!/usr/bin/env python3
"""Generate a summary report from data/crowd_log.csv.

Reads timestamp,gym_name,crowd_value rows and produces average/peak crowd
per gym, best/worst time of day, and a day-by-day trend. crowd_value may be
either a percentage ("42%") or a level word (e.g. "Not Crowded",
"Moderately Crowded", "Crowded", "Low", "Moderate", "High") -- both are
normalized to a 0-100 scale where possible so they can be averaged.

Usage:
    python generate_report.py [--csv data/crowd_log.csv] [--out reports/report.md] [--html]
"""
import argparse
import csv
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Ordinal level words mapped onto a rough 0-100 scale so they're comparable
# with percentage readings. Adjust once we know exactly which vocabulary the
# live page uses (see debug/last_success.html after the first real scrape).
LEVEL_SCALE = {
    "not crowded": 10,
    "low": 15,
    "slightly crowded": 35,
    "moderately crowded": 55,
    "moderate": 55,
    "crowded": 85,
    "high": 90,
}


def parse_crowd_value(raw: str) -> float | None:
    raw = raw.strip()
    pct_match = re.match(r"^(\d{1,3})\s?%$", raw)
    if pct_match:
        return float(pct_match.group(1))
    return LEVEL_SCALE.get(raw.lower())


def load_rows(csv_path: Path) -> list[dict]:
    rows = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            except ValueError:
                continue
            numeric = parse_crowd_value(row["crowd_value"])
            rows.append(
                {
                    "timestamp": ts,
                    "gym_name": row["gym_name"],
                    "crowd_value_raw": row["crowd_value"],
                    "crowd_value": numeric,
                }
            )
    return rows


def per_gym_stats(rows: list[dict]) -> dict:
    by_gym = defaultdict(list)
    for r in rows:
        by_gym[r["gym_name"]].append(r)

    stats = {}
    for gym, entries in by_gym.items():
        numeric_entries = [e for e in entries if e["crowd_value"] is not None]
        if not numeric_entries:
            stats[gym] = {
                "count": len(entries),
                "average": None,
                "peak": None,
                "peak_time": None,
            }
            continue
        avg = statistics.mean(e["crowd_value"] for e in numeric_entries)
        peak_entry = max(numeric_entries, key=lambda e: e["crowd_value"])
        stats[gym] = {
            "count": len(entries),
            "average": avg,
            "peak": peak_entry["crowd_value"],
            "peak_time": peak_entry["timestamp"],
        }
    return stats


def best_worst_hours(rows: list[dict]) -> tuple[list, list]:
    by_hour = defaultdict(list)
    for r in rows:
        if r["crowd_value"] is not None:
            by_hour[r["timestamp"].hour].append(r["crowd_value"])
    hour_avgs = sorted(
        ((hour, statistics.mean(vals)) for hour, vals in by_hour.items()),
        key=lambda x: x[1],
    )
    return hour_avgs[:3], hour_avgs[-3:][::-1]


def daily_trend(rows: list[dict]) -> list[tuple[str, float]]:
    by_day = defaultdict(list)
    for r in rows:
        if r["crowd_value"] is not None:
            by_day[r["timestamp"].date().isoformat()].append(r["crowd_value"])
    return sorted((day, statistics.mean(vals)) for day, vals in by_day.items())


def render_markdown(rows: list[dict], stats: dict, best_hours, worst_hours, trend) -> str:
    lines = ["# ActiveSG Gym Crowd Report", ""]
    if not rows:
        lines.append("No data available yet.")
        return "\n".join(lines)

    span_start = min(r["timestamp"] for r in rows)
    span_end = max(r["timestamp"] for r in rows)
    lines.append(
        f"Data range: **{span_start.isoformat()}** to **{span_end.isoformat()}** "
        f"({len(rows)} readings across {len(stats)} gyms)"
    )
    lines.append("")

    lines.append("## Per-gym summary")
    lines.append("")
    lines.append("| Gym | Readings | Avg crowd | Peak crowd | Peak time |")
    lines.append("|---|---|---|---|---|")
    for gym, s in sorted(stats.items()):
        avg = f"{s['average']:.1f}" if s["average"] is not None else "n/a"
        peak = f"{s['peak']:.1f}" if s["peak"] is not None else "n/a"
        peak_time = s["peak_time"].isoformat() if s["peak_time"] else "n/a"
        lines.append(f"| {gym} | {s['count']} | {avg} | {peak} | {peak_time} |")
    lines.append("")

    lines.append("## Best / worst times of day (all gyms combined)")
    lines.append("")
    lines.append("**Least crowded hours (UTC):**")
    for hour, avg in best_hours:
        lines.append(f"- {hour:02d}:00 — avg {avg:.1f}")
    lines.append("")
    lines.append("**Most crowded hours (UTC):**")
    for hour, avg in worst_hours:
        lines.append(f"- {hour:02d}:00 — avg {avg:.1f}")
    lines.append("")

    lines.append("## Trend over the week")
    lines.append("")
    lines.append("| Date | Avg crowd |")
    lines.append("|---|---|")
    for day, avg in trend:
        lines.append(f"| {day} | {avg:.1f} |")
    lines.append("")

    return "\n".join(lines)


def render_html(markdown_body: str) -> str:
    # Minimal wrapper; keeps the same content as the markdown table structure
    # rendered as basic HTML without any external dependencies.
    rows_html = markdown_body.replace("\n", "<br>\n")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>ActiveSG Gym Crowd Report</title>"
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;}"
        "td,th{border:1px solid #ccc;padding:6px 10px;text-align:left;}</style>"
        "</head><body><pre style='white-space:pre-wrap;font-family:inherit;'>"
        f"{markdown_body}</pre></body></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "data" / "crowd_log.csv"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "report.md"))
    parser.add_argument("--html", action="store_true", help="also write an .html version")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        print(f"No CSV found at {csv_path}")
        return

    rows = load_rows(csv_path)
    stats = per_gym_stats(rows)
    best_hours, worst_hours = best_worst_hours(rows)
    trend = daily_trend(rows)

    markdown = render_markdown(rows, stats, best_hours, worst_hours, trend)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {out_path}")

    if args.html:
        html_path = out_path.with_suffix(".html")
        html_path.write_text(render_html(markdown), encoding="utf-8")
        print(f"Wrote {html_path}")


if __name__ == "__main__":
    main()
