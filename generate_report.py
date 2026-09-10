#!/usr/bin/env python3
"""Generate a summary report (and dashboard website) from data/crowd_log.csv.

Reads timestamp,gym_name,crowd_value rows and computes: per-gym average/
peak/min/variability, busiest/quietest hour per gym, an hour-of-day profile
across all gyms, weekday vs weekend comparison, busiest/quietest/most
variable gym rankings, and a day-by-day trend with direction.

crowd_value may be either a percentage ("42%") or a level word (e.g. "Not
Crowded", "Moderately Crowded", "Crowded", "Low", "Moderate", "High") --
both are normalized to a 0-100 scale where possible so they can be averaged.

Outputs:
    reports/report.md          -- markdown summary
    reports/report.html        -- plain HTML copy (--html)
    reports/report_data.json   -- the computed data, for reuse/debugging
    docs/index.html            -- dashboard website with charts (--website)

Usage:
    python generate_report.py [--csv data/crowd_log.csv] [--out reports/report.md] [--html] [--website]
"""
import argparse
import csv
import json
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

HOUR_NAMES = [f"{h:02d}:00" for h in range(24)]


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


def build_report_data(rows: list[dict]) -> dict:
    numeric_rows = [r for r in rows if r["crowd_value"] is not None]

    data: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_readings": len(rows),
        "numeric_readings": len(numeric_rows),
    }

    if not rows:
        data["has_data"] = False
        return data
    data["has_data"] = True

    span_start = min(r["timestamp"] for r in rows)
    span_end = max(r["timestamp"] for r in rows)
    data["span_start"] = span_start.isoformat()
    data["span_end"] = span_end.isoformat()

    # ---- per-gym stats ----
    by_gym = defaultdict(list)
    for r in rows:
        by_gym[r["gym_name"]].append(r)

    per_gym = []
    for gym, entries in sorted(by_gym.items()):
        nums = [e for e in entries if e["crowd_value"] is not None]
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
            by_hour[e["timestamp"].hour].append(e["crowd_value"])
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
                "peak_time": peak_entry["timestamp"].isoformat(),
                "min": min_entry["crowd_value"],
                "min_time": min_entry["timestamp"].isoformat(),
                "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
                "busiest_hour": busiest_hour[0] if busiest_hour else None,
                "busiest_hour_avg": busiest_hour[1] if busiest_hour else None,
                "quietest_hour": quietest_hour[0] if quietest_hour else None,
                "quietest_hour_avg": quietest_hour[1] if quietest_hour else None,
            }
        )
    data["per_gym"] = per_gym
    data["gym_count"] = len(per_gym)

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

    # ---- hour-of-day profile (all 24 hours, all gyms combined) ----
    by_hour_all = defaultdict(list)
    for r in numeric_rows:
        by_hour_all[r["timestamp"].hour].append(r["crowd_value"])
    hour_profile = [
        {"hour": h, "label": HOUR_NAMES[h],
         "average": statistics.mean(by_hour_all[h]) if h in by_hour_all else None}
        for h in range(24)
    ]
    data["hour_profile"] = hour_profile
    known_hours = sorted(
        ((h["hour"], h["average"]) for h in hour_profile if h["average"] is not None),
        key=lambda x: x[1],
    )
    data["quietest_hours"] = [{"hour": h, "average": a} for h, a in known_hours[:3]]
    data["busiest_hours"] = [{"hour": h, "average": a} for h, a in known_hours[-3:][::-1]]

    # ---- weekday vs weekend ----
    weekday_vals = [r["crowd_value"] for r in numeric_rows if r["timestamp"].weekday() < 5]
    weekend_vals = [r["crowd_value"] for r in numeric_rows if r["timestamp"].weekday() >= 5]
    data["weekday_average"] = statistics.mean(weekday_vals) if weekday_vals else None
    data["weekend_average"] = statistics.mean(weekend_vals) if weekend_vals else None

    # ---- daily trend ----
    by_day = defaultdict(list)
    for r in numeric_rows:
        by_day[r["timestamp"].date().isoformat()].append(r["crowd_value"])
    daily_trend = sorted(
        ({"date": day, "average": statistics.mean(vals)} for day, vals in by_day.items()),
        key=lambda d: d["date"],
    )
    data["daily_trend"] = daily_trend

    # ---- weekly trend (ISO year-week buckets) ----
    by_week = defaultdict(list)
    for r in numeric_rows:
        iso_year, iso_week, _ = r["timestamp"].isocalendar()
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
        f"Data range: **{data['span_start']}** to **{data['span_end']}** "
        f"({data['total_readings']} readings across {data['gym_count']} gyms)"
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

    lines.append("## Time-of-day pattern (all gyms combined)")
    lines.append("")
    lines.append("**Quietest hours (UTC):**")
    for h in data["quietest_hours"]:
        lines.append(f"- {h['hour']:02d}:00 — avg {h['average']:.1f}")
    lines.append("")
    lines.append("**Busiest hours (UTC):**")
    for h in data["busiest_hours"]:
        lines.append(f"- {h['hour']:02d}:00 — avg {h['average']:.1f}")
    lines.append("")

    lines.append("## Weekday vs weekend")
    lines.append("")
    wd = data["weekday_average"]
    we = data["weekend_average"]
    lines.append(f"- Weekday average: {f'{wd:.1f}' if wd is not None else 'n/a'}")
    lines.append(f"- Weekend average: {f'{we:.1f}' if we is not None else 'n/a'}")
    lines.append("")

    lines.append("## Trend over the week")
    lines.append("")
    lines.append(f"Overall direction: **{data['trend_direction']}**"
                  + (f" ({data['trend_slope_per_day']:+.2f} crowd pts/day)"
                     if data["trend_slope_per_day"] is not None else ""))
    lines.append("")
    lines.append("| Date | Avg crowd |")
    lines.append("|---|---|")
    for d in data["daily_trend"]:
        lines.append(f"| {d['date']} | {d['average']:.1f} |")
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
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.4/chart.umd.min.js"></script>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; background: #0b0d12; color: #e6e8eb; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .sub {{ color: #9aa2ad; margin-bottom: 28px; }}
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
</style>
</head>
<body>
<h1>ActiveSG Gym Crowd Dashboard</h1>
<p class="sub" id="subtitle">Loading...</p>

<div class="grid" id="stat-cards"></div>

<section>
  <h2>Average crowd per gym</h2>
  <div class="chart-wrap"><canvas id="gymChart" height="110"></canvas></div>
</section>

<div class="two-col">
  <section>
    <h2>Time-of-day pattern</h2>
    <div class="chart-wrap"><canvas id="hourChart" height="180"></canvas></div>
  </section>
  <section>
    <h2>Daily trend</h2>
    <div class="chart-wrap"><canvas id="trendChart" height="180"></canvas></div>
  </section>
</div>

<section>
  <h2>Week-over-week</h2>
  <div class="chart-wrap"><canvas id="weeklyChart" height="90"></canvas></div>
</section>

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

<footer id="footer"></footer>

<script id="report-data" type="application/json">{payload}</script>
<script>
const data = JSON.parse(document.getElementById('report-data').textContent);

function fmt(v, digits = 1) {{ return v === null || v === undefined ? 'n/a' : v.toFixed(digits); }}
function hourLabel(h) {{ return h === null || h === undefined ? 'n/a' : String(h).padStart(2, '0') + ':00'; }}

if (!data.has_data) {{
  document.getElementById('subtitle').textContent = 'No data collected yet.';
}} else {{
  document.getElementById('subtitle').textContent =
    `${{data.span_start}} to ${{data.span_end}} — ${{data.total_readings}} readings across ${{data.gym_count}} gyms`;

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
  new Chart(document.getElementById('gymChart'), {{
    type: 'bar',
    data: {{
      labels: gyms.map(g => g.name),
      datasets: [{{ label: 'Average crowd %', data: gyms.map(g => g.average), backgroundColor: '#5b8def' }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ x: {{ beginAtZero: true, max: 100 }} }}
    }}
  }});

  const hours = data.hour_profile;
  new Chart(document.getElementById('hourChart'), {{
    type: 'bar',
    data: {{
      labels: hours.map(h => h.label),
      datasets: [{{ label: 'Avg crowd %', data: hours.map(h => h.average), backgroundColor: '#f2a65a' }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  new Chart(document.getElementById('trendChart'), {{
    type: 'line',
    data: {{
      labels: data.daily_trend.map(d => d.date),
      datasets: [{{ label: 'Avg crowd %', data: data.daily_trend.map(d => d.average),
                   borderColor: '#5bd68a', backgroundColor: 'rgba(91,214,138,0.15)', fill: true, tension: 0.3 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true, max: 100 }} }} }}
  }});

  new Chart(document.getElementById('weeklyChart'), {{
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
}}

document.getElementById('footer').textContent = 'Generated ' + data.generated_at + ' UTC';
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
        print(f"Wrote {website_path}")


if __name__ == "__main__":
    main()
