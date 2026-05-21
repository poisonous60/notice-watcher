#!/usr/bin/env python3
"""Generate the public status site as a single static HTML file."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
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


# second-level labels that are really part of a multi-part public suffix
# (e.g. .co.kr / .ac.kr / .co.jp) — the registrable label is one further left.
_PUBLIC_SUFFIX_2ND = {"co", "ac", "or", "ne", "go", "com", "net", "org", "edu", "gov"}


def service_from_host(host: str) -> str:
    """Registrable service label from a domain (store.steampowered.com -> steampowered,
    skku.ac.kr -> skku, github.com -> github)."""
    parts = [p for p in str(host).split(".") if p]
    if len(parts) >= 3 and parts[-2] in _PUBLIC_SUFFIX_2ND:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return host or "unknown"


def platform_from_slug(slug: str) -> str:
    for prefix in PLATFORM_PREFIXES:
        if slug.startswith(prefix):
            return prefix[:-1]
    if slug.startswith("host_"):
        return "generic host"
    return "other"


def platform_label(slug: str, host: str) -> str:
    """Recognized platform if the slug matches one, else the service derived from the
    domain so individually-registered sites (github, steam, wikipedia, …) are not all
    lumped as one 'generic host' bucket."""
    p = platform_from_slug(slug)
    if p == "generic host":
        return service_from_host(host)
    return p


def marker_kind(path: Path) -> str:
    name = path.name
    for suffix, label in POLL_SUFFIXES.items():
        if name.endswith(suffix):
            return label
    if name.endswith(".json"):
        return "polling"
    return "other"


def slug_from_marker_path(path: Path) -> str:
    name = path.name
    for suffix in POLL_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    if name.endswith(".json"):
        return name[:-5]
    return path.stem


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


def rejected_group(reason: object) -> tuple[str, str]:
    text = str(reason or "").upper()
    if any(token in text for token in ("TARGET_NOT_FOUND", "CERT_OR_DNS_BROKEN", "HTTP 404")):
        return "exclude", "dead"
    if any(token in text for token in ("CLOUDFLARE", "BASELINE_BLOCKED", "BLOCKED")):
        return "blocked", "blocked"
    return "content", "content"


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
    sites = []

    if not state_dir.exists():
        return {"markers": markers, "total": 0, "sites": sites}

    total = 0
    for path in sorted(state_dir.glob("*.json")):
        if not path.is_file():
            continue
        total += 1
        kind = marker_kind(path)
        markers[kind] += 1
        data = load_json(path)
        slug = str(data.get("slug") or slug_from_marker_path(path))
        url = str(data.get("url") or data.get("source_url") or data.get("_source_url") or "")
        host = hostname_from_url(url)
        if kind == "polling":
            group = "board"
            status = str(data.get("last_status") or "unknown")
        elif kind == "rejected":
            group, status = rejected_group(data.get("reason"))
        elif kind == "failed":
            group, status = "blocked", "blocked"
        elif kind == "bug":
            group, status = "exclude", "bug"
        else:
            group, status = "exclude", kind

        if group == "exclude":
            continue

        sites.append(
            {
                "slug": slug,
                "platform": platform_label(slug, host),
                "host": host or "unknown host",
                "group": group,
                "status": status,
                "seen_post_ids": data.get("seen_post_ids") if isinstance(data.get("seen_post_ids"), list) else [],
            }
        )

    return {"markers": markers, "total": total, "sites": sites}


def read_sites(poll: dict) -> list[dict]:
    return list(poll.get("sites") or [])


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


PALETTE = [
    "#52616b", "#8a6f4d", "#3d737f", "#9b6b6b", "#6f7f52", "#6d647c", "#4f6f8f", "#7b5c8c",
    "#5f8a72", "#a07a4f", "#506b8a", "#8c5c6d", "#7a8c4f", "#4f8c8c", "#a06b8a", "#6b7a9b",
]
OTHER_PLATFORM = "other site"
OTHER_COLOR = "#bcb3a4"


def platform_color_map(sites: list[dict]) -> dict:
    """Give the most common platforms a distinct color; fold the long tail of one-off
    sites into a single 'other site' bucket so the legend stays readable and the chart
    is not one undifferentiated mass. Mutates each site's platform to the bucket label."""
    counts = Counter(str(site["platform"]) for site in sites)
    top = [p for p, _ in counts.most_common(len(PALETTE))]
    topset = set(top)
    has_other = any(str(site["platform"]) not in topset for site in sites)
    for site in sites:
        if str(site["platform"]) not in topset:
            site["platform"] = OTHER_PLATFORM
    cmap = {platform: PALETTE[i] for i, platform in enumerate(top)}
    if has_other:
        cmap[OTHER_PLATFORM] = OTHER_COLOR
    return cmap


def _hash_unit(value: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def svg_grouped_scatter(sites: list[dict], color_map: dict) -> str:
    width = 760
    height = 460
    pad = 44
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad
    groups = [
        ("board", "Watched boards"),
        ("content", "Content pages"),
        ("blocked", "Blocked"),
    ]
    centers = {
        "board": pad + plot_w * 0.18,
        "content": pad + plot_w * 0.50,
        "blocked": pad + plot_w * 0.82,
    }

    if not sites:
        return (
            f'<svg id="siteScatter" viewBox="0 0 {width} {height}" role="img" aria-label="Site outcome scatter">'
            f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
            f'<rect x="{pad}" y="{pad}" width="{plot_w}" height="{plot_h}" class="scatter-frame"></rect>'
            f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" class="svg-label">No sites yet</text>'
            "</svg>"
        )

    circles = []
    max_board_posts = max((len(site.get("seen_post_ids") or []) for site in sites if site.get("group") == "board"), default=0)
    for group, _ in groups:
        group_sites = sorted(
            [site for site in sites if site.get("group") == group],
            key=lambda site: (str(site["platform"]), str(site["host"]), str(site["slug"])),
        )
        count = len(group_sites)
        for i, site in enumerate(group_sites):
            base_y = pad + 60 if count <= 1 else pad + 60 + (plot_h - 116) * i / (count - 1)
            y = min(height - pad - 28, max(pad + 48, base_y + (_hash_unit(str(site["slug"]), "y") - 0.5) * 18))
            x = min(pad + plot_w - 24, max(pad + 24, centers[group] + (_hash_unit(str(site["slug"]), "x") - 0.5) * 104))
            platform = str(site["platform"])
            posts = len(site.get("seen_post_ids") or [])
            radius = 3.5
            if group == "board":
                radius = 3 + (5 * math.log1p(posts) / math.log1p(max_board_posts) if max_board_posts else 0)
            status = str(site.get("status") or "unknown")
            ring = ' stroke="var(--ink)" stroke-width="1.4"' if group == "board" and status == "ok" else ""
            circles.append(
                f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                f'fill="{color_map.get(platform, PALETTE[0])}"{ring} '
                f'data-pf="{esc(platform)}" data-domain="{esc(site["host"])}" '
                f'data-status="{esc(status)}"></circle>'
            )

    group_counts = Counter(str(site.get("group")) for site in sites)
    labels = []
    for group, label in groups:
        labels.append(
            f'<text x="{centers[group]:.1f}" y="{pad - 16}" text-anchor="middle" class="svg-label">'
            f'{esc(label)} · {group_counts.get(group, 0)}</text>'
        )

    return (
        f'<svg id="siteScatter" viewBox="0 0 {width} {height}" role="img" aria-label="Site outcome scatter">'
        f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
        f'<rect x="{pad}" y="{pad}" width="{plot_w}" height="{plot_h}" class="scatter-frame"></rect>'
        + "".join(labels)
        + "".join(circles)
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
    sites = read_sites(poll)
    color_map = platform_color_map(sites)
    scatter_chart = svg_grouped_scatter(sites, color_map)
    platform_counts = Counter(str(s["platform"]) for s in sites)
    legend_html = "".join(
        f'<li><span class="swatch" style="background:{color}"></span>{esc(platform)}<b>{platform_counts.get(platform, 0)}</b></li>'
        for platform, color in color_map.items()
    ) or '<li>No watched sites yet</li>'

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

    all_hosts = sorted(configs["hosts"].items(), key=lambda kv: (-kv[1], kv[0]))
    host_total = len(all_hosts)
    top_hosts = "".join(
        f'<li data-host="{esc(host)}"><span>{esc(host)}</span><b>{count}</b></li>' for host, count in all_hosts
    )
    if not top_hosts:
        top_hosts = '<li data-host=""><span>No public host summary yet</span><b>0</b></li>'

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
    .scatter-bg {{ fill: var(--panel); }}
    .scatter-frame {{ fill: none; stroke: var(--muted); stroke-width: 1; }}
    .dot {{ opacity: 0.58; cursor: pointer; transition: opacity 0.12s ease; }}
    #siteScatter.dimmed .dot {{ opacity: 0.08; }}
    #siteScatter.dimmed .dot.hl {{ opacity: 0.95; }}
    .dot-tip {{
      position: fixed;
      z-index: 30;
      pointer-events: none;
      background: var(--ink);
      color: var(--panel);
      padding: 7px 11px;
      border-radius: 5px;
      font-size: 0.82rem;
      line-height: 1.35;
      box-shadow: 0 3px 12px rgba(31, 37, 40, 0.28);
      max-width: 300px;
    }}
    .dot-tip b {{ display: block; }}
    .dot-tip span {{ color: var(--line); font-size: 0.76rem; }}
    ol, ul {{ padding-left: 22px; }}
    .legend {{
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: 6px 18px;
      padding: 0;
      margin: 14px 0 0;
    }}
    .legend li {{
      display: flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 0.86rem;
    }}
    .legend b {{ color: var(--ink); }}
    .swatch {{
      width: 11px;
      height: 11px;
      border-radius: 2px;
      display: inline-block;
    }}
    .host-search {{
      width: 100%;
      padding: 10px 12px;
      margin: 10px 0 0;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      font: inherit;
    }}
    .host-empty {{ margin-top: 10px; }}
    .host-list {{
      list-style: none;
      padding: 0;
      margin: 10px 0 0;
      border-top: 1px solid var(--line);
    }}
    .host-list.scroll {{
      max-height: 360px;
      overflow-y: auto;
    }}
    .host-list li {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      border-bottom: 1px solid var(--line);
      padding: 9px 0;
    }}
    .host-list li[hidden] {{ display: none; }}
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
      .metrics {{ grid-template-columns: 1fr 1fr; }}
      th:nth-child(1), td:nth-child(1) {{ display: none; }}
    }}
    @media (max-width: 480px) {{
      .metrics {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="kicker">Public status site</div>
    <h1>Notice Watcher</h1>
    <p class="meta">Generated {esc(generated_at.strftime("%Y-%m-%d %H:%M:%S %Z"))}</p>
  </header>

  <section aria-labelledby="overview">
    <h2 id="overview">Overview</h2>
    <div class="metrics">
      {metric("registered configs", config_count, "tracked source definitions")}
      {metric("watched sites", polling_count, "active runtime states")}
      {metric("needs review", failed_count + bug_count, "failed or bug markers")}
      {metric("total jobs", sum(jobs["status"].values()), job_status)}
    </div>
  </section>

  <section aria-labelledby="figures">
    <h2 id="figures">Figures</h2>
    <figure>
      {scatter_chart}
      <ul class="legend">{legend_html}</ul>
      <div id="dotTip" class="dot-tip" hidden></div>
      <figcaption>Figure 1. Every page we evaluated, sorted by what it turned out to be. Left = list/board
        pages we actively watch (each dot is one board; dot color is its platform, see legend; a ring
        marks fully active boards). Middle = single content pages (one article or info page, not a
        board) that we skip. Right = pages we could not enter (anti-bot / Cloudflare). Broken or dead
        URLs are left out. Hover a dot to highlight its platform and see the domain.</figcaption>
    </figure>
    <script>
      (function () {{
        var svg = document.getElementById('siteScatter');
        var tip = document.getElementById('dotTip');
        if (!svg || !tip) return;
        function clear() {{
          svg.classList.remove('dimmed');
          svg.querySelectorAll('.dot.hl').forEach(function (d) {{ d.classList.remove('hl'); }});
          tip.hidden = true;
        }}
        svg.addEventListener('mouseover', function (e) {{
          var c = e.target.closest ? e.target.closest('.dot') : null;
          if (!c) {{ clear(); return; }}
          var pf = c.getAttribute('data-pf');
          svg.classList.add('dimmed');
          svg.querySelectorAll('.dot').forEach(function (d) {{
            d.classList.toggle('hl', d.getAttribute('data-pf') === pf);
          }});
          tip.innerHTML = '<b>' + c.getAttribute('data-domain') + '</b>'
            + '<span>' + pf + ' · ' + c.getAttribute('data-status') + '</span>';
          tip.hidden = false;
        }});
        svg.addEventListener('mousemove', function (e) {{
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }});
        svg.addEventListener('mouseleave', clear);
      }})();
    </script>
  </section>

  <section aria-labelledby="sources">
    <h2 id="sources">Public Source Domains</h2>
    <p class="meta">{host_total} domains tracked. Type to check whether one is already watched.</p>
    <input id="hostSearch" class="host-search" type="search" placeholder="Search a domain…" autocomplete="off" oninput="filterHosts(this.value)">
    <p id="hostEmpty" class="meta host-empty" hidden>No matching domain.</p>
    <ul id="hostList" class="host-list scroll">{top_hosts}</ul>
    <script>
      function filterHosts(q) {{
        q = q.trim().toLowerCase();
        var shown = 0;
        document.querySelectorAll('#hostList li').forEach(function (li) {{
          var match = (li.dataset.host || '').indexOf(q) !== -1;
          li.hidden = !match;
          if (match) shown++;
        }});
        document.getElementById('hostEmpty').hidden = shown !== 0;
      }}
    </script>
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
