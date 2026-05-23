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


def platform_from_slug(slug: str) -> str:
    for prefix in PLATFORM_PREFIXES:
        if slug.startswith(prefix):
            return prefix[:-1]
    if slug.startswith("host_"):
        return "generic host"
    return "other"


# config `strategy` (how each board is fetched) -> human label shown in the figure.
FETCH_LABELS = {
    "httpx_html": "static HTML",
    "httpx_json": "JSON API",
    "playwright_html": "headless browser",
    "handwritten": "custom adapter",
}
FETCH_COLORS = {
    "static HTML": "#3d737f",
    "JSON API": "#6f7f52",
    "headless browser": "#8a6f4d",
    "custom adapter": "#7b5c8c",
    "other method": "#9b6b6b",
    "content page": "#bcb3a4",
    "blocked": "#9aa0a6",
    "dead URL": "#c4b9a6",
    "system bug": "#b88a8a",
}
# legend / color order
FETCH_ORDER = [
    "static HTML", "JSON API", "headless browser", "custom adapter", "other method",
    "content page", "blocked", "dead URL", "system bug",
]


def color_key_for(site: dict, strategy_by_slug: dict) -> str:
    group = site.get("group")
    if group == "board":
        return FETCH_LABELS.get(str(strategy_by_slug.get(site.get("slug"), "")), "other method")
    if group == "content":
        return "content page"
    if group == "blocked":
        return "blocked"
    if group == "dead":
        return "dead URL"
    if group == "bug":
        return "system bug"
    return "other method"


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
    strategy_by_slug = {}

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
        strategy_by_slug[slug] = strategy
        if host and host != "unknown":
            hosts[host] += 1

    return {
        "items": configs,
        "platforms": platforms,
        "strategies": strategies,
        "hosts": hosts,
        "strategy_by_slug": strategy_by_slug,
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
            raw = str(data.get("last_status") or "unknown")
            status = "active" if raw in ("ok", "lurking", "registered") else raw
        elif kind == "rejected":
            group, status = rejected_group(data.get("reason"))
        elif kind == "failed":
            group, status = "blocked", "blocked"
        elif kind == "bug":
            group, status = "bug", "bug"
        else:
            continue

        if group == "exclude":
            group, status = "dead", "dead"

        sites.append(
            {
                "slug": slug,
                "url": url,
                "platform": platform_from_slug(slug),
                "host": host or "unknown host",
                "group": group,
                "status": status,
            }
        )

    return {"markers": markers, "total": total, "sites": sites}


def read_sites(poll: dict) -> list[dict]:
    return list(poll.get("sites") or [])


RC_TO_GROUP = {
    0: ("board", "active"),
    1: ("blocked", "generation failed"),
    2: ("content", "policy rejected"),
    3: ("content", "gate rejected"),
    4: ("dead", "URL unavailable"),
    5: ("blocked", "capability blocked"),
}


def rc_to_group(rc: object) -> tuple[str, str] | None:
    try:
        v = int(rc)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return ("bug", "system bug")
    return RC_TO_GROUP.get(v)


def read_jobs(limit: int = 20) -> dict:
    db_path = ROOT / "output" / "bot.sqlite3"
    status = Counter()
    recent = []
    by_url: dict[str, dict] = {}

    if not db_path.exists():
        return {"status": status, "recent": recent, "by_url": by_url, "available": False}

    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        with con:
            for row in con.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"):
                status[str(row["status"] or "unknown")] += int(row["n"] or 0)
            recent_rows = con.execute(
                """
                SELECT url, status, result_rc, finished_at
                FROM jobs
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            # latest finished job per URL — used to populate figure with URLs that
            # have no poll_state marker yet (or whose marker was overwritten by a
            # later attempt).
            all_rows = con.execute(
                """
                SELECT j.url, j.result_rc, j.finished_at
                FROM jobs j
                JOIN (
                    SELECT url, MAX(finished_at) AS f
                    FROM jobs
                    WHERE finished_at IS NOT NULL
                    GROUP BY url
                ) latest ON latest.url = j.url AND latest.f = j.finished_at
                """
            ).fetchall()
    except sqlite3.Error:
        return {"status": status, "recent": recent, "by_url": by_url, "available": False}
    finally:
        try:
            con.close()
        except UnboundLocalError:
            pass

    for row in recent_rows:
        recent.append(
            {
                "host": hostname_from_url(row["url"]) or "unknown host",
                "status": str(row["status"] or "unknown"),
                "result": rc_label(row["result_rc"]),
                "finished_at": str(row["finished_at"] or ""),
            }
        )

    for row in all_rows:
        url = str(row["url"] or "")
        if not url:
            continue
        by_url[url] = {"rc": row["result_rc"], "finished_at": str(row["finished_at"] or "")}

    return {"status": status, "recent": recent, "by_url": by_url, "available": True}


def top_items(counter: Counter, limit: int = 8) -> list[tuple[str, int]]:
    return [(str(k), int(v)) for k, v in counter.most_common(limit)]


def fetch_color_map(sites: list[dict], strategy_by_slug: dict) -> dict:
    """Assign each site a color key by *how it is fetched* (config strategy) for boards,
    and by outcome for content/blocked. Sets site['color_key']. Returns an ordered
    {color_key: hex} map of only the keys actually present, for fill + legend."""
    present = set()
    for site in sites:
        key = color_key_for(site, strategy_by_slug)
        site["color_key"] = key
        present.add(key)
    return {key: FETCH_COLORS[key] for key in FETCH_ORDER if key in present}


def _hash_unit(value: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


def _dot_svg(site: dict, x: float, y: float, radius: float, color_map: dict) -> str:
    color_key = str(site.get("color_key") or "other method")
    fill = color_map.get(color_key, FETCH_COLORS["other method"])
    status = str(site.get("status") or "unknown")
    url = str(site.get("url") or "")
    circle = (
        f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
        f'fill="{fill}" '
        f'data-pf="{esc(color_key)}" data-domain="{esc(site["host"])}" '
        f'data-status="{esc(status)}" data-url="{esc(url)}"></circle>'
    )
    if url:
        return f'<a xlink:href="{esc(url)}" target="_blank" rel="noopener noreferrer">{circle}</a>'
    return circle


def svg_grouped_scatter(sites: list[dict], color_map: dict) -> str:
    width = 880
    height = 720
    cx = width / 2
    cy = height / 2

    if not sites:
        return (
            f'<svg id="siteScatter" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="Site outcome radial">'
            f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
            f'<text x="{cx:.0f}" y="{cy:.0f}" text-anchor="middle" class="svg-label">No sites yet</text>'
            "</svg>"
        )

    board = [s for s in sites if s.get("group") == "board"]
    content = [s for s in sites if s.get("group") == "content"]
    blocked = [s for s in sites if s.get("group") == "blocked"]
    dead = [s for s in sites if s.get("group") == "dead"]
    bug = [s for s in sites if s.get("group") == "bug"]
    outer = dead + bug

    # ring geometry: inner sunflower disk, then three necklace rings
    r_core = 220.0
    gap = 26.0
    r_content = r_core + gap
    r_blocked = r_content + 28.0
    r_outer = r_blocked + 28.0

    dots: list[str] = []

    # ring 1 — host-clustered sunflower (boards on the same host pack together),
    # color = fetch strategy. Hosts are placed by golden-angle spiral, then each
    # host expands into a mini-spiral so its boards visibly group.
    from collections import OrderedDict as _OD
    board_sorted = sorted(board, key=lambda s: (str(s.get("color_key")), str(s["host"]), str(s["slug"])))
    host_groups: "OrderedDict[str, list[dict]]" = _OD()
    for s in board_sorted:
        host_groups.setdefault(str(s["host"]), []).append(s)
    n_hosts = len(host_groups)
    for h_idx, (_host, items) in enumerate(host_groups.items()):
        r_anchor = r_core * math.sqrt((h_idx + 0.5) / max(n_hosts, 1))
        theta_anchor = h_idx * GOLDEN_ANGLE
        ax = cx + r_anchor * math.cos(theta_anchor)
        ay = cy + r_anchor * math.sin(theta_anchor)
        n_sub = len(items)
        cluster_r = 1.8 * math.sqrt(n_sub)
        for j, site in enumerate(items):
            if n_sub == 1:
                x, y = ax, ay
            else:
                sub_r = cluster_r * math.sqrt((j + 0.5) / n_sub)
                sub_theta = j * GOLDEN_ANGLE
                x = ax + sub_r * math.cos(sub_theta)
                y = ay + sub_r * math.sin(sub_theta)
            dots.append(_dot_svg(site, x, y, 4.2, color_map))

    def necklace(items: list[dict], radius: float, dot_r: float, phase_salt: str) -> None:
        items_sorted = sorted(items, key=lambda s: (str(s["host"]), str(s["slug"])))
        n = len(items_sorted)
        if n == 0:
            return
        phase = _hash_unit(phase_salt, "phase") * math.tau
        for i, site in enumerate(items_sorted):
            theta = phase + i * (math.tau / n)
            jitter = (_hash_unit(str(site["slug"]), "rj") - 0.5) * 6.0
            r = radius + jitter
            x = cx + r * math.cos(theta)
            y = cy + r * math.sin(theta)
            dots.append(_dot_svg(site, x, y, dot_r, color_map))

    # ring 2 — content
    necklace(content, r_content, 3.4, "content")
    # ring 3 — blocked
    necklace(blocked, r_blocked, 3.4, "blocked")
    # ring 4 — dead + system bug
    necklace(outer, r_outer, 3.4, "outer")

    # faint ring guides
    guides = "".join(
        f'<circle class="ring-guide" cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}"></circle>'
        for r in (r_core, r_content, r_blocked, r_outer)
    )

    # ring labels — small text on top of each ring
    label_specs = [
        (r_core, f"Watched boards · {len(board)}"),
        (r_content, f"Content pages · {len(content)}"),
        (r_blocked, f"Blocked · {len(blocked)}"),
        (r_outer, f"Dead / bug · {len(outer)}"),
    ]
    labels = "".join(
        f'<text class="ring-label" x="{cx:.0f}" y="{(cy - r - 6):.1f}" text-anchor="middle">{esc(text)}</text>'
        for r, text in label_specs
    )

    return (
        f'<svg id="siteScatter" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Site outcome radial">'
        f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
        + guides
        + labels
        + "".join(dots)
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

    # Augment with jobs that have no marker file (the figure should show every
    # URL we tried, not only those whose marker survived later retries).
    seen_urls = {s["url"] for s in sites if s.get("url")}
    jobs_by_url = jobs.get("by_url") or {}
    for url, info in jobs_by_url.items():
        if url in seen_urls:
            continue
        mapped = rc_to_group(info.get("rc"))
        if not mapped:
            continue
        group, status = mapped
        if group == "board":
            continue  # only poll_state markers count as active boards
        host = hostname_from_url(url) or "unknown host"
        sites.append({
            "slug": "",
            "url": url,
            "platform": "other",
            "host": host,
            "group": group,
            "status": status,
        })

    color_map = fetch_color_map(sites, configs.get("strategy_by_slug") or {})
    scatter_chart = svg_grouped_scatter(sites, color_map)
    key_counts = Counter(str(s.get("color_key")) for s in sites)
    legend_html = "".join(
        f'<li><span class="swatch" style="background:{color}"></span>{esc(key)}<b>{key_counts.get(key, 0)}</b></li>'
        for key, color in color_map.items()
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

    # Merge hosts from registered configs + every URL we evaluated (rejected / failed / dead / bug).
    host_states: dict[str, Counter] = {}
    for host, count in configs["hosts"].items():
        host_states.setdefault(host, Counter())["registered"] += count
    for site in sites:
        host = site.get("host") or "unknown host"
        if not host or host == "unknown host":
            continue
        group = str(site.get("group") or "")
        if group == "board":
            continue  # already counted via configs
        label = {"content": "content", "blocked": "blocked", "dead": "dead", "bug": "bug"}.get(group)
        if not label:
            continue
        host_states.setdefault(host, Counter())[label] += 1

    STATE_ORDER = ["registered", "blocked", "content", "dead", "bug"]
    STATE_TITLES = {
        "registered": "watched",
        "blocked": "blocked",
        "content": "single article",
        "dead": "URL dead",
        "bug": "system bug",
    }

    def state_badges(states: Counter) -> str:
        parts = []
        for key in STATE_ORDER:
            n = states.get(key, 0)
            if not n:
                continue
            parts.append(f'<span class="state state-{key}" title="{esc(STATE_TITLES[key])}">{esc(STATE_TITLES[key])} {n}</span>')
        return "".join(parts)

    def total(states: Counter) -> int:
        return sum(states.values())

    sorted_hosts = sorted(
        host_states.items(),
        key=lambda kv: (-total(kv[1]), 0 if kv[1].get("registered") else 1, kv[0]),
    )
    host_total = len(sorted_hosts)
    top_hosts = "".join(
        f'<li data-host="{esc(host)}"><span>{esc(host)}</span><span class="states">{state_badges(states)}</span></li>'
        for host, states in sorted_hosts
    )
    if not top_hosts:
        top_hosts = '<li data-host=""><span>No public host summary yet</span><span class="states"></span></li>'

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
    .ring-guide {{ fill: none; stroke: var(--line); stroke-width: 0.8; stroke-dasharray: 2 4; opacity: 0.55; }}
    .ring-label {{ fill: var(--muted); font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: 0.04em; }}
    .dot {{ opacity: 0.7; cursor: pointer; }}
    .dot:hover {{ opacity: 1; }}
    #siteScatter.dimmed .dot {{ opacity: 0.35; }}
    #siteScatter.dimmed .dot.hl {{ opacity: 1; }}
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
    .dot-tip b {{ display: block; word-break: break-all; font-weight: 700; }}
    .dot-tip b i {{ display: block; font-style: normal; font-weight: 400; color: var(--line); font-size: 0.78rem; word-break: break-all; margin-top: 1px; }}
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
      align-items: center;
      gap: 20px;
      border-bottom: 1px solid var(--line);
      padding: 9px 0;
    }}
    .host-list li[hidden] {{ display: none; }}
    .host-list > li > span:first-child {{
      overflow-wrap: anywhere;
      flex: 1 1 auto;
    }}
    .host-list .states {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
    }}
    .state {{
      font-size: 0.74rem;
      padding: 2px 7px;
      border-radius: 10px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: var(--paper);
      white-space: nowrap;
    }}
    .state-registered {{ color: var(--ink); border-color: var(--accent); background: #eaf1f2; }}
    .state-blocked {{ color: #4a4a52; background: #ebebed; }}
    .state-content {{ color: #5a4f3d; background: #efe9dc; }}
    .state-dead {{ color: #6a6253; background: #eee7d8; }}
    .state-bug {{ color: #7a4a4a; background: #f1dede; }}
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
      <figcaption>Figure 1. Every URL we evaluated, arranged from the centre outward by outcome. The inner
        disc is the set of boards we actively watch — each dot's colour shows how we read it (static
        HTML, JSON API, headless browser, or a custom adapter; see legend), and the spiral layout has no
        meaning beyond even packing. The outer rings are URLs we evaluated but did not subscribe to:
        single content pages, anti-bot blocks, and dead or broken URLs. Hover a dot to highlight the
        same fetch method and see the domain; click to open the URL in a new tab.</figcaption>
    </figure>
    <script>
      (function () {{
        var svg = document.getElementById('siteScatter');
        var tip = document.getElementById('dotTip');
        if (!svg || !tip) return;
        // Bucket dots by data-pf once — avoid scanning all dots on every hover.
        var byPf = {{}};
        svg.querySelectorAll('.dot').forEach(function (d) {{
          var pf = d.getAttribute('data-pf') || '';
          (byPf[pf] = byPf[pf] || []).push(d);
        }});
        var activePf = null;
        function setActive(pf) {{
          if (pf === activePf) return;
          if (activePf !== null) {{
            (byPf[activePf] || []).forEach(function (d) {{ d.classList.remove('hl'); }});
          }}
          if (pf !== null) {{
            (byPf[pf] || []).forEach(function (d) {{ d.classList.add('hl'); }});
            svg.classList.add('dimmed');
          }} else {{
            svg.classList.remove('dimmed');
          }}
          activePf = pf;
        }}
        svg.addEventListener('mouseover', function (e) {{
          var c = e.target.closest ? e.target.closest('.dot') : null;
          if (!c) {{ setActive(null); tip.hidden = true; return; }}
          var pf = c.getAttribute('data-pf');
          setActive(pf);
          var domain = c.getAttribute('data-domain') || '';
          var url = c.getAttribute('data-url') || '';
          var path = '';
          if (url) {{
            try {{
              var u = new URL(url);
              path = u.pathname + (u.search || '');
              if (path.length > 60) path = path.slice(0, 57) + '…';
            }} catch (err) {{ path = ''; }}
          }}
          tip.innerHTML = '<b>' + domain + (path && path !== '/' ? '<i>' + path + '</i>' : '') + '</b>'
            + '<span>' + pf + ' · ' + c.getAttribute('data-status') + '</span>';
          tip.hidden = false;
        }});
        svg.addEventListener('mousemove', function (e) {{
          if (tip.hidden) return;
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }});
        svg.addEventListener('mouseleave', function () {{
          setActive(null);
          tip.hidden = true;
        }});
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
