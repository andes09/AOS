"""Stage-2 aggregate HTML report renderer.

Reads ``output/aggregate/summary.csv`` and emits a self-contained
``summary.html`` with the same Chart.js layout / palette as the hand-edited
report. Stdlib only — no jinja, no pandas.

Usage::

    .venv/bin/python -m src.report_html \
        --input output/aggregate/summary.csv \
        --output output/aggregate/summary.html
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Display order matches the existing hand-edited report.
ARCHETYPE_ORDER = ["small", "balanced", "meeting_heavy", "large", "struggling"]
STRATEGY_ORDER = ["algorithm", "omada", "random"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        default="output/aggregate/summary.csv",
        help="Path to summary.csv (default: output/aggregate/summary.csv)",
    )
    parser.add_argument(
        "--output",
        default="output/aggregate/summary.html",
        help="Path to write summary.html (default: output/aggregate/summary.html)",
    )
    return parser.parse_args(argv)


def _read_rows(path: Path) -> list[dict]:
    """Return parsed CSV rows with floats coerced. Empty file → []."""
    rows: list[dict] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {
                "archetype": raw["archetype"],
                "strategy": raw["strategy"],
                "runs": int(raw["runs"]),
                "sprints": int(raw["sprints"]),
                "completion": float(raw["mean_completion_rate"]),
                "std": float(raw["std_completion_rate"]),
                "spillover": float(raw["mean_spillover"]),
                "committed": float(raw["mean_committed"]),
                "completed": float(raw["mean_completed"]),
                "plan_ok": float(raw["plan_ok_pct"]),
                "push_ok": float(raw["push_ok_pct"]),
                "retro_ok": float(raw["retro_ok_pct"]),
                "sync_ok": float(raw["sync_ok_pct"]),
            }
            rows.append(row)
    return rows


def _sort_rows(rows: list[dict]) -> list[dict]:
    """Sort by (archetype display order, strategy display order). Falls back
    to alpha for any names we don't know about."""
    arch_idx = {a: i for i, a in enumerate(ARCHETYPE_ORDER)}
    strat_idx = {s: i for i, s in enumerate(STRATEGY_ORDER)}

    def key(r: dict) -> tuple:
        return (
            arch_idx.get(r["archetype"], 999),
            r["archetype"],
            strat_idx.get(r["strategy"], 999),
            r["strategy"],
        )

    return sorted(rows, key=key)


def _archetypes_present(rows: list[dict]) -> list[str]:
    """Archetypes in display order, then any extras alpha-sorted."""
    seen = {r["archetype"] for r in rows}
    ordered = [a for a in ARCHETYPE_ORDER if a in seen]
    extras = sorted(a for a in seen if a not in ARCHETYPE_ORDER)
    return ordered + extras


def _row_for(rows: list[dict], archetype: str, strategy: str) -> dict | None:
    for r in rows:
        if r["archetype"] == archetype and r["strategy"] == strategy:
            return r
    return None


# ---------------------------------------------------------------------------
# KPIs


def _compute_kpis(rows: list[dict]) -> dict:
    """Header KPIs: best strategy by archetypes won, top/worst cell, sync mean."""
    archetypes = _archetypes_present(rows)

    # Best strategy: per archetype, which strategy has the highest completion?
    winners: list[str] = []
    for arch in archetypes:
        cells = [r for r in rows if r["archetype"] == arch]
        if not cells:
            continue
        top = max(cells, key=lambda r: r["completion"])
        winners.append(top["strategy"])

    win_counts = Counter(winners)
    if win_counts:
        best_strategy, best_wins = win_counts.most_common(1)[0]
    else:
        best_strategy, best_wins = "—", 0

    # Top / worst cell.
    top_cell = max(rows, key=lambda r: r["completion"])
    worst_cell = min(rows, key=lambda r: r["completion"])

    # Sync health: mean of sync_ok_pct across all cells.
    sync_mean = sum(r["sync_ok"] for r in rows) / len(rows)

    return {
        "best_strategy": best_strategy,
        "best_wins": best_wins,
        "total_archetypes": len(archetypes),
        "top_pct": top_cell["completion"] * 100.0,
        "top_label": f"{top_cell['archetype']} · {top_cell['strategy']}",
        "worst_pct": worst_cell["completion"] * 100.0,
        "worst_label": f"{worst_cell['archetype']} · {worst_cell['strategy']}",
        "sync_mean": sync_mean,
    }


# ---------------------------------------------------------------------------
# Insights


def _compute_insights(rows: list[dict], kpis: dict) -> list[str]:
    """Auto-generated bullets — 5–7 of them. Tight voice, data-driven."""
    insights: list[str] = []
    archetypes = _archetypes_present(rows)

    # 1. Best-strategy headline.
    best = kpis["best_strategy"]
    wins = kpis["best_wins"]
    total = kpis["total_archetypes"]
    if best != "—" and wins > 0:
        insights.append(
            f"<strong>{best.capitalize()} wins {wins} of {total} archetypes by completion rate.</strong> "
            f"Strongest signal in the matrix — every other comparison should be framed against this baseline."
        )

    # 2. Largest gap between best and worst strategy in any archetype.
    biggest_gap = None
    for arch in archetypes:
        cells = [r for r in rows if r["archetype"] == arch]
        if len(cells) < 2:
            continue
        hi = max(cells, key=lambda r: r["completion"])
        lo = min(cells, key=lambda r: r["completion"])
        gap = hi["completion"] - lo["completion"]
        if biggest_gap is None or gap > biggest_gap["gap"]:
            biggest_gap = {"arch": arch, "gap": gap, "hi": hi, "lo": lo}
    if biggest_gap and biggest_gap["gap"] >= 0.05:
        bg = biggest_gap
        insights.append(
            f"<strong>{bg['arch']} shows the widest strategy gap "
            f"({bg['gap'] * 100:.0f} pts).</strong> "
            f"{bg['hi']['strategy']} hits {bg['hi']['completion'] * 100:.0f}% vs "
            f"{bg['lo']['strategy']} at {bg['lo']['completion'] * 100:.0f}% — "
            f"this is where the planner choice actually moves the needle."
        )

    # 3. High-variance cells.
    high_var = [r for r in rows if r["std"] > 0.15]
    if high_var:
        worst_var = max(high_var, key=lambda r: r["std"])
        insights.append(
            f"<strong>High variance on {worst_var['archetype']} · {worst_var['strategy']} "
            f"(±{worst_var['std'] * 100:.0f} pts).</strong> "
            f"{len(high_var)} cell(s) above the 0.15 σ threshold — these need more runs "
            f"before treating the means as load-bearing."
        )

    # 4. Archetype dominates over strategy?
    arch_range = []
    for arch in archetypes:
        comps = [r["completion"] for r in rows if r["archetype"] == arch]
        if comps:
            arch_range.append(max(comps) - min(comps))
    strat_range = []
    for strat in STRATEGY_ORDER:
        comps = [r["completion"] for r in rows if r["strategy"] == strat]
        if comps:
            strat_range.append(max(comps) - min(comps))
    if arch_range and strat_range:
        # Compare mean within-archetype strategy spread to overall archetype spread.
        comps_all = [r["completion"] for r in rows]
        archetype_spread = max(comps_all) - min(comps_all)
        avg_strategy_spread = sum(arch_range) / len(arch_range)
        if archetype_spread > 2 * avg_strategy_spread and avg_strategy_spread > 0:
            ratio = archetype_spread / avg_strategy_spread
            insights.append(
                f"<strong>Archetype variance dominates strategy variance "
                f"({ratio:.1f}× larger spread).</strong> "
                f"Team composition explains more than planner choice — invest in "
                f"capacity modelling before tuning the heuristic."
            )

    # 5. push_ok / retro_ok status across the matrix.
    push_means_by_strat = {
        s: [r["push_ok"] for r in rows if r["strategy"] == s] for s in STRATEGY_ORDER
    }
    retro_means_by_strat = {
        s: [r["retro_ok"] for r in rows if r["strategy"] == s] for s in STRATEGY_ORDER
    }
    push_overall = [r["push_ok"] for r in rows]
    retro_overall = [r["retro_ok"] for r in rows]
    push_avg = sum(push_overall) / len(push_overall) if push_overall else 0.0
    retro_avg = sum(retro_overall) / len(retro_overall) if retro_overall else 0.0

    omada_push = push_means_by_strat.get("omada") or []
    omada_retro = retro_means_by_strat.get("omada") or []
    omada_push_avg = sum(omada_push) / len(omada_push) if omada_push else 0.0
    omada_retro_avg = sum(omada_retro) / len(omada_retro) if omada_retro else 0.0

    if push_avg == 0.0 and retro_avg == 0.0:
        insights.append(
            "<strong>push_ok_pct and retro_ok_pct are 0% across every cell.</strong> "
            "Jira push + retro sync aren't firing in this run — either disabled or broken end-to-end. "
            "Check the dispatcher logs before reading anything else."
        )
    elif omada_push_avg > 0 or omada_retro_avg > 0:
        insights.append(
            f"<strong>Omada push/retro now reporting "
            f"(push {omada_push_avg:.0f}%, retro {omada_retro_avg:.0f}%).</strong> "
            f"The recent push-to-jira + sprint-close-sync fixes are landing — but other "
            f"strategies still show 0%, so the per-team wiring isn't fully symmetric yet."
        )
    else:
        insights.append(
            f"<strong>Integration health is mixed.</strong> "
            f"Mean push_ok_pct {push_avg:.0f}%, retro_ok_pct {retro_avg:.0f}% across the matrix. "
            f"Look at per-strategy rows in the table below to localize."
        )

    # 6. Sync health summary.
    if kpis["sync_mean"] >= 95.0:
        insights.append(
            f"<strong>Sync health is solid ({kpis['sync_mean']:.0f}%).</strong> "
            f"Whatever's off with push/retro, the read path is intact — "
            f"diagnose write failures, not state drift."
        )
    elif kpis["sync_mean"] < 75.0:
        insights.append(
            f"<strong>Sync health degraded to {kpis['sync_mean']:.0f}%.</strong> "
            f"The Jira read path is dropping state — fix this first; "
            f"every other metric becomes noisy when sync is unreliable."
        )

    # Trim to 7 max.
    return insights[:7]


# ---------------------------------------------------------------------------
# Rendering


def _format_data_array(rows: list[dict]) -> str:
    """Produce the JS data array embedded in the page."""
    lines = []
    for r in rows:
        lines.append(
            "      { "
            f"archetype: {r['archetype']!r}, "
            f"strategy: {r['strategy']!r}, "
            f"completion: {r['completion']:.4f}, "
            f"std: {r['std']:.4f}, "
            f"spillover: {r['spillover']:.4f}, "
            f"committed: {r['committed']:.4f}, "
            f"completed: {r['completed']:.4f}, "
            f"plan_ok: {r['plan_ok']:.1f}, "
            f"push_ok: {r['push_ok']:.1f}, "
            f"retro_ok: {r['retro_ok']:.1f}, "
            f"sync_ok: {r['sync_ok']:.1f} "
            "},"
        )
    return "\n".join(lines)


def _format_archetypes_array(archetypes: list[str]) -> str:
    return ", ".join(repr(a) for a in archetypes)


def _format_insights_list(insights: list[str]) -> str:
    return "\n".join(f"        <li>{html}</li>" for html in insights)


def _subtitle(rows: list[dict]) -> str:
    archetypes = _archetypes_present(rows)
    strategies = sorted({r["strategy"] for r in rows})
    runs = max((r["runs"] for r in rows), default=0)
    sprints_per_cell = max((r["sprints"] // max(r["runs"], 1) for r in rows), default=0)
    return (
        f"Sprint completion across {len(archetypes)} team archetypes × "
        f"{len(strategies)} planning strategies · "
        f"{runs} run × {sprints_per_cell} sprints each"
    )


def render(rows: list[dict]) -> str:
    rows = _sort_rows(rows)
    archetypes = _archetypes_present(rows)
    kpis = _compute_kpis(rows)
    insights = _compute_insights(rows, kpis)
    generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    data_js = _format_data_array(rows)
    archetypes_js = _format_archetypes_array(archetypes)
    insights_html = _format_insights_list(insights)
    subtitle = _subtitle(rows)

    return _TEMPLATE.format(
        subtitle=subtitle,
        best_strategy=kpis["best_strategy"].capitalize(),
        best_wins=kpis["best_wins"],
        total_archetypes=kpis["total_archetypes"],
        top_pct=f"{kpis['top_pct']:.0f}%",
        top_label=kpis["top_label"],
        worst_pct=f"{kpis['worst_pct']:.0f}%",
        worst_label=kpis["worst_label"],
        sync_mean=f"{kpis['sync_mean']:.0f}%",
        insights_html=insights_html,
        data_js=data_js,
        archetypes_js=archetypes_js,
        generated_at=generated_at,
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Stage 2 — Aggregate Summary</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #fafafa;
      --card: #ffffff;
      --text: #1a1a1a;
      --muted: #6b7280;
      --border: #e5e7eb;
      --accent-algo: #2563eb;
      --accent-omada: #f97316;
      --accent-random: #10b981;
      --good: #16a34a;
      --bad: #dc2626;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 32px 24px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1080px; margin: 0 auto; }}
    h1 {{ font-size: 28px; font-weight: 600; margin: 0 0 4px 0; }}
    h2 {{ font-size: 18px; font-weight: 600; margin: 32px 0 12px 0; color: var(--text); }}
    .subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 24px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 20px;
    }}
    .kpi {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .kpi-label {{
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
    }}
    .kpi-value {{ font-size: 22px; font-weight: 600; }}
    .kpi-sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
    .chart-wrap {{ position: relative; height: 340px; }}
    .chart-wrap.tall {{ height: 380px; }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }}
    th {{
      font-weight: 600;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    tr:last-child td {{ border-bottom: none; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 500;
    }}
    .pill-algo {{ background: #dbeafe; color: #1e40af; }}
    .pill-omada {{ background: #ffedd5; color: #c2410c; }}
    .pill-random {{ background: #d1fae5; color: #047857; }}
    .insights {{ list-style: none; padding: 0; margin: 0; }}
    .insights li {{
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
      font-size: 14px;
    }}
    .insights li:last-child {{ border-bottom: none; }}
    .insights strong {{ color: var(--text); }}
    .footer {{
      font-size: 12px;
      color: var(--muted);
      text-align: center;
      padding: 16px 0 4px;
      border-top: 1px solid var(--border);
      margin-top: 24px;
    }}
    @media (max-width: 720px) {{
      .kpis {{ grid-template-columns: repeat(2, 1fr); }}
      .grid-2 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Stage 2 — Aggregate Summary</h1>
    <p class="subtitle">{subtitle}</p>

    <div class="kpis">
      <div class="kpi">
        <div class="kpi-label">Best strategy</div>
        <div class="kpi-value">{best_strategy}</div>
        <div class="kpi-sub">Wins {best_wins} of {total_archetypes} archetypes</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Top completion</div>
        <div class="kpi-value">{top_pct}</div>
        <div class="kpi-sub">{top_label}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Worst completion</div>
        <div class="kpi-value">{worst_pct}</div>
        <div class="kpi-sub">{worst_label}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Sync health</div>
        <div class="kpi-value">{sync_mean}</div>
        <div class="kpi-sub">Mean across cells</div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0;">Completion rate by archetype &amp; strategy</h2>
      <div class="chart-wrap"><canvas id="completionChart"></canvas></div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2 style="margin-top:0;">Spillover (issues left unfinished)</h2>
        <div class="chart-wrap"><canvas id="spilloverChart"></canvas></div>
      </div>
      <div class="card">
        <h2 style="margin-top:0;">Committed vs Completed</h2>
        <div class="chart-wrap"><canvas id="committedChart"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0;">Integration health — plan_ok_pct</h2>
      <p class="subtitle" style="margin-bottom:16px;">Percent of sprints where SprintBrain plan generation succeeded.</p>
      <div class="chart-wrap"><canvas id="planOkChart"></canvas></div>
    </div>

    <div class="card">
      <h2 style="margin-top:0;">Key insights</h2>
      <ul class="insights">
{insights_html}
      </ul>
    </div>

    <div class="card">
      <h2 style="margin-top:0;">Full data</h2>
      <table>
        <thead>
          <tr>
            <th>Archetype</th>
            <th>Strategy</th>
            <th>Completion</th>
            <th>Spillover</th>
            <th>Committed</th>
            <th>Completed</th>
            <th>Plan OK %</th>
            <th>Push OK %</th>
            <th>Retro OK %</th>
            <th>Sync OK %</th>
          </tr>
        </thead>
        <tbody id="dataTable"></tbody>
      </table>
    </div>

    <div class="footer">
      Generated from <code>summary.csv</code> · {generated_at}
    </div>
  </div>

  <script>
    const data = [
{data_js}
    ];

    const archetypes = [{archetypes_js}];
    const strategies = ['algorithm', 'omada', 'random'];
    const colors = {{
      algorithm: '#2563eb',
      omada: '#f97316',
      random: '#10b981',
    }};

    function valuesFor(metric, strategy) {{
      return archetypes.map(a => {{
        const row = data.find(d => d.archetype === a && d.strategy === strategy);
        return row ? row[metric] : 0;
      }});
    }}

    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.color = '#374151';

    // Completion rate chart
    new Chart(document.getElementById('completionChart'), {{
      type: 'bar',
      data: {{
        labels: archetypes,
        datasets: strategies.map(s => ({{
          label: s,
          data: valuesFor('completion', s).map(v => +(v * 100).toFixed(1)),
          backgroundColor: colors[s],
          borderRadius: 4,
        }})),
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'bottom' }},
          tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y}}%` }} }},
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            max: 100,
            ticks: {{ callback: v => v + '%' }},
            grid: {{ color: '#f3f4f6' }},
          }},
          x: {{ grid: {{ display: false }} }},
        }},
      }},
    }});

    // Spillover chart
    new Chart(document.getElementById('spilloverChart'), {{
      type: 'bar',
      data: {{
        labels: archetypes,
        datasets: strategies.map(s => ({{
          label: s,
          data: valuesFor('spillover', s).map(v => +v.toFixed(1)),
          backgroundColor: colors[s],
          borderRadius: 4,
        }})),
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'bottom' }},
        }},
        scales: {{
          y: {{ beginAtZero: true, grid: {{ color: '#f3f4f6' }} }},
          x: {{ grid: {{ display: false }} }},
        }},
      }},
    }});

    // Committed vs Completed (algorithm strategy)
    const committedData = archetypes.map(a => {{
      const row = data.find(d => d.archetype === a && d.strategy === 'algorithm');
      return row ? row.committed : 0;
    }});
    const completedData = archetypes.map(a => {{
      const row = data.find(d => d.archetype === a && d.strategy === 'algorithm');
      return row ? row.completed : 0;
    }});

    new Chart(document.getElementById('committedChart'), {{
      type: 'bar',
      data: {{
        labels: archetypes,
        datasets: [
          {{ label: 'Committed', data: committedData.map(v => +v.toFixed(1)), backgroundColor: '#cbd5e1', borderRadius: 4 }},
          {{ label: 'Completed', data: completedData.map(v => +v.toFixed(1)), backgroundColor: '#2563eb', borderRadius: 4 }},
        ],
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'bottom' }},
          title: {{ display: true, text: 'Algorithm strategy', color: '#6b7280', font: {{ size: 11, weight: 'normal' }} }},
        }},
        scales: {{
          y: {{ beginAtZero: true, grid: {{ color: '#f3f4f6' }} }},
          x: {{ grid: {{ display: false }} }},
        }},
      }},
    }});

    // plan_ok_pct chart
    new Chart(document.getElementById('planOkChart'), {{
      type: 'bar',
      data: {{
        labels: archetypes,
        datasets: strategies.map(s => ({{
          label: s,
          data: valuesFor('plan_ok', s).map(v => +v.toFixed(1)),
          backgroundColor: colors[s],
          borderRadius: 4,
        }})),
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ position: 'bottom' }},
          tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}}: ${{ctx.parsed.y}}%` }} }},
        }},
        scales: {{
          y: {{ beginAtZero: true, max: 100, ticks: {{ callback: v => v + '%' }}, grid: {{ color: '#f3f4f6' }} }},
          x: {{ grid: {{ display: false }} }},
        }},
      }},
    }});

    // Fill data table
    const tbody = document.getElementById('dataTable');
    const pillClass = s => s === 'algorithm' ? 'pill-algo' : (s === 'omada' ? 'pill-omada' : 'pill-random');
    const pillFor = s => `<span class="pill ${{pillClass(s)}}">${{s}}</span>`;
    data.forEach(row => {{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${{row.archetype}}</td>
        <td>${{pillFor(row.strategy)}}</td>
        <td>${{(row.completion * 100).toFixed(1)}}% <span style="color:#9ca3af;">± ${{(row.std * 100).toFixed(1)}}</span></td>
        <td>${{row.spillover.toFixed(1)}}</td>
        <td>${{row.committed.toFixed(1)}}</td>
        <td>${{row.completed.toFixed(1)}}</td>
        <td>${{row.plan_ok.toFixed(1)}}%</td>
        <td>${{row.push_ok.toFixed(1)}}%</td>
        <td>${{row.retro_ok.toFixed(1)}}%</td>
        <td>${{row.sync_ok.toFixed(1)}}%</td>
      `;
      tbody.appendChild(tr);
    }});
  </script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(
            f"[report_html] error: input CSV not found at {input_path}",
            file=sys.stderr,
        )
        return 1

    rows = _read_rows(input_path)
    if not rows:
        print(
            f"[report_html] error: {input_path} has no data rows — "
            f"run --aggregate first",
            file=sys.stderr,
        )
        return 1

    html = render(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"[report_html] wrote {output_path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
