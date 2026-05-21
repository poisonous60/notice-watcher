#!/usr/bin/env python3
"""Generate the public status site as a single static HTML file."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
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
        sites.append(
            {
                "slug": slug,
                "platform": platform_from_slug(slug),
                "host": host or "unknown host",
                "registered_at": data.get("registered_at"),
                "last_poll_at": data.get("last_poll_at"),
                "last_status": data.get("last_status") or kind,
                "consecutive_breakage": data.get("consecutive_breakage", 0),
                "n_baseline": data.get("n_baseline", 0),
                "seen_post_ids": data.get("seen_post_ids") if isinstance(data.get("seen_post_ids"), list) else [],
                "body_empty_at_baseline": bool(data.get("body_empty_at_baseline")),
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


def _parse_age_days(value: object, now: datetime) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return max((now - dt.astimezone(KST)).days, 0)


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [v / norm for v in vector]


def _mat_vec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[i] * vector[i] for i in range(len(vector))) for row in matrix]


def _power_iteration(matrix: list[list[float]], start_index: int) -> tuple[list[float], float]:
    n = len(matrix)
    if n == 0:
        return [], 0.0
    vector = [0.0] * n
    vector[min(start_index, n - 1)] = 1.0
    for _ in range(200):
        next_vector = _normalize(_mat_vec(matrix, vector))
        if not any(next_vector):
            return [0.0] * n, 0.0
        vector = next_vector
    eigenvalue = sum(vector[i] * _mat_vec(matrix, vector)[i] for i in range(n))
    return vector, eigenvalue


CONT_FEATURE_NAMES = ["activity", "age", "glitches", "post count", "empty posts"]


class SiteProjection(NamedTuple):
    points: list[dict]
    pca_ready: bool
    v1: list[float]
    v2: list[float]
    lambda1: float
    lambda2: float
    total_variance: float
    platforms: list[str]
    n_platforms: int
    cont_feature_names: list[str]


def _fallback_site_projection(sites: list[dict], platforms: list[str] | None = None) -> SiteProjection:
    platforms = platforms or sorted({str(site["platform"]) for site in sites})
    return SiteProjection(
        points=_fallback_grid_projection(sites),
        pca_ready=False,
        v1=[],
        v2=[],
        lambda1=0.0,
        lambda2=0.0,
        total_variance=0.0,
        platforms=platforms,
        n_platforms=len(platforms),
        cont_feature_names=CONT_FEATURE_NAMES,
    )


def _project_sites(sites: list[dict], now: datetime) -> SiteProjection:
    platforms = sorted({str(site["platform"]) for site in sites})
    features = []
    for site in sites:
        row = [1.0 if site["platform"] == platform else 0.0 for platform in platforms]
        row.extend(
            [
                math.log1p(len(site.get("seen_post_ids") or [])),
                _parse_age_days(site.get("registered_at"), now),
                _as_float(site.get("consecutive_breakage")),
                _as_float(site.get("n_baseline")),
                1.0 if site.get("body_empty_at_baseline") else 0.0,
            ]
        )
        features.append(row)

    if len(features) < 3 or len(features[0]) < 2:
        return _fallback_site_projection(sites, platforms)

    columns = list(zip(*features))
    means = [sum(col) / len(col) for col in columns]
    stds = []
    for col, mean in zip(columns, means):
        variance = sum((value - mean) ** 2 for value in col) / len(col)
        stds.append(math.sqrt(variance))

    x = []
    for row in features:
        x.append([(value - means[i]) / stds[i] if stds[i] else 0.0 for i, value in enumerate(row)])

    if not any(any(value for value in row) for row in x):
        return _fallback_site_projection(sites, platforms)

    n_features = len(x[0])
    covariance = []
    for i in range(n_features):
        cov_row = []
        for j in range(n_features):
            cov_row.append(sum(row[i] * row[j] for row in x) / (len(x) - 1))
        covariance.append(cov_row)
    total_variance = sum(covariance[i][i] for i in range(n_features))

    v1, lambda1 = _power_iteration(covariance, 0)
    if not any(v1):
        return _fallback_site_projection(sites, platforms)
    deflated = []
    for i in range(n_features):
        deflated.append([covariance[i][j] - lambda1 * v1[i] * v1[j] for j in range(n_features)])
    v2, lambda2 = _power_iteration(deflated, 1 if n_features > 1 else 0)

    points = []
    for site, row in zip(sites, x):
        points.append({**site, "x": sum(row[i] * v1[i] for i in range(n_features)), "y": sum(row[i] * v2[i] for i in range(n_features))})
    return SiteProjection(
        points=points,
        pca_ready=any(v2),
        v1=v1,
        v2=v2,
        lambda1=lambda1,
        lambda2=lambda2,
        total_variance=total_variance,
        platforms=platforms,
        n_platforms=len(platforms),
        cont_feature_names=CONT_FEATURE_NAMES,
    )


def _fallback_grid_projection(sites: list[dict]) -> list[dict]:
    if not sites:
        return []
    cols = max(1, math.ceil(math.sqrt(len(sites))))
    points = []
    for i, site in enumerate(sites):
        points.append({**site, "x": float(i % cols), "y": float(i // cols)})
    return points


PALETTE = ["#52616b", "#8a6f4d", "#3d737f", "#9b6b6b", "#6f7f52", "#6d647c", "#4f6f8f", "#7b5c8c", "#5f8a72", "#a07a4f", "#506b8a", "#8c5c6d"]


def platform_color_map(sites: list[dict]) -> dict:
    platforms = sorted({str(site["platform"]) for site in sites})
    return {platform: PALETTE[i % len(PALETTE)] for i, platform in enumerate(platforms)}


def svg_pca_scatter(sites: list[dict], now: datetime, color_map: dict) -> str:
    width = 760
    height = 460
    pad = 44
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad

    if not sites:
        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Watched site projection scatter">'
            f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
            f'<rect x="{pad}" y="{pad}" width="{plot_w}" height="{plot_h}" class="scatter-frame"></rect>'
            f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle" class="svg-label">No watched sites yet</text>'
            "</svg>"
        )

    projection = _project_sites(sites, now)
    points = projection.points
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    max_posts = max([len(point.get("seen_post_ids") or []) for point in points], default=0)

    def sx(value: float) -> float:
        return pad + (value - min_x) * plot_w / span_x

    def sy(value: float) -> float:
        return height - pad - (value - min_y) * plot_h / span_y

    circles = []
    for point in points:
        posts = len(point.get("seen_post_ids") or [])
        radius = 3 + (5 * posts / max_posts if max_posts else 0)
        title = f"{point['host']} · {point['platform']} · {point.get('last_status') or 'unknown'}"
        circles.append(
            f'<circle cx="{sx(point["x"]):.1f}" cy="{sy(point["y"]):.1f}" r="{radius:.1f}" '
            f'fill="{color_map.get(point["platform"], PALETTE[0])}" opacity="0.58">'
            f"<title>{esc(title)}</title></circle>"
        )

    center_x = pad + plot_w / 2
    center_y = pad + plot_h / 2
    loading_arrows = []
    if projection.pca_ready:
        arrow_scale = min(plot_w, plot_h) * 0.42
        specs = []
        for k, name in enumerate(projection.cont_feature_names):
            i = projection.n_platforms + k
            if i >= len(projection.v1) or i >= len(projection.v2):
                continue
            dx = projection.v1[i]
            dy = projection.v2[i]
            specs.append((name, dx, dy, math.sqrt(dx * dx + dy * dy)))
        max_mag = max((mag for _, _, _, mag in specs), default=0.0)
        placed: list[tuple[float, float]] = []
        for name, dx, dy, mag in specs:
            if mag == 0 or max_mag == 0:
                continue
            # arrow length scales with loading magnitude (proper biplot) so
            # near-parallel (correlated) features separate by length, not overlap.
            length = arrow_scale * (0.45 + 0.55 * mag / max_mag)
            ux, uy = dx / mag, dy / mag
            end_x = center_x + ux * length
            end_y = center_y - uy * length
            angle = math.atan2(end_y - center_y, end_x - center_x)
            head = 7
            spread = 0.45
            p1 = (end_x, end_y)
            p2 = (end_x - head * math.cos(angle - spread), end_y - head * math.sin(angle - spread))
            p3 = (end_x - head * math.cos(angle + spread), end_y - head * math.sin(angle + spread))
            label_x = end_x + 9 * math.cos(angle)
            label_y = end_y + 9 * math.sin(angle)
            # nudge label down while it collides with an already-placed label
            for _ in range(8):
                if not any(abs(label_x - lx) < 66 and abs(label_y - ly) < 14 for lx, ly in placed):
                    break
                label_y += 15
            placed.append((label_x, label_y))
            anchor = "start" if math.cos(angle) >= 0 else "end"
            loading_arrows.append(
                f'<line x1="{center_x:.1f}" y1="{center_y:.1f}" x2="{end_x:.1f}" y2="{end_y:.1f}" class="loading-arrow"></line>'
                f'<polygon points="{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}" class="loading-head"></polygon>'
                f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}" class="svg-label loading-label">{esc(name)}</text>'
            )

    variance_note = ""
    if projection.pca_ready and projection.total_variance > 0:
        pc1 = round(100 * projection.lambda1 / projection.total_variance)
        pc2 = round(100 * projection.lambda2 / projection.total_variance)
        variance_note = (
            f'<text x="{pad}" y="{height - 22}" class="svg-label">PC1 = {pc1}% of variation</text>'
            f'<text x="{width - pad}" y="{height - 22}" text-anchor="end" class="svg-label">PC2 = {pc2}% of variation</text>'
        )
    note = "" if projection.pca_ready else f'<text x="{pad}" y="{pad - 14}" class="svg-label">Fallback layout: not enough varied data for PCA</text>'
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Watched site projection scatter">'
        f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
        f'<rect x="{pad}" y="{pad}" width="{plot_w}" height="{plot_h}" class="scatter-frame"></rect>'
        f"{note}"
        + "".join(circles)
        + "".join(loading_arrows)
        + variance_note
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
    scatter_chart = svg_pca_scatter(sites, generated_at, color_map)
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
    .loading-arrow {{ stroke: var(--ink); stroke-width: 1.2; opacity: 0.85; }}
    .loading-head {{ fill: var(--ink); opacity: 0.85; }}
    .loading-label {{
      fill: var(--ink);
      font-weight: 600;
      paint-order: stroke;
      stroke: var(--panel);
      stroke-width: 3.5px;
      stroke-linejoin: round;
    }}
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
      <figcaption>Figure 1. A map of every site we watch. Each dot is one site — its <strong>color</strong> is the platform (see legend below) and its <strong>size</strong> shows how busy it is. We describe each site by a few simple traits (how active it is, how long we've watched it, how often its updates glitch) and lay them on a flat map so that <strong>similar sites land close together</strong>. Same-colored dots clump, and the overall spread shows how varied our coverage is. The gray arrows point toward higher values of each trait — dots near the “age” arrow are older, near “activity” are busier. Hover any dot to see its domain.</figcaption>
    </figure>
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
