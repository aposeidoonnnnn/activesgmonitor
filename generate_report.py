#!/usr/bin/env python3
"""Generate a summary report (and dashboard website) from data/crowd_log.csv.

Reads timestamp,gym_name,crowd_value rows and computes: per-gym average/
peak/min/variability, a 15-minute crowd profile from 7am-9:45pm Singapore
time, day-of-week pattern, weekday vs weekend comparison, busiest/quietest/
most variable gym rankings, and trend direction over the collection period.

All display times are Singapore time (SGT, UTC+8) even though the CSV
stores UTC timestamps -- SGT is what matters since that's the gym's local
opening hours and the audience's timezone.

Scrape events where every gym simultaneously reads 0% are excluded from
analysis (treated as "actually closed / no real data" rather than genuine
crowd data) but left untouched in the raw CSV.

crowd_value may be either a percentage ("42%") or a level word (e.g. "Not
Crowded", "Moderately Crowded", "Crowded", "Low", "Moderate", "High") --
both are normalized to a 0-100 scale where possible so they can be averaged.

Outputs:
    reports/report.md          -- markdown summary
    reports/report.html        -- plain HTML copy (--html)
    reports/report_data.json   -- the computed data, for reuse/debugging
    docs/index.html            -- dashboard website with charts (--website)
    docs/report_data.json      -- same data, fetched client-side on page load

Usage:
    python generate_report.py [--csv data/crowd_log.csv] [--out reports/report.md] [--html] [--website]
"""
import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SGT = timezone(timedelta(hours=8))
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

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

# 15-minute buckets covering the "day trend" chart window, 7:00am-9:45pm SGT.
DAY_PATTERN_SLOTS = [(h, m) for h in range(7, 22) for m in (0, 15, 30, 45)]
DAY_PATTERN_SLOTS_SET = set(DAY_PATTERN_SLOTS)


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
                    "timestamp_sgt": ts.astimezone(SGT),
                    "gym_name": row["gym_name"],
                    "crowd_value_raw": row["crowd_value"],
                    "crowd_value": numeric,
                }
            )
    return rows


def exclude_all_zero_events(rows: list[dict]) -> tuple[list[dict], int]:
    """Drop scrape events where every gym simultaneously reads 0% -- these
    reflect the site showing a "closed" state, not real crowd data."""
    by_ts = defaultdict(list)
    for r in rows:
        by_ts[r["timestamp"]].append(r)

    excluded_ts = set()
    for ts, group in by_ts.items():
        numeric = [r["crowd_value"] for r in group if r["crowd_value"] is not None]
        if numeric and all(v == 0 for v in numeric):
            excluded_ts.add(ts)

    kept = [r for r in rows if r["timestamp"] not in excluded_ts]
    return kept, len(excluded_ts)


def linear_trend_slope(series: list[float]) -> float | None:
    """Least-squares slope of series against its index (0..n-1)."""
    n = len(series)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = statistics.mean(xs)
    mean_y = statistics.mean(series)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, series))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return numerator / denominator


def day_pattern_for(entries: list[dict]) -> list[dict]:
    """15-min crowd profile, 7:00am-9:45pm SGT, for the given entries."""
    by_slot = defaultdict(list)
    for e in entries:
        if e["crowd_value"] is None:
            continue
        ts = e["timestamp_sgt"]
        slot = (ts.hour, (ts.minute // 15) * 15)
        if slot in DAY_PATTERN_SLOTS_SET:
            by_slot[slot].append(e["crowd_value"])
    return [
        {
            "label": f"{h:02d}:{m:02d}",
            "hour": h,
            "minute": m,
            "average": statistics.mean(by_slot[(h, m)]) if (h, m) in by_slot else None,
        }
        for h, m in DAY_PATTERN_SLOTS
    ]


def dow_day_pattern_for(entries: list[dict]) -> dict:
    """{weekday_name: 15-min day_pattern} -- used to predict the least
    crowded upcoming slot on the same weekday as "now"."""
    by_dow: dict = defaultdict(list)
    for e in entries:
        by_dow[e["timestamp_sgt"].weekday()].append(e)
    return {
        WEEKDAY_NAMES[i]: day_pattern_for(by_dow.get(i, []))
        for i in range(7)
    }


def day_of_week_pattern_for(entries: list[dict]) -> list[dict]:
    """Average crowd per weekday (Mon..Sun), SGT calendar day."""
    by_dow = defaultdict(list)
    for e in entries:
        if e["crowd_value"] is None:
            continue
        by_dow[e["timestamp_sgt"].weekday()].append(e["crowd_value"])
    return [
        {
            "day": WEEKDAY_NAMES[i],
            "average": statistics.mean(by_dow[i]) if i in by_dow else None,
            "readings": len(by_dow.get(i, [])),
        }
        for i in range(7)
    ]


def dow_hour_matrix_for(entries: list[dict]) -> dict:
    """{weekday_name: {hour: average}} for the 'predicted crowd now' feature."""
    by_dow_hour = defaultdict(list)
    for e in entries:
        if e["crowd_value"] is None:
            continue
        ts = e["timestamp_sgt"]
        by_dow_hour[(ts.weekday(), ts.hour)].append(e["crowd_value"])
    matrix: dict = {name: {} for name in WEEKDAY_NAMES}
    for (dow, hour), vals in by_dow_hour.items():
        matrix[WEEKDAY_NAMES[dow]][str(hour)] = round(statistics.mean(vals), 1)
    return matrix


def build_report_data(all_rows: list[dict]) -> dict:
    rows, excluded_events = exclude_all_zero_events(all_rows)
    numeric_rows = [r for r in rows if r["crowd_value"] is not None]

    data: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_readings": len(rows),
        "numeric_readings": len(numeric_rows),
        "excluded_all_zero_events": excluded_events,
    }

    if not rows:
        data["has_data"] = False
        return data
    data["has_data"] = True

    span_start = min(r["timestamp_sgt"] for r in rows)
    span_end = max(r["timestamp_sgt"] for r in rows)
    data["span_start"] = span_start.isoformat()
    data["span_end"] = span_end.isoformat()

    # ---- per-gym stats ----
    by_gym = defaultdict(list)
    for r in rows:
        by_gym[r["gym_name"]].append(r)

    per_gym = []
    per_gym_day_pattern = {}
    per_gym_dow_pattern = {}
    per_gym_dow_hour = {}
    per_gym_dow_day_pattern = {}
    for gym, entries in sorted(by_gym.items()):
        nums = [e for e in entries if e["crowd_value"] is not None]
        per_gym_day_pattern[gym] = day_pattern_for(entries)
        per_gym_dow_pattern[gym] = day_of_week_pattern_for(entries)
        per_gym_dow_hour[gym] = dow_hour_matrix_for(entries)
        per_gym_dow_day_pattern[gym] = dow_day_pattern_for(entries)

        if not nums:
            per_gym.append(
                {"name": gym, "count": len(entries), "average": None, "peak": None,
                 "peak_time": None, "min": None, "min_time": None, "stdev": None,
                 "busiest_hour": None, "quietest_hour": None}
            )
            continue

        values = [e["crowd_value"] for e in nums]
        peak_entry = max(nums, key=lambda e: e["crowd_value"])
        min_entry = min(nums, key=lambda e: e["crowd_value"])

        by_hour = defaultdict(list)
        for e in nums:
            by_hour[e["timestamp_sgt"].hour].append(e["crowd_value"])
        hour_avgs = sorted(
            ((h, statistics.mean(v)) for h, v in by_hour.items()), key=lambda x: x[1]
        )
        quietest_hour = hour_avgs[0] if hour_avgs else None
        busiest_hour = hour_avgs[-1] if hour_avgs else None

        per_gym.append(
            {
                "name": gym,
                "count": len(entries),
                "average": statistics.mean(values),
                "peak": peak_entry["crowd_value"],
                "peak_time": peak_entry["timestamp_sgt"].isoformat(),
                "min": min_entry["crowd_value"],
                "min_time": min_entry["timestamp_sgt"].isoformat(),
                "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                "busiest_hour": busiest_hour[0] if busiest_hour else None,
                "busiest_hour_avg": busiest_hour[1] if busiest_hour else None,
                "quietest_hour": quietest_hour[0] if quietest_hour else None,
                "quietest_hour_avg": quietest_hour[1] if quietest_hour else None,
            }
        )
    data["per_gym"] = per_gym
    data["gym_count"] = len(per_gym)
    data["per_gym_day_pattern"] = per_gym_day_pattern
    data["per_gym_dow_pattern"] = per_gym_dow_pattern
    data["per_gym_dow_hour"] = per_gym_dow_hour
    data["per_gym_dow_day_pattern"] = per_gym_dow_day_pattern

    ranked_by_avg = sorted(
        (g for g in per_gym if g["average"] is not None),
        key=lambda g: g["average"], reverse=True,
    )
    data["top_busiest_gyms"] = [
        {"name": g["name"], "average": g["average"]} for g in ranked_by_avg[:5]
    ]
    data["top_quietest_gyms"] = [
        {"name": g["name"], "average": g["average"]} for g in ranked_by_avg[-5:][::-1]
    ]
    data["most_variable_gyms"] = [
        {"name": g["name"], "stdev": g["stdev"]}
        for g in sorted(per_gym, key=lambda g: g["stdev"] or 0, reverse=True)[:5]
    ]

    # ---- day trend, all gyms combined (15-min, 7am-9:45pm SGT) ----
    data["day_pattern"] = day_pattern_for(rows)
    known_slots = sorted(
        ((s["label"], s["average"]) for s in data["day_pattern"] if s["average"] is not None),
        key=lambda x: x[1],
    )
    data["quietest_times"] = [{"label": l, "average": a} for l, a in known_slots[:3]]
    data["busiest_times"] = [{"label": l, "average": a} for l, a in known_slots[-3:][::-1]]

    # ---- day-of-week pattern, all gyms combined ----
    data["day_of_week_pattern"] = day_of_week_pattern_for(rows)

    # ---- weekday vs weekend (SGT calendar day) ----
    weekday_vals = [r["crowd_value"] for r in numeric_rows if r["timestamp_sgt"].weekday() < 5]
    weekend_vals = [r["crowd_value"] for r in numeric_rows if r["timestamp_sgt"].weekday() >= 5]
    data["weekday_average"] = statistics.mean(weekday_vals) if weekday_vals else None
    data["weekend_average"] = statistics.mean(weekend_vals) if weekend_vals else None

    # ---- daily trend (SGT calendar date; used for the trend-direction slope,
    # not shown as its own chart per user preference for day-of-week instead) ----
    by_day = defaultdict(list)
    for r in numeric_rows:
        by_day[r["timestamp_sgt"].date().isoformat()].append(r["crowd_value"])
    daily_trend = sorted(
        ({"date": day, "average": statistics.mean(vals)} for day, vals in by_day.items()),
        key=lambda d: d["date"],
    )

    # ---- weekly trend (ISO year-week buckets, SGT) ----
    by_week = defaultdict(list)
    for r in numeric_rows:
        iso_year, iso_week, _ = r["timestamp_sgt"].isocalendar()
        by_week[(iso_year, iso_week)].append(r["crowd_value"])
    weekly_trend = sorted(
        (
            {
                "week": f"{year}-W{week:02d}",
                "average": statistics.mean(vals),
                "readings": len(vals),
            }
            for (year, week), vals in by_week.items()
        ),
        key=lambda d: d["week"],
    )
    data["weekly_trend"] = weekly_trend

    slope = linear_trend_slope([d["average"] for d in daily_trend])
    data["trend_slope_per_day"] = slope
    if slope is None:
        data["trend_direction"] = "not enough days yet"
    elif abs(slope) < 0.5:
        data["trend_direction"] = "flat"
    elif slope > 0:
        data["trend_direction"] = "rising"
    else:
        data["trend_direction"] = "falling"

    return data


def render_markdown(data: dict) -> str:
    lines = ["# ActiveSG Gym Crowd Report", ""]
    if not data.get("has_data"):
        lines.append("No data available yet.")
        return "\n".join(lines)

    lines.append(
        f"Data range (SGT): **{data['span_start']}** to **{data['span_end']}** "
        f"({data['total_readings']} readings across {data['gym_count']} gyms)"
    )
    if data["excluded_all_zero_events"]:
        lines.append(
            f"\n_{data['excluded_all_zero_events']} scrape events excluded: every gym "
            "read 0% simultaneously (treated as 'closed', not real data)._"
        )
    lines.append("")

    lines.append("## Per-gym summary")
    lines.append("")
    lines.append("| Gym | Readings | Avg | Peak | Min | Std dev | Busiest hour | Quietest hour |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for g in data["per_gym"]:
        def fmt(v):
            return f"{v:.1f}" if v is not None else "n/a"
        busiest = f"{g['busiest_hour']:02d}:00" if g.get("busiest_hour") is not None else "n/a"
        quietest = f"{g['quietest_hour']:02d}:00" if g.get("quietest_hour") is not None else "n/a"
        lines.append(
            f"| {g['name']} | {g['count']} | {fmt(g['average'])} | {fmt(g['peak'])} | "
            f"{fmt(g['min'])} | {fmt(g['stdev'])} | {busiest} | {quietest} |"
        )
    lines.append("")

    lines.append("## Rankings")
    lines.append("")
    lines.append("**Busiest gyms (highest average crowd):**")
    for g in data["top_busiest_gyms"]:
        lines.append(f"- {g['name']} — avg {g['average']:.1f}")
    lines.append("")
    lines.append("**Quietest gyms (lowest average crowd):**")
    for g in data["top_quietest_gyms"]:
        lines.append(f"- {g['name']} — avg {g['average']:.1f}")
    lines.append("")
    lines.append("**Most variable gyms (least predictable crowd level):**")
    for g in data["most_variable_gyms"]:
        lines.append(f"- {g['name']} — std dev {g['stdev']:.1f}")
    lines.append("")

    lines.append("## Day trend, 7am-9:45pm (SGT, all gyms combined)")
    lines.append("")
    lines.append("**Quietest times:**")
    for t in data["quietest_times"]:
        lines.append(f"- {t['label']} — avg {t['average']:.1f}")
    lines.append("")
    lines.append("**Busiest times:**")
    for t in data["busiest_times"]:
        lines.append(f"- {t['label']} — avg {t['average']:.1f}")
    lines.append("")

    lines.append("## Day-of-week pattern (SGT)")
    lines.append("")
    lines.append("| Day | Avg crowd | Readings |")
    lines.append("|---|---|---|")
    for d in data["day_of_week_pattern"]:
        avg = f"{d['average']:.1f}" if d["average"] is not None else "n/a"
        lines.append(f"| {d['day']} | {avg} | {d['readings']} |")
    lines.append("")

    lines.append("## Weekday vs weekend")
    lines.append("")
    wd = data["weekday_average"]
    we = data["weekend_average"]
    lines.append(f"- Weekday average: {f'{wd:.1f}' if wd is not None else 'n/a'}")
    lines.append(f"- Weekend average: {f'{we:.1f}' if we is not None else 'n/a'}")
    lines.append("")

    lines.append(f"Overall trend direction: **{data['trend_direction']}**"
                  + (f" ({data['trend_slope_per_day']:+.2f} crowd pts/day)"
                     if data["trend_slope_per_day"] is not None else ""))
    lines.append("")

    if len(data["weekly_trend"]) > 1:
        lines.append("## Week-over-week")
        lines.append("")
        lines.append("| Week | Avg crowd | Readings |")
        lines.append("|---|---|---|")
        for w in data["weekly_trend"]:
            lines.append(f"| {w['week']} | {w['average']:.1f} | {w['readings']} |")
        lines.append("")

    return "\n".join(lines)


def render_html(markdown_body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>ActiveSG Gym Crowd Report</title>"
        "<style>body{font-family:sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;}"
        "td,th{border:1px solid #ccc;padding:6px 10px;text-align:left;}</style>"
        "</head><body><pre style='white-space:pre-wrap;font-family:inherit;'>"
        f"{markdown_body}</pre></body></html>"
    )


def render_website(data: dict) -> str:
    payload = json.dumps(data)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Crowd levels at ActiveSG gyms across Singapore, updated from real scraped data.">
<title>ActiveSG Gym Crowd Dashboard</title>
<script src="chart.umd.js"></script>
<style>
  :root {{
    color-scheme: dark;
    --bg: #0b0d12;
    --card-bg: #161a22;
    --card-bg-raised: #1a1f29;
    --border: #2a2f3d;
    --text: #f1f3f5;
    --text-muted: #a7aebb;
    --text-dim: #7d8492;
    --accent: #6c9bff;
    --accent-strong: #4f7fe8;
    --good: #4ade80;
    --warn: #fbbf24;
    --focus: #8ab4ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    max-width: 1120px; margin: 0 auto; padding: 32px 20px 72px;
    background: var(--bg); color: var(--text); line-height: 1.5; font-size: 16px;
  }}
  h1 {{ font-size: 1.75rem; font-weight: 700; margin: 0 0 6px; letter-spacing: -0.01em; }}
  h2 {{ font-size: 1.2rem; font-weight: 600; margin: 0 0 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
  h3 {{ font-size: 1rem; font-weight: 600; margin: 0 0 10px; color: var(--text); }}
  p {{ margin: 0; }}
  .sub {{ color: var(--text-muted); margin-bottom: 4px; font-size: 0.95rem; }}
  .visually-hidden {{
    position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0;
    overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
  }}
  a {{ color: var(--accent); }}
  button {{ font-family: inherit; }}
  button:focus-visible, a:focus-visible {{
    outline: 3px solid var(--focus); outline-offset: 2px; border-radius: 4px;
  }}

  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 32px; }}
  .card {{
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 18px;
  }}
  .card .label {{ color: var(--text-muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }}
  .card .value {{ font-size: 1.75rem; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; }}

  section {{ margin-bottom: 44px; }}
  .chart-wrap {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .chart-caption {{ color: var(--text-dim); font-size: 0.82rem; margin-top: 10px; }}

  table {{ border-collapse: collapse; width: 100%; font-size: 0.92rem; }}
  th, td {{ text-align: left; padding: 11px 12px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--text-muted); font-weight: 600; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}
  .table-scroll {{ overflow-x: auto; border-radius: 12px; }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  .rank-list {{ list-style: none; padding: 0; margin: 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  .rank-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }}
  .rank-list li:last-child {{ border-bottom: none; }}
  .rank-list .name {{ color: var(--text); }}
  .rank-list .val {{ color: var(--text-muted); font-weight: 600; }}

  footer {{ color: var(--text-dim); font-size: 0.82rem; margin-top: 48px; }}

  nav.tabs {{ display: flex; gap: 4px; margin-bottom: 28px; border-bottom: 1px solid var(--border); }}
  .tab-btn {{
    background: none; border: none; color: var(--text-muted); font-size: 1rem; font-weight: 500;
    padding: 12px 18px; cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -1px;
  }}
  .tab-btn:hover {{ color: var(--text); }}
  .tab-btn[aria-selected="true"] {{ color: var(--text); border-bottom-color: var(--accent); }}
  .tab-panel[hidden] {{ display: none; }}

  .gym-tabs {{ display: flex; gap: 8px; overflow-x: auto; padding: 4px 4px 14px; margin-bottom: 8px; }}
  .gym-pill {{
    background: var(--card-bg); border: 1px solid var(--border); color: var(--text-muted); border-radius: 999px;
    padding: 9px 16px; font-size: 0.88rem; font-weight: 500; white-space: nowrap; cursor: pointer; flex: none;
    min-height: 40px;
  }}
  .gym-pill:hover {{ color: var(--text); border-color: var(--accent); }}
  .gym-pill[aria-selected="true"] {{ background: var(--accent-strong); border-color: var(--accent-strong); color: #fff; }}

  nav.subtabs {{ display: flex; gap: 4px; margin: 4px 0 24px; }}
  .subtab-btn {{
    background: var(--card-bg); border: 1px solid var(--border); color: var(--text-muted);
    padding: 9px 16px; font-size: 0.9rem; font-weight: 500; cursor: pointer; border-radius: 8px;
  }}
  .subtab-btn:hover {{ color: var(--text); }}
  .subtab-btn[aria-selected="true"] {{ background: var(--accent-strong); border-color: var(--accent-strong); color: #fff; }}
  .subtab-panel[hidden] {{ display: none; }}

  .predict-card {{
    background: linear-gradient(135deg, #1c2740, #161a22); border: 1px solid #2f3c5c;
    border-radius: 12px; padding: 22px; margin-bottom: 20px;
  }}
  .predict-card .label {{ color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }}
  .predict-card .value {{ font-size: 2.1rem; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }}
  .predict-card .note {{ color: var(--text-dim); font-size: 0.85rem; margin-top: 8px; }}

  .best-time-hero {{
    background: linear-gradient(135deg, #16321f, #161a22); border: 1px solid #2a4b34;
    border-radius: 12px; padding: 24px; margin-bottom: 20px;
  }}
  .best-time-hero .label {{ color: var(--good); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }}
  .best-time-hero .value {{ font-size: 2.3rem; font-weight: 700; margin-top: 8px; }}
  .best-time-hero .value .pct {{ color: var(--text-muted); font-size: 1.3rem; font-weight: 600; margin-left: 10px; }}
  .best-time-hero .note {{ color: var(--text-dim); font-size: 0.85rem; margin-top: 10px; }}
  .alt-slots {{ margin-top: 18px; }}
  .alt-slots ul {{ list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-wrap: wrap; gap: 8px; }}
  .alt-slots li {{
    background: var(--card-bg-raised); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 14px; font-size: 0.88rem; font-variant-numeric: tabular-nums;
  }}
</style>
</head>
<body>
<h1>ActiveSG Gym Crowd Dashboard</h1>
<p class="sub" id="subtitle">Loading…</p>
<p class="sub" id="fetch-status" style="font-size:0.8rem;" role="status"></p>

<nav class="tabs" role="tablist" aria-label="Dashboard sections">
  <button class="tab-btn" id="tabbtn-overview" role="tab" aria-selected="true" aria-controls="tab-overview" data-tab="overview">Overview</button>
  <button class="tab-btn" id="tabbtn-bygym" role="tab" aria-selected="false" aria-controls="tab-bygym" data-tab="bygym">By Gym</button>
</nav>

<main>
<div class="tab-panel" id="tab-overview" role="tabpanel" aria-labelledby="tabbtn-overview">

<div class="grid" id="stat-cards" aria-label="Summary statistics"></div>

<section aria-labelledby="h-gym-avg">
  <h2 id="h-gym-avg">Average crowd per gym</h2>
  <div class="chart-wrap"><canvas id="gymChart" height="110" role="img" aria-label="Bar chart of average crowd percentage per gym"></canvas></div>
</section>

<section aria-labelledby="h-day-trend">
  <h2 id="h-day-trend">Day trend, 7am–9:45pm (SGT)</h2>
  <div class="chart-wrap">
    <canvas id="dayPatternChart" height="90" role="img" aria-label="Line chart of average crowd percentage through the day, all gyms combined"></canvas>
    <p class="chart-caption" id="day-trend-caption"></p>
  </div>
</section>

<div class="two-col">
  <section aria-labelledby="h-dow">
    <h2 id="h-dow">Day-of-week pattern</h2>
    <div class="chart-wrap"><canvas id="dowChart" height="180" role="img" aria-label="Bar chart of average crowd percentage by day of week"></canvas></div>
  </section>
  <section aria-labelledby="h-weekly">
    <h2 id="h-weekly">Week-over-week</h2>
    <div class="chart-wrap"><canvas id="weeklyChart" height="180" role="img" aria-label="Bar chart of average crowd percentage per calendar week"></canvas></div>
  </section>
</div>

<div class="two-col">
  <section aria-labelledby="h-busiest">
    <h2 id="h-busiest">Busiest gyms</h2>
    <ul class="rank-list" id="busiest-list"></ul>
  </section>
  <section aria-labelledby="h-quietest">
    <h2 id="h-quietest">Quietest gyms</h2>
    <ul class="rank-list" id="quietest-list"></ul>
  </section>
</div>

<section aria-labelledby="h-variable">
  <h2 id="h-variable">Most unpredictable gyms (highest variability)</h2>
  <ul class="rank-list" id="variable-list"></ul>
</section>

<section aria-labelledby="h-allgyms">
  <h2 id="h-allgyms">All gyms</h2>
  <div class="table-scroll">
  <table id="gym-table">
    <caption class="visually-hidden">Full statistics for every gym: readings, average, peak, minimum, standard deviation, busiest and quietest hour</caption>
    <thead>
      <tr><th scope="col">Gym</th><th scope="col" class="num">Readings</th><th scope="col" class="num">Avg</th>
          <th scope="col" class="num">Peak</th><th scope="col" class="num">Min</th>
          <th scope="col" class="num">Std dev</th><th scope="col">Busiest hour</th><th scope="col">Quietest hour</th></tr>
    </thead>
    <tbody></tbody>
  </table>
  </div>
</section>

</div>

<div class="tab-panel" id="tab-bygym" role="tabpanel" aria-labelledby="tabbtn-bygym" hidden>
  <div class="gym-tabs" id="gym-tabs" role="tablist" aria-label="Choose a gym"></div>

  <nav class="subtabs" role="tablist" aria-label="Gym detail view">
    <button class="subtab-btn" id="subtabbtn-charts" role="tab" aria-selected="true" aria-controls="subtab-charts" data-subtab="charts">Charts</button>
    <button class="subtab-btn" id="subtabbtn-besttime" role="tab" aria-selected="false" aria-controls="subtab-besttime" data-subtab="besttime">Best Time to Visit</button>
  </nav>

  <div class="subtab-panel" id="subtab-charts" role="tabpanel" aria-labelledby="subtabbtn-charts"></div>
  <div class="subtab-panel" id="subtab-besttime" role="tabpanel" aria-labelledby="subtabbtn-besttime" hidden></div>
</div>
</main>

<footer id="footer"></footer>

<script id="report-data" type="application/json">{payload}</script>
<script>
const embeddedData = JSON.parse(document.getElementById('report-data').textContent);
let data = embeddedData;
let charts = {{}};
const DAY_NAMES_SUN_FIRST = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function fmtPct(v, digits = 1) {{ return v === null || v === undefined ? 'n/a' : v.toFixed(digits) + '%'; }}
function fmtNum(v) {{ return v === null || v === undefined ? 'n/a' : Number(v).toLocaleString('en-US'); }}
function hourLabel(h) {{ return h === null || h === undefined ? 'n/a' : String(h).padStart(2, '0') + ':00'; }}
function destroyChart(id) {{ if (charts[id]) {{ charts[id].destroy(); delete charts[id]; }} }}
function nowSgt() {{ return new Date(new Date().toLocaleString('en-US', {{ timeZone: 'Asia/Singapore' }})); }}

function renderOverview() {{
  if (!data.has_data) {{
    document.getElementById('subtitle').textContent = 'No data collected yet.';
    return;
  }}
  document.getElementById('subtitle').textContent =
    `${{data.span_start}} to ${{data.span_end}} (SGT) — ${{fmtNum(data.total_readings)}} readings across ${{data.gym_count}} gyms`
    + (data.excluded_all_zero_events ? ` (${{data.excluded_all_zero_events}} closed-state events excluded)` : '');

  const cards = [
    ['Weekday average', fmtPct(data.weekday_average)],
    ['Weekend average', fmtPct(data.weekend_average)],
    ['Trend', data.trend_direction],
    ['Total readings', fmtNum(data.total_readings)],
  ];
  document.getElementById('stat-cards').innerHTML = cards.map(([label, value]) =>
    `<div class="card"><div class="label">${{label}}</div><div class="value">${{value}}</div></div>`
  ).join('');

  const gyms = data.per_gym.filter(g => g.average !== null).sort((a, b) => b.average - a.average);
  destroyChart('gymChart');
  charts.gymChart = new Chart(document.getElementById('gymChart'), {{
    type: 'bar',
    data: {{
      labels: gyms.map(g => g.name),
      datasets: [{{ label: 'Average crowd %', data: gyms.map(g => g.average), backgroundColor: '#6c9bff', borderRadius: 4 }}]
    }},
    options: {{
      indexAxis: 'y', responsive: true,
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.x.toFixed(1) + '%' }} }} }},
      scales: {{ x: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }}
    }}
  }});

  const busiestSlot = data.day_pattern.reduce((a, b) => (b.average !== null && (a === null || b.average > a.average)) ? b : a, null);
  const quietestSlot = data.day_pattern.reduce((a, b) => (b.average !== null && (a === null || b.average < a.average)) ? b : a, null);
  document.getElementById('day-trend-caption').textContent =
    busiestSlot && quietestSlot ? `Busiest around ${{busiestSlot.label}} (${{fmtPct(busiestSlot.average)}}), quietest around ${{quietestSlot.label}} (${{fmtPct(quietestSlot.average)}}).` : '';
  destroyChart('dayPatternChart');
  charts.dayPatternChart = new Chart(document.getElementById('dayPatternChart'), {{
    type: 'line',
    data: {{
      labels: data.day_pattern.map(s => s.label),
      datasets: [{{ label: 'Avg crowd %', data: data.day_pattern.map(s => s.average),
                   borderColor: '#f2a65a', backgroundColor: 'rgba(242,166,90,0.15)', fill: true, tension: 0.3, pointRadius: 0 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y.toFixed(1) + '%' }} }} }},
                scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }} }}
  }});

  destroyChart('dowChart');
  charts.dowChart = new Chart(document.getElementById('dowChart'), {{
    type: 'bar',
    data: {{
      labels: data.day_of_week_pattern.map(d => d.day.slice(0,3)),
      datasets: [{{ label: 'Avg crowd %', data: data.day_of_week_pattern.map(d => d.average), backgroundColor: '#4ade80', borderRadius: 4 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y.toFixed(1) + '%' }} }} }},
                scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }} }}
  }});

  destroyChart('weeklyChart');
  charts.weeklyChart = new Chart(document.getElementById('weeklyChart'), {{
    type: 'bar',
    data: {{
      labels: data.weekly_trend.map(w => w.week),
      datasets: [{{ label: 'Avg crowd %', data: data.weekly_trend.map(w => w.average), backgroundColor: '#c17ee0', borderRadius: 4 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y.toFixed(1) + '%' }} }} }},
                scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }} }}
  }});

  document.getElementById('busiest-list').innerHTML = data.top_busiest_gyms.map(g =>
    `<li><span class="name">${{g.name}}</span><span class="val">${{fmtPct(g.average)}}</span></li>`).join('');
  document.getElementById('quietest-list').innerHTML = data.top_quietest_gyms.map(g =>
    `<li><span class="name">${{g.name}}</span><span class="val">${{fmtPct(g.average)}}</span></li>`).join('');
  document.getElementById('variable-list').innerHTML = data.most_variable_gyms.map(g =>
    `<li><span class="name">${{g.name}}</span><span class="val">±${{fmtPct(g.stdev)}}</span></li>`).join('');

  const tbody = document.querySelector('#gym-table tbody');
  tbody.innerHTML = data.per_gym.map(g => `<tr>
    <td>${{g.name}}</td><td class="num">${{fmtNum(g.count)}}</td><td class="num">${{fmtPct(g.average)}}</td><td class="num">${{fmtPct(g.peak)}}</td>
    <td class="num">${{fmtPct(g.min)}}</td><td class="num">${{fmtPct(g.stdev)}}</td>
    <td>${{hourLabel(g.busiest_hour)}}</td><td>${{hourLabel(g.quietest_hour)}}</td>
  </tr>`).join('');

  document.getElementById('footer').textContent = 'Generated ' + data.generated_at;
}}

let selectedGym = null;

function predictedCrowdNow(gymName) {{
  const matrix = data.per_gym_dow_hour[gymName];
  if (!matrix) return null;
  const now = nowSgt();
  const dayName = DAY_NAMES_SUN_FIRST[now.getDay()];
  const hour = now.getHours();
  const val = matrix[dayName] ? matrix[dayName][String(hour)] : undefined;
  return {{ dayName, hour, value: val === undefined ? null : val }};
}}

function bestTimeToVisit(gymName) {{
  const patternByDow = data.per_gym_dow_day_pattern[gymName];
  if (!patternByDow) return null;
  const now = nowSgt();
  const dayName = DAY_NAMES_SUN_FIRST[now.getDay()];
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  const todaySlots = (patternByDow[dayName] || []).filter(s => s.average !== null);
  let source = todaySlots.filter(s => (s.hour * 60 + s.minute) >= nowMinutes);
  let when = 'later today';
  if (!source.length) {{
    const tomorrowName = DAY_NAMES_SUN_FIRST[(now.getDay() + 1) % 7];
    source = (patternByDow[tomorrowName] || []).filter(s => s.average !== null);
    when = 'tomorrow';
  }}
  if (!source.length) return null;
  const sorted = [...source].sort((a, b) => a.average - b.average);
  return {{ when, best: sorted[0], alternatives: sorted.slice(1, 4) }};
}}

function renderGymCharts(gymName) {{
  const g = data.per_gym.find(x => x.name === gymName);
  const dayPattern = data.per_gym_day_pattern[gymName] || [];
  const dowPattern = data.per_gym_dow_pattern[gymName] || [];
  const pred = predictedCrowdNow(gymName);

  const container = document.getElementById('subtab-charts');
  container.innerHTML = `
    <div class="predict-card">
      <div class="label">Predicted crowd right now</div>
      <div class="value">${{pred && pred.value !== null ? fmtPct(pred.value) : 'n/a — no historical data for this day/hour yet'}}</div>
      <div class="note">${{pred ? `Based on the historical average for ${{pred.dayName}} ${{String(pred.hour).padStart(2,'0')}}:00 SGT. Not a live reading.` : ''}}</div>
    </div>
    <div class="grid">
      <div class="card"><div class="label">Average</div><div class="value">${{fmtPct(g?.average)}}</div></div>
      <div class="card"><div class="label">Peak</div><div class="value">${{fmtPct(g?.peak)}}</div></div>
      <div class="card"><div class="label">Min</div><div class="value">${{fmtPct(g?.min)}}</div></div>
      <div class="card"><div class="label">Std dev</div><div class="value">±${{fmtPct(g?.stdev)}}</div></div>
    </div>
    <section aria-labelledby="h-gym-day-trend">
      <h2 id="h-gym-day-trend">${{gymName}} — day trend, 7am–9:45pm (SGT)</h2>
      <div class="chart-wrap"><canvas id="gymDayPatternChart" height="90" role="img" aria-label="Line chart of average crowd percentage through the day for ${{gymName}}"></canvas></div>
    </section>
    <section aria-labelledby="h-gym-dow">
      <h2 id="h-gym-dow">${{gymName}} — day-of-week pattern</h2>
      <div class="chart-wrap"><canvas id="gymDowChart" height="180" role="img" aria-label="Bar chart of average crowd percentage by day of week for ${{gymName}}"></canvas></div>
    </section>
  `;

  destroyChart('gymDayPatternChart');
  charts.gymDayPatternChart = new Chart(document.getElementById('gymDayPatternChart'), {{
    type: 'line',
    data: {{
      labels: dayPattern.map(s => s.label),
      datasets: [{{ label: 'Avg crowd %', data: dayPattern.map(s => s.average),
                   borderColor: '#6c9bff', backgroundColor: 'rgba(108,155,255,0.15)', fill: true, tension: 0.3, pointRadius: 0 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y.toFixed(1) + '%' }} }} }},
                scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }} }}
  }});

  destroyChart('gymDowChart');
  charts.gymDowChart = new Chart(document.getElementById('gymDowChart'), {{
    type: 'bar',
    data: {{
      labels: dowPattern.map(d => d.day.slice(0,3)),
      datasets: [{{ label: 'Avg crowd %', data: dowPattern.map(d => d.average), backgroundColor: '#4ade80', borderRadius: 4 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: c => c.parsed.y.toFixed(1) + '%' }} }} }},
                scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Average crowd %' }} }} }} }}
  }});
}}

function renderBestTime(gymName) {{
  const result = bestTimeToVisit(gymName);
  const container = document.getElementById('subtab-besttime');
  if (!result) {{
    container.innerHTML = `<p class="sub">Not enough historical data yet to predict the best time to visit ${{gymName}}.</p>`;
    return;
  }}
  const {{ when, best, alternatives }} = result;
  container.innerHTML = `
    <div class="best-time-hero">
      <div class="label">Next best time to go${{when === 'tomorrow' ? ' (today is over)' : ''}}</div>
      <div class="value">${{when === 'tomorrow' ? 'Tomorrow ' : ''}}${{best.label}} SGT<span class="pct">${{fmtPct(best.average)}} predicted</span></div>
      <div class="note">Based on the historical average for this time slot on ${{when === 'tomorrow' ? DAY_NAMES_SUN_FIRST[(nowSgt().getDay()+1)%7] : DAY_NAMES_SUN_FIRST[nowSgt().getDay()]}}s. Not a live reading — actual crowd on the day may differ.</div>
      ${{alternatives.length ? `
      <div class="alt-slots">
        <h3>Other good times</h3>
        <ul>
          ${{alternatives.map(a => `<li>${{a.label}} — ${{fmtPct(a.average)}}</li>`).join('')}}
        </ul>
      </div>` : ''}}
    </div>
  `;
}}

function renderGymDetail(gymName) {{
  selectedGym = gymName;
  document.querySelectorAll('.gym-pill').forEach(p => {{
    const active = p.dataset.gym === gymName;
    p.setAttribute('aria-selected', active ? 'true' : 'false');
  }});
  renderGymCharts(gymName);
  renderBestTime(gymName);
}}

function renderGymTabs() {{
  const tabsEl = document.getElementById('gym-tabs');
  const names = data.per_gym.map(g => g.name);
  tabsEl.innerHTML = names.map(n =>
    `<button class="gym-pill" role="tab" aria-selected="false" data-gym="${{n}}">${{n}}</button>`).join('');
  tabsEl.querySelectorAll('.gym-pill').forEach(btn => {{
    btn.addEventListener('click', () => renderGymDetail(btn.dataset.gym));
  }});
  if (names.length) renderGymDetail(selectedGym && names.includes(selectedGym) ? selectedGym : names[0]);
}}

function renderAll() {{
  renderOverview();
  renderGymTabs();
}}

document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.setAttribute('aria-selected', 'false'));
    document.querySelectorAll('main > .tab-panel').forEach(p => p.hidden = true);
    btn.setAttribute('aria-selected', 'true');
    document.getElementById('tab-' + btn.dataset.tab).hidden = false;
  }});
}});

document.querySelectorAll('.subtab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.subtab-btn').forEach(b => b.setAttribute('aria-selected', 'false'));
    document.querySelectorAll('.subtab-panel').forEach(p => p.hidden = true);
    btn.setAttribute('aria-selected', 'true');
    document.getElementById('subtab-' + btn.dataset.subtab).hidden = false;
  }});
}});

// Pull the latest already-collected data on every page load rather than
// relying solely on the snapshot embedded at generation time. This does
// NOT scrape activesg.gov.sg live (that site is Cloudflare-protected and
// needs a real headless browser, which a static page can't run) -- it
// fetches whatever report_data.json currently holds in this repo, which
// is refreshed each time the scraper + report workflow run.
renderAll();
fetch('report_data.json?t=' + Date.now())
  .then(r => r.ok ? r.json() : null)
  .then(fresh => {{
    if (fresh && fresh.has_data) {{
      data = fresh;
      document.getElementById('fetch-status').textContent = 'Live data loaded at page open.';
      renderAll();
    }}
  }})
  .catch(() => {{
    document.getElementById('fetch-status').textContent = '';
  }});
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "data" / "crowd_log.csv"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "report.md"))
    parser.add_argument("--html", action="store_true", help="also write an .html version")
    parser.add_argument("--website", action="store_true", help="also write docs/index.html dashboard")
    parser.add_argument("--website-out", default=str(ROOT / "docs" / "index.html"))
    args = parser.parse_args()

    csv_path = Path(args.csv)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        print(f"No CSV found at {csv_path}")
        return

    rows = load_rows(csv_path)
    data = build_report_data(rows)

    markdown = render_markdown(data)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {out_path}")

    json_path = out_path.with_name("report_data.json")
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {json_path}")

    if args.html:
        html_path = out_path.with_suffix(".html")
        html_path.write_text(render_html(markdown), encoding="utf-8")
        print(f"Wrote {html_path}")

    if args.website:
        website_path = Path(args.website_out)
        website_path.parent.mkdir(parents=True, exist_ok=True)
        website_path.write_text(render_website(data), encoding="utf-8")
        (website_path.parent / ".nojekyll").touch()
        # Also drop a copy of the data next to index.html so the page can
        # fetch the latest version client-side on every visit.
        (website_path.parent / "report_data.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        print(f"Wrote {website_path}")


if __name__ == "__main__":
    main()
