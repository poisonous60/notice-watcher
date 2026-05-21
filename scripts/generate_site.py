#!/usr/bin/env python3
"""Generate the public status site as a single static HTML file."""

from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")

PLATFORM_PREFIXES = (
    "discourse_",
    "arca-live_",
    "arca_",
    "naver-cafe_",
    "reddit_",
    "xenforo_",
    "dcinside_",
    "tistory_",
    "google-news_",
    "naver-blog_",
    "naver-game-lounge_",
    "daum-cafe_",
    "nexon-forum_",
)

POLL_SUFFIXES = {
    ".FAILED.json": "failed",
    ".REJECTED.json": "rejected",
    ".BUG.json": "bug",
}

RC_LABELS = {
    0: "registered",
    1: "generation failed",
    2: "policy rejected",
    3: "gate rejected",
    4: "URL unavailable",
    5: "capability blocked",
}


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def hostname_from_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parsed = urlparse(value.strip())
    host = parsed.hostname
    if host:
        return host.lower()
    if "/" not in value and "." in value:
        return value.strip().split(":", 1)[0].lower()
    return ""


def platform_from_slug(slug: str) -> str:
    for prefix in PLATFORM_PREFIXES:
        if slug.startswith(prefix):
            return prefix[:-1]
    if slug.startswith("host_"):
        return "generic host"
    return "other"


def marker_kind(path: Path) -> str:
    name = path.name
    for suffix, label in POLL_SUFFIXES.items():
        if name.endswith(suffix):
            return label
    if name.endswith(".json"):
        return "polling"
    return "other"


def rc_label(value: object) -> str:
    if value is None:
        return "unknown"
    try:
        rc = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if rc < 0:
        return "system bug"
    return RC_LABELS.get(rc, f"rc {rc}")


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_configs() -> dict:
    config_dir = ROOT / "configs"
    configs = []
    platforms = Counter()
    strategies = Counter()
    hosts = Counter()

    for path in sorted(config_dir.glob("*.json")):
        data = load_json(path)
        slug = path.stem
        platform = str(data.get("_recognized_platform") or platform_from_slug(slug))
        strategy = str(data.get("strategy") or "unknown")
        site = str(data.get("site") or hostname_from_url(data.get("_source_url")) or "unknown")
        host = hostname_from_url(data.get("_source_url")) or hostname_from_url(site) or site

        configs.append({"site": site, "platform": platform, "strategy": strategy, "host": host})
        platforms[platform] += 1
        strategies[strategy] += 1
        if host and host != "unknown":
            hosts[host] += 1

    return {
        "items": configs,
        "platforms": platforms,
        "strategies": strategies,
        "hosts": hosts,
    }


def read_poll_state() -> dict:
    state_dir = ROOT / "output" / "poll_state"
    markers = Counter()

    if not state_dir.exists():
        return {"markers": markers, "total": 0}

    total = 0
    for path in state_dir.glob("*.json"):
        if not path.is_file():
            continue
        total += 1
        markers[marker_kind(path)] += 1

    return {"markers": markers, "total": total}


def read_jobs(limit: int = 20) -> dict:
    db_path = ROOT / "output" / "bot.sqlite3"
    status = Counter()
    recent = []

    if not db_path.exists():
        return {"status": status, "recent": recent, "available": False}

    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        with con:
            for row in con.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
                status[str(row["status"] or "unknown")] += int(row["n"] or 0)
            rows = con.execute(
                """
                SELECT url, status, result_rc, finished_at
                FROM jobs
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return {"status": status, "recent": recent, "available": False}
    finally:
        try:
            con.close()
        except UnboundLocalError:
            pass

    for row in rows:
        recent.append(
            {
                "host": hostname_from_url(row["url"]) or "unknown host",
                "status": str(row["status"] or "unknown"),
                "result": rc_label(row["result_rc"]),
                "finished_at": str(row["finished_at"] or ""),
            }
        )

    return {"status": status, "recent": recent, "available": True}


def top_items(counter: Counter, limit: int = 8) -> list[tuple[str, int]]:
    return [(str(k), int(v)) for k, v in counter.most_common(limit)]


def pct(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(part * 100 / total)


def svg_bar_chart(items: list[tuple[str, int]], title: str) -> str:
    width = 760
    row_h = 34
    top = 34
    height = max(150, top + len(items) * row_h + 22)
    max_value = max([v for _, v in items], default=1)
    rows = []
    for i, (label, value) in enumerate(items):
        y = top + i * row_h
        bar_w = int((width - 250) * value / max_value) if max_value else 0
        rows.append(
            f'<text x="0" y="{y + 18}" class="svg-label">{esc(label)}</text>'
            f'<rect x="190" y="{y}" width="{bar_w}" height="20" rx="2" class="bar"></rect>'
            f'<text x="{205 + bar_w}" y="{y + 16}" class="svg-value">{value}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        f'<text x="0" y="18" class="svg-title">{esc(title)}</text>'
        + "".join(rows)
        + "</svg>"
    )


def svg_donut(items: list[tuple[str, int]], title: str) -> str:
    total = sum(v for _, v in items)
    width = 760
    height = 230
    colors = ["#52616b", "#8a6f4d", "#3d737f", "#9b6b6b", "#6f7f52", "#6d647c"]
    if total <= 0:
        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
            f'<text x="0" y="24" class="svg-title">{esc(title)}</text>'
            '<text x="0" y="76" class="svg-label">No data yet</text></svg>'
        )

    x = 0
    parts = []
    legend = []
    for i, (label, value) in enumerate(items):
        w = int((width - 230) * value / total)
        color = colors[i % len(colors)]
        parts.append(f'<rect x="{x}" y="50" width="{w}" height="32" fill="{color}"></rect>')
        legend.append(
            f'<rect x="0" y="{112 + i * 24}" width="12" height="12" fill="{color}"></rect>'
            f'<text x="22" y="{123 + i * 24}" class="svg-label">{esc(label)} · {value} · {pct(value, total)}%</text>'
        )
        x += w
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">'
        f'<text x="0" y="24" class="svg-title">{esc(title)}</text>'
        + "".join(parts)
        + "".join(legend)
        + "</svg>"
    )


def metric(label: str, value: object, note: str = "") -> str:
    note_html = f"<span>{esc(note)}</span>" if note else ""
    return f'<div class="metric"><strong>{esc(value)}</strong><em>{esc(label)}</em>{note_html}</div>'


def render_html(configs: dict, poll: dict, jobs: dict, generated_at: datetime) -> str:
    config_count = len(configs["items"])
    polling_count = poll["markers"].get("polling", 0)
    failed_count = poll["markers"].get("failed", 0)
    rejected_count = poll["markers"].get("rejected", 0)
    bug_count = poll["markers"].get("bug", 0)
    hand_count = configs["strategies"].get("handwritten", 0)
    other_strategy_count = max(config_count - hand_count, 0)

    platform_chart = svg_bar_chart(top_items(configs["platforms"], 8), "Figure 1. Registered sources by platform")
    marker_chart = svg_donut(
        [
            ("polling", polling_count),
            ("failed", failed_count),
            ("rejected", rejected_count),
            ("bug", bug_count),
        ],
        "Figure 2. Runtime marker mix",
    )
    strategy_chart = svg_donut(
        [("handwritten strategy", hand_count), ("other strategy", other_strategy_count)],
        "Figure 3. Configuration strategy mix",
    )

    recent_rows = []
    for item in jobs["recent"]:
        recent_rows.append(
            "<tr>"
            f"<td>{esc(item['finished_at'])}</td>"
            f"<td>{esc(item['host'])}</td>"
            f"<td>{esc(item['status'])}</td>"
            f"<td>{esc(item['result'])}</td>"
            "</tr>"
        )
    if not recent_rows:
        recent_rows.append('<tr><td colspan="4">No completed registration jobs on this machine yet.</td></tr>')

    top_hosts = "".join(
        f"<li><span>{esc(host)}</span><b>{count}</b></li>" for host, count in top_items(configs["hosts"], 10)
    )
    if not top_hosts:
        top_hosts = "<li><span>No public host summary yet</span><b>0</b></li>"

    job_status = ", ".join(f"{name}: {count}" for name, count in top_items(jobs["status"], 6))
    if not job_status:
        job_status = "no queued jobs in local database" if jobs["available"] else "job database unavailable"

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Notice Watcher Public Status Site</title>
  <style>
    :root {{
      --paper: #f7f4ed;
      --ink: #1f2528;
      --muted: #667078;
      --line: #d8d0c2;
      --accent: #3d737f;
      --accent-2: #8a6f4d;
      --panel: #fffdf8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 56px 20px 72px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      margin-bottom: 30px;
      padding-bottom: 26px;
    }}
    .kicker {{
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1, h2, h3 {{
      font-family: Georgia, "Times New Roman", serif;
      font-weight: 600;
      line-height: 1.15;
    }}
    h1 {{
      font-size: 2.8rem;
      margin: 8px 0 12px;
      letter-spacing: 0;
    }}
    h2 {{
      font-size: 1.55rem;
      margin: 38px 0 14px;
      border-top: 1px solid var(--line);
      padding-top: 22px;
    }}
    p {{ margin: 0 0 14px; }}
    .lead {{
      max-width: 720px;
      color: #3e474d;
      font-size: 1.05rem;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.92rem;
      margin-top: 18px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 28px 0 14px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px 14px 13px;
      min-height: 112px;
    }}
    .metric strong {{
      display: block;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 2rem;
      line-height: 1;
    }}
    .metric em {{
      display: block;
      color: var(--ink);
      font-style: normal;
      font-weight: 700;
      margin-top: 9px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 0.84rem;
      margin-top: 4px;
    }}
    figure {{
      margin: 24px 0;
      padding: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    figcaption {{
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 10px;
    }}
    svg {{
      display: block;
      height: auto;
      max-width: 100%;
      overflow: visible;
    }}
    .svg-title {{
      fill: var(--ink);
      font: 600 18px Georgia, "Times New Roman", serif;
    }}
    .svg-label, .svg-value {{
      fill: var(--muted);
      font: 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .svg-value {{ fill: var(--ink); font-weight: 700; }}
    .bar {{ fill: var(--accent); }}
    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 26px;
    }}
    ol, ul {{ padding-left: 22px; }}
    .host-list {{
      list-style: none;
      padding: 0;
      margin: 8px 0 0;
      border-top: 1px solid var(--line);
    }}
    .host-list li {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      border-bottom: 1px solid var(--line);
      padding: 9px 0;
    }}
    .host-list span {{
      overflow-wrap: anywhere;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
    }}
    footer {{
      color: var(--muted);
      border-top: 1px solid var(--line);
      margin-top: 42px;
      padding-top: 18px;
      font-size: 0.9rem;
    }}
    @media (max-width: 720px) {{
      main {{ padding-top: 34px; }}
      h1 {{ font-size: 2.1rem; }}
      .metrics, .split {{ grid-template-columns: 1fr 1fr; }}
      th:nth-child(1), td:nth-child(1) {{ display: none; }}
    }}
    @media (max-width: 480px) {{
      .metrics, .split {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="kicker">Public status site</div>
    <h1>Notice Watcher</h1>
    <p class="lead">A static, anonymized summary of the notice-watcher project running on N100. It shows aggregate progress, public source domains, and recent registration outcomes without exposing Discord identifiers, raw addresses, extraction details, opaque internal names, or configuration internals.</p>
    <p class="meta">Generated {esc(generated_at.strftime("%Y-%m-%d %H:%M:%S %Z"))}</p>
  </header>

  <section aria-labelledby="overview">
    <h2 id="overview">Overview</h2>
    <div class="metrics">
      {metric("registered configs", config_count, "tracked source definitions")}
      {metric("polling markers", polling_count, "active runtime states")}
      {metric("needs review", failed_count + bug_count, "failed or bug markers")}
      {metric("total jobs", sum(jobs["status"].values()), job_status)}
    </div>
  </section>

  <section aria-labelledby="figures">
    <h2 id="figures">Figures</h2>
    <figure>
      {platform_chart}
      <figcaption>Figure 1. Platform is derived from recognized platform metadata or from the public filename prefix class, not from hidden extraction data or raw addresses.</figcaption>
    </figure>
    <figure>
      {marker_chart}
      <figcaption>Figure 2. Marker counts summarize active polling, registration failures, permanent rejections, and system bug markers.</figcaption>
    </figure>
    <figure>
      {strategy_chart}
      <figcaption>Figure 3. Strategy counts distinguish adapter-backed handwritten strategy configs from other config strategies.</figcaption>
    </figure>
  </section>

  <section aria-labelledby="sources">
    <h2 id="sources">Public Source Domains</h2>
    <div class="split">
      <div>
        <h3>Most Represented Hosts</h3>
        <ul class="host-list">{top_hosts}</ul>
      </div>
      <div>
        <h3>Safety Boundary</h3>
        <p>This page intentionally reports only aggregate counts, config site names, public hostnames, status labels, and timestamps. It omits private Discord metadata, raw addresses, route details, extraction rules, opaque internal names, request bodies, and config internals.</p>
      </div>
    </div>
  </section>

  <section aria-labelledby="activity">
    <h2 id="activity">Recent Activity</h2>
    <table>
      <thead><tr><th>Finished</th><th>Host</th><th>Status</th><th>Result</th></tr></thead>
      <tbody>{''.join(recent_rows)}</tbody>
    </table>
  </section>

  <footer>
    <p>Generated from local runtime snapshots on N100. The internal development interface remains separate from this public static artifact.</p>
  </footer>
</main>
</body>
</html>
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate output/site/index.html")
    parser.add_argument("--out", default="output/site/index.html", help="output HTML path")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    configs = read_configs()
    poll = read_poll_state()
    jobs = read_jobs()
    generated_at = datetime.now(KST)
    page = render_html(configs, poll, jobs, generated_at)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(
        "[generate_site] wrote "
        f"{out_path} ({len(configs['items'])} configs, {poll['total']} polling, "
        f"{len(jobs['recent'])} recent jobs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
