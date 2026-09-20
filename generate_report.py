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
    for gym, entries in sorted(by_gym.items()):
        nums = [e for e in entries if e["crowd_value"] is not None]
        per_gym_day_pattern[gym] = day_pattern_for(entries)
        per_gym_dow_pattern[gym] = day_of_week_pattern_for(entries)
        per_gym_dow_hour[gym] = dow_hour_matrix_for(entries)

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
<title>ActiveSG Gym Crowd Dashboard</title>
<script src="chart.umd.js"></script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; background: #0b0d12; color: #e6e8eb; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .sub {{ color: #9aa2ad; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 28px; }}
  .card {{ background: #161a22; border: 1px solid #262b36; border-radius: 10px; padding: 16px; }}
  .card .label {{ color: #9aa2ad; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card .value {{ font-size: 1.6rem; font-weight: 600; margin-top: 4px; }}
  section {{ margin-bottom: 40px; }}
  h2 {{ font-size: 1.15rem; border-bottom: 1px solid #262b36; padding-bottom: 8px; margin-bottom: 16px; }}
  .chart-wrap {{ background: #161a22; border: 1px solid #262b36; border-radius: 10px; padding: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #262b36; }}
  th {{ color: #9aa2ad; font-weight: 600; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  .rank-list {{ list-style: none; padding: 0; margin: 0; }}
  .rank-list li {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #21262f; }}
  footer {{ color: #666e7a; font-size: 0.8rem; margin-top: 40px; }}

  .tabs {{ display: flex; gap: 4px; margin-bottom: 24px; border-bottom: 1px solid #262b36; }}
  .tab-btn {{ background: none; border: none; color: #9aa2ad; font-size: 0.95rem; padding: 10px 16px;
             cursor: pointer; border-bottom: 2px solid transparent; }}
  .tab-btn.active {{ color: #e6e8eb; border-bottom-color: #5b8def; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  .gym-tabs {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 10px; margin-bottom: 20px; }}
  .gym-pill {{ background: #161a22; border: 1px solid #262b36; color: #c7cbd1; border-radius: 999px;
              padding: 7px 14px; font-size: 0.85rem; white-space: nowrap; cursor: pointer; flex: none; }}
  .gym-pill.active {{ background: #5b8def; border-color: #5b8def; color: #fff; }}
  .predict-card {{ background: linear-gradient(135deg, #1c2333, #161a22); border: 1px solid #2c3548;
                   border-radius: 10px; padding: 18px; margin-bottom: 20px; }}
  .predict-card .label {{ color: #9aa2ad; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .predict-card .value {{ font-size: 2rem; font-weight: 700; margin-top: 6px; }}
  .predict-card .note {{ color: #7a828d; font-size: 0.8rem; margin-top: 6px; }}
</style>
</head>
<body>
<h1>ActiveSG Gym Crowd Dashboard</h1>
<p class="sub" id="subtitle">Loading...</p>
<p class="sub" id="fetch-status" style="font-size:0.8rem;"></p>

<div class="tabs">
  <button class="tab-btn active" data-tab="overview">Overview</button>
  <button class="tab-btn" data-tab="bygym">By Gym</button>
</div>

<div class="tab-panel active" id="tab-overview">

<div class="grid" id="stat-cards"></div>

<section>
  <h2>Average crowd per gym</h2>
  <div class="chart-wrap"><canvas id="gymChart" height="110"></canvas></div>
</section>

<section>
  <h2>Day trend, 7am-9:45pm (SGT)</h2>
  <div class="chart-wrap"><canvas id="dayPatternChart" height="90"></canvas></div>
</section>

<div class="two-col">
  <section>
    <h2>Day-of-week pattern</h2>
    <div class="chart-wrap"><canvas id="dowChart" height="180"></canvas></div>
  </section>
  <section>
    <h2>Week-over-week</h2>
    <div class="chart-wrap"><canvas id="weeklyChart" height="180"></canvas></div>
  </section>
</div>

<div class="two-col">
  <section>
    <h2>Busiest gyms</h2>
    <ul class="rank-list" id="busiest-list"></ul>
  </section>
  <section>
    <h2>Quietest gyms</h2>
    <ul class="rank-list" id="quietest-list"></ul>
  </section>
</div>

<section>
  <h2>Most unpredictable gyms (highest variability)</h2>
  <ul class="rank-list" id="variable-list"></ul>
</section>

<section>
  <h2>All gyms</h2>
  <table id="gym-table">
    <thead>
      <tr><th>Gym</th><th>Readings</th><th>Avg</th><th>Peak</th><th>Min</th>
          <th>Std dev</th><th>Busiest hour</th><th>Quietest hour</th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

</div>

<div class="tab-panel" id="tab-bygym">
  <div class="gym-tabs" id="gym-tabs"></div>
  <div id="gym-detail"></div>
</div>

<footer id="footer"></footer>

<script id="report-data" type="application/json">{payload}</script>
<script>
const embeddedData = JSON.parse(document.getElementById('report-data').textContent);
let data = embeddedData;
let charts = {{}};

function fmt(v, digits = 1) {{ return v === null || v === undefined ? 'n/a' : v.toFixed(digits); }}
function hourLabel(h) {{ return h === null || h === undefined ? 'n/a' : String(h).padStart(2, '0') + ':00'; }}
function destroyChart(id) {{ if (charts[id]) {{ charts[id].destroy(); delete charts[id]; }} }}

function renderOverview() {{
  if (!data.has_data) {{
    document.getElementById('subtitle').textContent = 'No data collected yet.';
    return;
  }}
  document.getElementById('subtitle').textContent =
    `${{data.span_start}} to ${{data.span_end}} (SGT) — ${{data.total_readings}} readings across ${{data.gym_count}} gyms`
    + (data.excluded_all_zero_events ? ` (${{data.excluded_all_zero_events}} closed-state events excluded)` : '');

  const cards = [
    ['Weekday average', fmt(data.weekday_average)],
    ['Weekend average', fmt(data.weekend_average)],
    ['Trend', data.trend_direction],
    ['Total readings', data.total_readings],
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
      datasets: [{{ label: 'Average crowd %', data: gyms.map(g => g.average), backgroundColor: '#5b8def' }}]
    }},
    options: {{
      indexAxis: 'y', responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ beginAtZero: true, max: 100 }} }}
    }}
  }});

  destroyChart('dayPatternChart');
  charts.dayPatternChart = new Chart(document.getElementById('dayPatternChart'), {{
    type: 'line',
    data: {{
      labels: data.day_pattern.map(s => s.label),
      datasets: [{{ label: 'Avg crowd %', data: data.day_pattern.map(s => s.average),
                   borderColor: '#f2a65a', backgroundColor: 'rgba(242,166,90,0.15)', fill: true, tension: 0.3, pointRadius: 0 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  destroyChart('dowChart');
  charts.dowChart = new Chart(document.getElementById('dowChart'), {{
    type: 'bar',
    data: {{
      labels: data.day_of_week_pattern.map(d => d.day.slice(0,3)),
      datasets: [{{ label: 'Avg crowd %', data: data.day_of_week_pattern.map(d => d.average), backgroundColor: '#5bd68a' }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  destroyChart('weeklyChart');
  charts.weeklyChart = new Chart(document.getElementById('weeklyChart'), {{
    type: 'bar',
    data: {{
      labels: data.weekly_trend.map(w => w.week),
      datasets: [{{ label: 'Avg crowd %', data: data.weekly_trend.map(w => w.average), backgroundColor: '#c17ee0' }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  document.getElementById('busiest-list').innerHTML = data.top_busiest_gyms.map(g =>
    `<li><span>${{g.name}}</span><span>${{fmt(g.average)}}</span></li>`).join('');
  document.getElementById('quietest-list').innerHTML = data.top_quietest_gyms.map(g =>
    `<li><span>${{g.name}}</span><span>${{fmt(g.average)}}</span></li>`).join('');
  document.getElementById('variable-list').innerHTML = data.most_variable_gyms.map(g =>
    `<li><span>${{g.name}}</span><span>${{fmt(g.stdev)}}</span></li>`).join('');

  const tbody = document.querySelector('#gym-table tbody');
  tbody.innerHTML = data.per_gym.map(g => `<tr>
    <td>${{g.name}}</td><td>${{g.count}}</td><td>${{fmt(g.average)}}</td><td>${{fmt(g.peak)}}</td>
    <td>${{fmt(g.min)}}</td><td>${{fmt(g.stdev)}}</td>
    <td>${{hourLabel(g.busiest_hour)}}</td><td>${{hourLabel(g.quietest_hour)}}</td>
  </tr>`).join('');

  document.getElementById('footer').textContent = 'Generated ' + data.generated_at;
}}

let selectedGym = null;

function predictedCrowdNow(gymName) {{
  const matrix = data.per_gym_dow_hour[gymName];
  if (!matrix) return null;
  const nowSgt = new Date(new Date().toLocaleString('en-US', {{ timeZone: 'Asia/Singapore' }}));
  const dayNames = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  const dayName = dayNames[nowSgt.getDay()];
  const hour = nowSgt.getHours();
  const val = matrix[dayName] ? matrix[dayName][String(hour)] : undefined;
  return {{ dayName, hour, value: val === undefined ? null : val }};
}}

function renderGymDetail(gymName) {{
  selectedGym = gymName;
  document.querySelectorAll('.gym-pill').forEach(p => p.classList.toggle('active', p.dataset.gym === gymName));

  const g = data.per_gym.find(x => x.name === gymName);
  const dayPattern = data.per_gym_day_pattern[gymName] || [];
  const dowPattern = data.per_gym_dow_pattern[gymName] || [];
  const pred = predictedCrowdNow(gymName);

  const container = document.getElementById('gym-detail');
  container.innerHTML = `
    <div class="predict-card">
      <div class="label">Predicted crowd right now</div>
      <div class="value">${{pred && pred.value !== null ? fmt(pred.value) + '%' : 'n/a (no historical data for this day/hour)'}}</div>
      <div class="note">${{pred ? `Based on historical average for ${{pred.dayName}} ${{String(pred.hour).padStart(2,'0')}}:00 SGT` : ''}}</div>
    </div>
    <div class="grid">
      <div class="card"><div class="label">Average</div><div class="value">${{fmt(g?.average)}}</div></div>
      <div class="card"><div class="label">Peak</div><div class="value">${{fmt(g?.peak)}}</div></div>
      <div class="card"><div class="label">Min</div><div class="value">${{fmt(g?.min)}}</div></div>
      <div class="card"><div class="label">Std dev</div><div class="value">${{fmt(g?.stdev)}}</div></div>
    </div>
    <section>
      <h2>${{gymName}} — day trend, 7am-9:45pm (SGT)</h2>
      <div class="chart-wrap"><canvas id="gymDayPatternChart" height="90"></canvas></div>
    </section>
    <section>
      <h2>${{gymName}} — day-of-week pattern</h2>
      <div class="chart-wrap"><canvas id="gymDowChart" height="180"></canvas></div>
    </section>
  `;

  destroyChart('gymDayPatternChart');
  charts.gymDayPatternChart = new Chart(document.getElementById('gymDayPatternChart'), {{
    type: 'line',
    data: {{
      labels: dayPattern.map(s => s.label),
      datasets: [{{ label: 'Avg crowd %', data: dayPattern.map(s => s.average),
                   borderColor: '#5b8def', backgroundColor: 'rgba(91,141,239,0.15)', fill: true, tension: 0.3, pointRadius: 0 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  destroyChart('gymDowChart');
  charts.gymDowChart = new Chart(document.getElementById('gymDowChart'), {{
    type: 'bar',
    data: {{
      labels: dowPattern.map(d => d.day.slice(0,3)),
      datasets: [{{ label: 'Avg crowd %', data: dowPattern.map(d => d.average), backgroundColor: '#5bd68a' }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});
}}

function renderGymTabs() {{
  const tabsEl = document.getElementById('gym-tabs');
  const names = data.per_gym.map(g => g.name);
  tabsEl.innerHTML = names.map(n => `<button class="gym-pill" data-gym="${{n}}">${{n}}</button>`).join('');
  tabsEl.querySelectorAll('.gym-pill').forEach(btn => {{
    btn.addEventListener('click', () => renderGymDetail(btn.dataset.gym));
  }});
  if (names.length) renderGymDetail(names[0]);
}}

function renderAll() {{
  renderOverview();
  renderGymTabs();
}}

document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
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
