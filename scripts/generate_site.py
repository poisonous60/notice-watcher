#!/usr/bin/env python3
"""Generate the public status site as a single static HTML file."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, date as _date
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo("Asia/Seoul")

# Static narrative of the probe pipeline — used by the Figure 3 HAR section.
# Edit when probe code refactors so the public page keeps describing what runs.
# Stages reflect the actual execution order: static GET first, headless+HAR
# captured only when needed, signal extractors are per-extractor (no shared
# load step), and the decision path is the multi-arm register dispatch.
PROBE_PIPELINE: list[dict] = [
    {
        "id": "fetch",
        "title": "Probe fetches",
        "tagline": "static + browser",
        "summary": (
            "Static GET first; if the page can't be read without a real "
            "browser, Playwright launches and replays it."
        ),
        "steps": [
            ("scripts/probe.py", "main(argv) → _run(args, url, slug)",
             "CLI entry — parses URL + flags, opens output/probe/<slug>/."),
            ("probe/fetch_static.py", "fetch()",
             "Static httpx GET with preset headers; first attempt before the browser."),
            ("probe/fetch_headless.py", "fetch_with_capture()",
             "Playwright Chromium with record_har_path on the context — runs only "
             "when static is insufficient."),
        ],
    },
    {
        "id": "har",
        "title": "Capture HAR",
        "tagline": "network log + HTML",
        "summary": (
            "When the headless run was needed, Playwright writes traffic.har "
            "plus the rendered HTML and screenshots."
        ),
        "steps": [
            ("probe/fetch_headless.py", "browser.new_context(record_har_path=…)",
             "HAR is buffered as the page runs; context.close() flushes it to disk."),
            ("output/probe/<slug>/traffic.har", "—",
             "Primary network log every later extractor reads when present."),
            ("output/probe/<slug>/list.html", "—",
             "Parallel HTML snapshot consumed by RSS / pagination / platform detectors."),
            ("output/probe/<slug>/environment.json", "—",
             "Runtime info: platform, Python, arch, outbound IP, goodbyedpi flag, proxy env."),
        ],
    },
    {
        "id": "entries",
        "title": "Inspect entries",
        "tagline": "data calls, not assets",
        "summary": (
            "Each extractor parses the HAR itself and drops static assets and "
            "ad/tracker hosts before scoring candidates."
        ),
        "steps": [
            ("probe/extract.py", "json.loads(har_path.read_text())",
             "Every extractor loads the HAR JSON it needs — there is no shared "
             "filtered-entry artifact."),
            ("probe/extract.py", "_entry_resource_type()",
             "Tags each entry by resourceType (xhr / fetch / document / image / ...)."),
            ("probe/extract.py", "_AD_TRACKER_RE + per-extractor filters",
             "Drops static assets, ad/tracker hosts, and image responses."),
        ],
    },
    {
        "id": "signals",
        "title": "Match signals",
        "tagline": "APIs · feeds · pages · platforms",
        "summary": (
            "Five extractors hunt JSON APIs, body APIs, RSS, pagination, and "
            "known platform fingerprints."
        ),
        "steps": [
            ("probe/extract.py", "traffic_api_candidates()",
             "Detect JSON list endpoints — cross-host brand match included."),
            ("probe/extract.py", "traffic_article_body_candidates()",
             "Detect article-body JSON endpoints (per-post payloads)."),
            ("probe/extract.py", "rss_feed_urls()",
             "Find RSS / Atom feeds in <link> + HAR responses."),
            ("probe/extract.py", "pagination_hints()",
             "Detect ?page=, /p/2/, infinite-scroll templates."),
            ("probe/extract.py", "detect_*_platform()",
             "Fingerprint WordPress / Discourse / XenForo / Lemmy / Mastodon / ..."),
        ],
    },
    {
        "id": "decide",
        "title": "Choose path",
        "tagline": "digest · recognizer · writer",
        "summary": (
            "Signals fold into a digest. URL fast-path, probe-marker platform "
            "config, api_loop, or agentic LLM commits the final config."
        ),
        "steps": [
            ("scripts/register.py", "_try_known_platform(url)",
             "URL fast-path — known platform shortcut runs before any probe."),
            ("engine/digest.py", "build_digest(*, slug, url, …)",
             "Roll signals + artifacts into one recommendation."),
            ("scripts/register.py", "probe-marker platform config",
             "WordPress / Discourse / XenForo / Lemmy / PeerTube / Mbin detected "
             "from probe artifacts."),
            ("scripts/register.py", "auto: api_loop_once → agentic",
             "Generation dispatch — api_loop one-shot, escalates to multi-turn "
             "agent in auto mode."),
            ("scripts/register.py", "_register_built_config()",
             "Validate end-to-end then write configs/<slug>.json."),
        ],
    },
]

# Figure 2 — fix-layer bucket vocabulary (CONTEXT.md "추론 개선" / fix-layer letters).
# Priority for combos = F > C > A > B/D/E first-match. Legacy `config`/`adapter` → B/D/E.
BUCKET_ORDER = ["no-change", "B/D/E", "A", "C", "F"]  # bottom→top stack order
BUCKET_COLORS = {
    "no-change": "#d4cdbc",
    "B/D/E":     "#6f7f52",
    "A":         "#7b5c8c",
    "C":         "#8a6f4d",
    "F":         "#3d737f",
}
BUCKET_LABELS = {
    "no-change": "no fix layer (terminal closure)",
    "B/D/E":     "B/D/E · engine · writer · validate",
    "A":         "A · prompt / agentic",
    "C":         "C · probe heuristic",
    "F":         "F · recognizer / platform",
}

# Hand-maintained timeline milestones. Add new dated entry when a pipeline-level
# capability lands (ADR, infra rollout, gate rule). Format: (iso_date, short_label, full_description).
EVENT_ANNOTATIONS = [
    ("2026-05-11", "Project start", "First case_runs row recorded — repo bootstrapped."),
    ("2026-05-15", "Self-improvement v3", "Per-case memory + reviewer subagent + pre-push hook landed (commit 3bfebc6)."),
    ("2026-05-19", "Permanent-gate rule", "CLAUDE.md §8a — favour permanent gate over one-shot bypass."),
    ("2026-05-21", "5-batch parallel run", "244 cases in one day; academic / forums / fedi / blogcms / recognizer 승급."),
    ("2026-05-24", "Worktree isolation", "ADR 0015 — parallel Codex sessions via git worktree."),
    ("2026-05-26", "Agentic register", "ADR 0020 — register call-site switched to multi-turn agent (api_loop default)."),
]

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
    ".BROKEN.json": "broken",
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
    return (
        f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
        f'fill="{fill}" '
        f'data-pf="{esc(color_key)}" data-domain="{esc(site["host"])}" '
        f'data-status="{esc(status)}"></circle>'
    )


def svg_grouped_scatter(sites: list[dict], color_map: dict) -> str:
    width = 920
    height = 840
    cx = width / 2
    cy = height / 2

    if not sites:
        return (
            f'<svg id="siteScatter" '
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

    # ring geometry: inner sunflower disk; outer bands auto-expand into multiple
    # sub-rings when single-ring packing would overlap.
    r_core = 220.0

    dots: list[str] = []

    # ring 1 — host-clustered sunflower (boards on the same host pack together),
    # color = fetch strategy. Each host gets an anchor whose radial position is
    # proportional to its cumulative cluster *area* (∝ member count) so that big
    # clusters claim more room — adjacent anchors stay apart even when clusters
    # have very different sizes.
    from collections import OrderedDict as _OD
    board_sorted = sorted(board, key=lambda s: (str(s.get("color_key")), str(s["host"]), str(s["slug"])))
    host_groups: "OrderedDict[str, list[dict]]" = _OD()
    for s in board_sorted:
        host_groups.setdefault(str(s["host"]), []).append(s)
    items_list = list(host_groups.items())
    weights = [max(1, len(items)) for _host, items in items_list]
    total_w = sum(weights) or 1
    r_effective = r_core - 14.0  # leave a margin so the largest cluster doesn't bleed into ring 2

    # initial anchor placement: area-weighted sunflower
    anchors: list[list[float]] = []  # [ax, ay, cluster_r]
    cumsum = 0.0
    for h_idx, (_host, items) in enumerate(items_list):
        w = weights[h_idx]
        r_anchor = r_effective * math.sqrt((cumsum + w * 0.5) / total_w)
        theta_anchor = h_idx * GOLDEN_ANGLE
        cumsum += w
        ax = cx + r_anchor * math.cos(theta_anchor)
        ay = cy + r_anchor * math.sin(theta_anchor)
        n_sub = len(items)
        cluster_r = 3.0 + 2.6 * math.sqrt(max(n_sub - 1, 0))
        anchors.append([ax, ay, cluster_r])

    # Lloyd-style relaxation: golden-angle sunflower has Fibonacci-neighbour collisions
    # (e.g. index i and i+13 land ~12° apart in angle); push overlapping anchors apart.
    gap_px = 4.0
    r_clamp = r_core - 2.0  # keep anchors inside the disc
    n_a = len(anchors)
    for _ in range(40):
        any_move = False
        for i in range(n_a):
            for j in range(i + 1, n_a):
                ax_i, ay_i, ri = anchors[i]
                ax_j, ay_j, rj = anchors[j]
                dx = ax_j - ax_i
                dy = ay_j - ay_i
                d = math.hypot(dx, dy)
                min_d = ri + rj + gap_px
                if d >= min_d:
                    continue
                if d < 1e-6:
                    # identical — nudge deterministically
                    dx, dy = math.cos(i * 0.7), math.sin(i * 0.7)
                    d = 1.0
                push = (min_d - d) * 0.5
                ux, uy = dx / d, dy / d
                anchors[i][0] -= ux * push
                anchors[i][1] -= uy * push
                anchors[j][0] += ux * push
                anchors[j][1] += uy * push
                any_move = True
        # clamp to disc
        for k in range(n_a):
            ax_k, ay_k, rk = anchors[k]
            d_c = math.hypot(ax_k - cx, ay_k - cy)
            limit = r_clamp - rk
            if d_c > limit and d_c > 0:
                scale = limit / d_c
                anchors[k][0] = cx + (ax_k - cx) * scale
                anchors[k][1] = cy + (ay_k - cy) * scale
        if not any_move:
            break

    # emit sub-dots
    for (anchor, (_host, items)) in zip(anchors, items_list):
        ax, ay, cluster_r = anchor
        n_sub = len(items)
        for j, site in enumerate(items):
            if n_sub == 1:
                x, y = ax, ay
            else:
                sub_r = cluster_r * math.sqrt((j + 0.5) / n_sub)
                sub_theta = j * GOLDEN_ANGLE
                x = ax + sub_r * math.cos(sub_theta)
                y = ay + sub_r * math.sin(sub_theta)
            dots.append(_dot_svg(site, x, y, 4.2, color_map))

    def necklace(items: list[dict], inner_r: float, dot_r: float, phase_salt: str) -> tuple[float, float]:
        """Lay items out on one or more concentric sub-rings starting at inner_r,
        expanding outward when a single ring would pack tighter than 2*dot_r+gap.
        Returns (label_r, outer_r) — label_r is the inner ring radius, outer_r is
        the radius the next band should start from."""
        n = len(items)
        if n == 0:
            return inner_r, inner_r
        items_sorted = sorted(items, key=lambda s: (str(s["host"]), str(s["slug"])))
        spacing = 2 * dot_r + 2.5
        row_step = 2 * dot_r + 2.5
        phase = _hash_unit(phase_salt, "phase") * math.tau
        i = 0
        row = 0
        outer_r = inner_r
        while i < n:
            r_row = inner_r + row * row_step
            cap = max(1, int((math.tau * r_row) / spacing))
            row_n = min(cap, n - i)
            row_phase = phase + row * (math.tau / max(cap * 2, 1))  # offset alternating rows
            for k in range(row_n):
                site = items_sorted[i + k]
                theta = row_phase + (k + 0.5) * (math.tau / row_n)
                x = cx + r_row * math.cos(theta)
                y = cy + r_row * math.sin(theta)
                dots.append(_dot_svg(site, x, y, dot_r, color_map))
            outer_r = r_row
            i += row_n
            row += 1
        return inner_r, outer_r

    band_gap = 14.0
    label_specs: list[tuple[float, str]] = [(r_core, f"Watched boards · {len(board)}")]
    guide_radii: list[float] = [r_core]

    cursor = r_core + band_gap
    label_r, cursor = necklace(content, cursor, 3.4, "content")
    label_specs.append((label_r, f"Content pages · {len(content)}"))
    guide_radii.append(label_r)
    cursor += band_gap

    label_r, cursor = necklace(blocked, cursor, 3.4, "blocked")
    label_specs.append((label_r, f"Blocked · {len(blocked)}"))
    guide_radii.append(label_r)
    cursor += band_gap

    label_r, cursor = necklace(outer, cursor, 3.4, "outer")
    label_specs.append((label_r, f"Dead / bug · {len(outer)}"))
    guide_radii.append(label_r)

    # faint ring guides — one per band's inner radius
    guides = "".join(
        f'<circle class="ring-guide" cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}"></circle>'
        for r in guide_radii
    )

    # ring labels — small text above each band
    labels = "".join(
        f'<text class="ring-label" x="{cx:.0f}" y="{(cy - r - 6):.1f}" text-anchor="middle">{esc(text)}</text>'
        for r, text in label_specs
    )

    return (
        f'<svg id="siteScatter" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Site outcome radial">'
        f'<rect x="0" y="0" width="{width}" height="{height}" class="scatter-bg"></rect>'
        + guides
        + labels
        + "".join(dots)
        + "</svg>"
    )


# ────────────────────────────────────────────────────────────────────────────
# Figure 2 — case-accumulation timeline
# ────────────────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def _fix_layer_bucket(raw) -> str:
    """Map a case_runs.fix_layer raw value to one of BUCKET_ORDER.

    Combos like ``C+F`` go to first-match in priority F>C>A>B/D/E (rationale:
    recognizer/F rollup is more event-shaped). Legacy spellings (`config`,
    `adapter`) folded into B/D/E. Null/none/empty → ``no-change``.
    """
    if isinstance(raw, (list, tuple)):
        raw = "+".join(str(x) for x in raw if x)
    s = (raw or "").strip().upper()
    if not s or s == "NONE":
        return "no-change"
    if s in ("CONFIG", "ADAPTER"):
        return "B/D/E"
    if "F" in s:
        return "F"
    if "C" in s:
        return "C"
    if "A" in s:
        return "A"
    if "B" in s or "D" in s or "E" in s:
        return "B/D/E"
    return "no-change"


def _safe_class(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", text or "x")


def _first_body_paragraph(body: str, *, cap: int = 360) -> str:
    """Pull the first content paragraph out of a case markdown body.

    Skips headings, code fences, blank lines. Joins wrapped lines back into one
    paragraph, caps length, no markdown decoration removed beyond simple
    whitespace normalisation.
    """
    paragraphs: list[str] = []
    cur: list[str] = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        if in_fence:
            continue
        if not stripped:
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        if stripped.startswith("#") or stripped.startswith("|"):
            if cur:
                paragraphs.append(" ".join(cur))
                cur = []
            continue
        cur.append(stripped)
    if cur:
        paragraphs.append(" ".join(cur))
    for p in paragraphs:
        if p:
            return p if len(p) <= cap else p[: cap - 1] + "…"
    return ""


def _outcome_class(outcome: str) -> str:
    """Map outcome to a *texture* class used by Figure 2 — bright = system got
    smarter (improved), darker = hand patch (handcrafted/single-shot)."""
    o = (outcome or "").lower()
    if "improved" in o or "fixed" in o or "recovered" in o:
        return "improved"
    if "handcrafted" in o or "registered" == o or o.startswith("registered"):
        return "handcrafted"
    if "rejected" in o:
        return "rejected"
    return "neutral"


def read_case_records() -> list[dict]:
    """Read every ``docs/cases/*.md`` (including ``_*.md`` batch/bug/chunk files)
    and return one record per file. Each record has the date, bucket, outcome,
    status one-liner, slug (for the GitHub md link), URL when present, and the
    first body paragraph. Sorted oldest→newest.
    """
    cases_dir = ROOT / "docs" / "cases"
    if not cases_dir.exists():
        return []
    try:
        import yaml  # noqa: WPS433 — runtime optional, N100 venv has it
    except ImportError:
        return []
    out: list[dict] = []
    for path in sorted(cases_dir.glob("*.md")):
        if path.name == "INDEX.md":
            continue
        try:
            text = path.read_text(encoding="utf-8").lstrip("﻿")
        except OSError:
            continue
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict):
            continue
        date_v = fm.get("date")
        date_s = str(date_v) if date_v is not None else ""
        if not date_s or len(date_s) < 10:
            continue
        slug = str(fm.get("slug") or path.stem)
        fix_raw = fm.get("fix_layer")
        bucket = _fix_layer_bucket(fix_raw)
        outcome = str(fm.get("outcome") or "")
        body = text[m.end():]
        first_para = _first_body_paragraph(body)
        out.append({
            "date": date_s[:10],
            "slug": slug,
            "filename": path.name,
            "bucket": bucket,
            "outcome": outcome,
            "outcome_class": _outcome_class(outcome),
            "status": str(fm.get("status") or ""),
            "url": str(fm.get("url") or ""),
            "fix_layer": "+".join(fix_raw) if isinstance(fix_raw, (list, tuple)) else (str(fix_raw) if fix_raw else ""),
            "first_paragraph": first_para,
        })
    out.sort(key=lambda r: (r["date"], r["slug"]))
    return out


# Sort key inside each day's column so the foundational "engine" lives at the
# bottom and lighter patches pile on top — visually echoes the user's
# "engine + scrap welded on" metaphor.
_BUCKET_STACK_PRIORITY = {"F": 0, "C": 1, "A": 2, "B/D/E": 3, "no-change": 4}


def svg_case_blocks(records: list[dict], events: list[tuple[str, str, str]]) -> str:
    """Block grid Figure 2 — every case is one square. Days form columns (x =
    date), cases stack upward within each column. Colour = fix-layer bucket
    (no-change = light, F = solid teal etc). Each block is clickable to open
    the case modal. Vertical dashed lines mark pipeline milestones.
    """
    width = 920
    title_pad = 60
    axis_pad = 56
    cx_left = 56
    cx_right = width - 24

    if not records:
        height = 260
        return (
            f'<svg id="caseTimeline" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Case block grid">'
            f'<rect class="scatter-bg" x="0" y="0" width="{width}" height="{height}"></rect>'
            f'<text class="svg-label" x="{width / 2:.0f}" y="{height / 2:.0f}" '
            f'text-anchor="middle">No case history available on this host yet</text>'
            f"</svg>"
        )

    days_sorted = sorted({r["date"] for r in records})
    start = _date.fromisoformat(days_sorted[0])
    end = _date.fromisoformat(days_sorted[-1])
    all_days: list[str] = []
    d = start
    while d <= end:
        all_days.append(d.isoformat())
        d = _date.fromordinal(d.toordinal() + 1)
    n_days = len(all_days)
    day_to_idx = {d: i for i, d in enumerate(all_days)}

    plot_w = cx_right - cx_left
    day_slot = plot_w / n_days

    block_size = 11
    block_gap = 2
    cell = block_size + block_gap
    per_row = max(1, int((day_slot - 4) / cell))

    case_ids = {id(rec): f"case-{i}" for i, rec in enumerate(records)}
    by_day: dict[str, list[dict]] = {}
    for r in records:
        by_day.setdefault(r["date"], []).append(r)
    for day, lst in by_day.items():
        lst.sort(key=lambda r: (_BUCKET_STACK_PRIORITY.get(r["bucket"], 9), r["slug"]))

    max_count = max(len(by_day.get(d, ())) for d in all_days)
    rows_needed = (max_count + per_row - 1) // per_row
    grid_h = max(rows_needed * cell + 4, 180)
    height = title_pad + grid_h + axis_pad

    baseline_y = title_pad + grid_h

    blocks_parts: list[str] = []
    for day, lst in by_day.items():
        idx = day_to_idx[day]
        col_x = cx_left + idx * day_slot + (day_slot - per_row * cell) / 2
        for i, rec in enumerate(lst):
            row = i // per_row
            col = i % per_row
            bx = col_x + col * cell
            by = baseline_y - (row + 1) * cell
            bucket = rec["bucket"]
            blocks_parts.append(
                f'<rect class="case-block bucket-{_safe_class(bucket)} '
                f'outcome-{rec["outcome_class"]}" '
                f'x="{bx:.1f}" y="{by:.1f}" '
                f'width="{block_size}" height="{block_size}" rx="0.5" ry="0.5" '
                f'data-case-id="{esc(case_ids[id(rec)])}" '
                f'data-bucket="{esc(bucket)}" '
                f'tabindex="0" role="button" '
                f'aria-label="{esc(rec["date"])} · {esc(bucket)} case"></rect>'
            )

    engine_line = (
        f'<line class="engine-baseline" x1="{cx_left:.0f}" y1="{baseline_y:.1f}" '
        f'x2="{cx_right:.0f}" y2="{baseline_y:.1f}"></line>'
    )

    tick_parts: list[str] = []
    tick_step = max(1, n_days // 8)
    for i in range(0, n_days, tick_step):
        xi = cx_left + i * day_slot + day_slot / 2
        tick_parts.append(
            f'<text class="axis-tick" x="{xi:.1f}" y="{baseline_y + 16:.0f}" '
            f'text-anchor="middle">{esc(all_days[i][5:])}</text>'
        )

    title = (
        f'<text class="panel-title" x="{cx_left:.0f}" y="{title_pad - 28:.0f}">'
        f"{len(records)} cases bolted onto the engine — click a block to open the note"
        "</text>"
        f'<text class="panel-sub" x="{cx_left:.0f}" y="{title_pad - 12:.0f}">'
        "Each square = one case file. Columns = day. Colour = fix layer; "
        "solid border = improvement that generalised back into the solver."
        "</text>"
    )

    annotation_parts: list[str] = []
    for iso, short, full_text in events:
        idx = day_to_idx.get(iso)
        if idx is None:
            if iso < all_days[0] or iso > all_days[-1]:
                continue
            for i, dd in enumerate(all_days):
                if dd >= iso:
                    idx = i
                    break
            if idx is None:
                continue
        xi = cx_left + idx * day_slot + day_slot / 2
        annotation_parts.append(
            f'<g class="annot" data-date="{esc(iso)}" data-full="{esc(full_text)}">'
            f'<line class="annot-line" x1="{xi:.1f}" y1="{title_pad:.0f}" '
            f'x2="{xi:.1f}" y2="{baseline_y:.1f}"></line>'
            f'<text class="annot-marker" x="{xi:.1f}" y="14" '
            f'text-anchor="middle">{esc(short)}</text>'
            f"</g>"
        )

    return (
        f'<svg id="caseTimeline" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Case block grid by day">'
        f'<rect class="scatter-bg" x="0" y="0" width="{width}" height="{height}"></rect>'
        + title
        + "".join(annotation_parts)
        + engine_line
        + "".join(tick_parts)
        + "".join(blocks_parts)
        + "</svg>"
    )


def render_case_db(records: list[dict]) -> str:
    """Hidden HTML store the modal JS reads when the user clicks a block.
    One `<div class="case-record">` per case with frontmatter in data-* attrs
    and the first paragraph as innerHTML.
    """
    parts: list[str] = []
    for i, rec in enumerate(records):
        host = _short_host(rec.get("url")) or "host masked"
        parts.append(
            f'<div class="case-record" data-case-id="case-{esc(i)}" '
            f'data-date="{esc(rec["date"])}" '
            f'data-bucket="{esc(rec["bucket"])}" '
            f'data-fix-layer="{esc(rec["fix_layer"])}" '
            f'data-outcome="{esc(rec["outcome"])}" '
            f'data-status="{esc(_redact_public_text(rec["status"]))}" '
            f'data-host="{esc(host)}">'
            f"{esc(_redact_public_text(rec['first_paragraph']))}"
            f"</div>"
        )
    return f'<div id="caseDB" hidden>{"".join(parts)}</div>'

# ────────────────────────────────────────────────────────────────────────────
# HAR section — clickable pipeline funnel + per-stage file-flow diagram
# ────────────────────────────────────────────────────────────────────────────


def _short_host(value: object) -> str:
    """ADR 0010 §17 whitelist helper — host only, no path/query/fragment."""
    host = hostname_from_url(value) if value is not None else ""
    if not host:
        return ""
    host = host.lower()
    return host if len(host) <= 60 else host[:57] + "…"


def _short_text(value: object, limit: int = 60) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


_URL_RE = re.compile(r"https?://\S+")
_HOST_SLUG_RE = re.compile(r"\bhost_[a-z0-9_]+_[0-9a-f]{8}\b")


def _redact_public_text(value: object) -> str:
    s = "" if value is None else str(value)
    if _URL_RE.search(s):
        s = _URL_RE.sub(lambda m: _host_mask(m.group(0)) or "host masked", s)
    return _HOST_SLUG_RE.sub("host masked", s)


def svg_har_funnel() -> str:
    """Pipeline funnel — five labelled boxes left → right, one per pipeline
    stage. No aggregate numbers (the user called them meaningless). Click
    target = whole <g class="funnel-stage"> with tabindex + role for
    keyboard activation; the first stage is active by default."""
    width = 920
    height = 170
    margin_x = 28
    n = len(PROBE_PIPELINE)
    col_w = (width - 2 * margin_x) / n
    box_w = col_w - 16
    box_h = 110
    y_mid = height / 2

    boxes: list[str] = []
    arrows: list[str] = []
    last_right = None
    for i, stage in enumerate(PROBE_PIPELINE):
        cx_box = margin_x + i * col_w + (col_w - box_w) / 2
        by = y_mid - box_h / 2
        active = " active" if i == 0 else ""
        boxes.append(
            f'<g class="funnel-stage{active}" data-stage-id="{esc(stage["id"])}" '
            f'tabindex="0" role="button" '
            f'aria-controls="har-panel-{esc(stage["id"])}" '
            f'aria-expanded="{"true" if i == 0 else "false"}" '
            f'aria-label="Stage {i + 1}: {esc(stage["title"])} — click to see files">'
            f'<rect x="{cx_box:.1f}" y="{by:.1f}" width="{box_w:.1f}" height="{box_h}" '
            f'rx="8" ry="8" class="funnel-box"></rect>'
            f'<text class="funnel-step" x="{cx_box + box_w / 2:.1f}" y="{by + 22:.0f}" '
            f'text-anchor="middle">Step {i + 1}</text>'
            f'<text class="funnel-label" x="{cx_box + box_w / 2:.1f}" y="{by + 50:.0f}" '
            f'text-anchor="middle">{esc(stage["title"])}</text>'
            f'<text class="funnel-tagline" x="{cx_box + box_w / 2:.1f}" y="{by + 78:.0f}" '
            f'text-anchor="middle">{esc(stage["tagline"])}</text>'
            f"</g>"
        )
        if last_right is not None:
            arrows.append(
                f'<line class="funnel-arrow" x1="{last_right:.1f}" y1="{y_mid:.0f}" '
                f'x2="{cx_box:.1f}" y2="{y_mid:.0f}" '
                f'marker-end="url(#funnel-arrow-head)"></line>'
            )
        last_right = cx_box + box_w

    arrow_marker = (
        '<defs><marker id="funnel-arrow-head" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="currentColor"></path>'
        "</marker></defs>"
    )

    return (
        f'<svg id="harFunnel" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Probe pipeline — 5 stages, click any stage for files">'
        f'<rect class="scatter-bg" x="0" y="0" width="{width}" height="{height}"></rect>'
        + arrow_marker
        + "".join(arrows)
        + "".join(boxes)
        + "</svg>"
    )


def render_stage_flow_html(stage: dict) -> str:
    """Per-stage file flow as a flat numbered rail."""
    steps = stage["steps"] or []
    if not steps:
        return '<p class="muted">No file steps recorded for this stage.</p>'
    items = []
    for i, (file_path, fn, role) in enumerate(steps):
        items.append(
            '<li class="step-row">'
            f'<span class="step-num">{esc(i + 1)}</span>'
            '<div class="step-body">'
            f'<code class="step-file">{esc(file_path)}</code>'
            '<span class="step-sep">&rarr;</span>'
            f'<code class="step-fn">{esc(fn)}</code>'
            f'<p class="step-role">{esc(role)}</p>'
            '</div>'
            "</li>"
        )
    return f'<ol class="stage-flow">{"".join(items)}</ol>'


def render_stage_panels() -> str:
    """One <section> per pipeline stage. Only the first is visible (others
    carry `hidden`). The funnel JS toggles `hidden` + `aria-expanded` on the
    matching `<g class="funnel-stage">`."""
    parts: list[str] = []
    for i, stage in enumerate(PROBE_PIPELINE):
        hidden_attr = "" if i == 0 else " hidden"
        parts.append(
            f'<section class="stage-panel" id="har-panel-{esc(stage["id"])}" '
            f'data-stage-id="{esc(stage["id"])}"'
            f'{hidden_attr} aria-labelledby="har-panel-{esc(stage["id"])}-title">'
            f'<header class="stage-panel-head">'
            f'<span class="stage-panel-num">Step {esc(i + 1)}</span>'
            f'<h3 id="har-panel-{esc(stage["id"])}-title">{esc(stage["title"])}</h3>'
            f'<p class="stage-panel-summary">{esc(stage["summary"])}</p>'
            f"</header>"
            f'{render_stage_flow_html(stage)}'
            f"</section>"
        )
    return "".join(parts)


# ────────────────────────────────────────────────────────────────────────────
# Figure 4 — live HAR detail for one auto-selected probe (dashboard parity)
# ────────────────────────────────────────────────────────────────────────────

_HAR_DETAIL_CACHE_PATH = ROOT / "output" / "site" / "_har_detail.json"
_HAR_DETAIL_MANIFEST_FILES = (
    "traffic.har",
    "list.html",
    "list_candidates.json",
    "diagnosis.json",
    "feed_candidates.json",
    "environment.json",
    "robots.json",
    "sitemap.json",
    "list.captured_headers.json",
    "article_candidates.json",
    "article_click.json",
)
_HAR_DETAIL_SECTION_ROW_CAP = 5
# Redaction keys — applied recursively when serialising raw JSON sample blobs.
# Codex review of v4 §5 flagged Figure 1 parity as insufficient: internal API
# endpoints, evidence URLs, and selectors are a new exposure surface, so we
# replace any key whose name matches one of these with "[redacted]".
_REDACT_KEYS = {
    "url", "slug", "recommended_headers", "static_ok_request_headers",
    "captured_headers", "sample_url", "evidence_url", "url_template",
    "next_url", "request_url", "response_url", "selector", "css_selector",
    "xpath", "request_headers", "response_headers", "headers", "cookies",
    "set_cookie", "set-cookie", "cookie", "request_body", "request_body_text",
    "body_text", "body", "sample", "snippet", "html", "list_html.html",
    "article_sample.html", "source", "primary_feed_url", "first_article_url",
    "href_pattern_guess", "row_data_attrs", "inline_js_data_candidates",
    "clicked_resolved_url", "clicked_note", "body_path", "accept_lang",
    "user_agent", "authorization", "auth_token", "session", "prompt",
}


def _host_mask(value: object) -> str:
    """ADR 0010 §17 + codex review v4 §5 — emit host only, hide path/query.

    Returns "" for non-URL input. For URLs, returns the registered host plus
    a literal `/ path hidden` marker when the original had a path.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    host = hostname_from_url(s)
    if not host:
        # not a URL — fall back to short text without revealing original
        return _short_text(s, 60)
    host = host.lower()
    try:
        parsed = urlparse(s)
        has_path = bool(parsed.path and parsed.path not in ("", "/"))
    except ValueError:
        has_path = False
    return f"{host}{ ' / path hidden' if has_path else '' }"


def _redact_json(obj, depth: int = 0):
    """Recursively redact private fields before raw-JSON dumping.

    Keys in `_REDACT_KEYS` (case-insensitive) become `"[redacted]"`. Strings
    that look like URLs are host-masked. Depth cap of 8 prevents runaway
    recursion on cyclic-looking probe artifacts.
    """
    if depth > 8:
        return "[truncated]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in _REDACT_KEYS or any(kl.endswith("_" + t) for t in _REDACT_KEYS):
                out[k] = "[redacted]"
            else:
                out[k] = _redact_json(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_redact_json(x, depth + 1) for x in obj[:50]]
    if isinstance(obj, str):
        s = obj
        if _URL_RE.search(s):
            s = _URL_RE.sub(lambda m: _host_mask(m.group(0)) or "host masked", s)
        return s if len(s) <= 220 else s[:219] + "…"
    return obj


def _resp_content_type(resp: dict) -> str:
    for h in resp.get("headers") or []:
        if str(h.get("name") or "").lower() == "content-type":
            return str(h.get("value") or "")
    return str((resp.get("content") or {}).get("mimeType") or "")


def _har_load_safe(har_path: Path) -> dict:
    try:
        return json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def _har_kpi_summary(har_path: Path) -> dict:
    har = _har_load_safe(har_path)
    if not isinstance(har, dict):
        return {"entry_count": 0, "json_count": 0, "xhr_count": 0,
                "status_error_count": 0, "content_types": []}
    entries = (har.get("log") or {}).get("entries") or []
    cts: Counter[str] = Counter()
    json_count = 0
    xhr_count = 0
    status_error_count = 0
    for entry in entries:
        req = entry.get("request") or {}
        resp = entry.get("response") or {}
        rtype = str(entry.get("_resourceType")
                    or entry.get("resourceType")
                    or req.get("_resourceType") or "")
        if rtype in ("xhr", "fetch"):
            xhr_count += 1
        try:
            status = int(resp.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        if status >= 400:
            status_error_count += 1
        ct = _resp_content_type(resp)
        if ct:
            cts[ct.split(";", 1)[0].strip().lower()] += 1
        content = resp.get("content") or {}
        if "json" in (ct.lower() + " " + str(content.get("mimeType") or "").lower()):
            json_count += 1
    return {
        "entry_count": len(entries),
        "json_count": json_count,
        "xhr_count": xhr_count,
        "status_error_count": status_error_count,
        "content_types": cts.most_common(8),
    }


def _lazy_extract():
    """Local import of probe.extract — lazy because the module imports bs4
    + helpers we don't want to pay at site-generator startup. Codex v4 §3
    confirmed no global Playwright / DB side effects."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from probe.extract import (
            traffic_api_candidates,
            traffic_article_body_candidates,
            rss_feed_urls,
            pagination_hints,
            audio_share_signal,
        )
    except ImportError:
        return None
    return (
        traffic_api_candidates,
        traffic_article_body_candidates,
        rss_feed_urls,
        pagination_hints,
        audio_share_signal,
    )


def _manifest_for(run_dir: Path, slug: str) -> dict:
    """Codex review §2 — replace the v4 narrow cache key with a manifest
    over every direct input that can affect Figure 4 output."""
    items: list[tuple[str, int, int]] = []
    for name in _HAR_DETAIL_MANIFEST_FILES:
        p = run_dir / name
        if p.exists():
            try:
                st = p.stat()
                items.append((name, st.st_size, st.st_mtime_ns))
            except OSError:
                items.append((name, -1, -1))
    cfg = ROOT / "configs" / f"{slug}.json"
    if cfg.exists():
        try:
            st = cfg.stat()
            items.append(("__config__", st.st_size, st.st_mtime_ns))
        except OSError:
            items.append(("__config__", -1, -1))
    extract_path = ROOT / "probe" / "extract.py"
    for label, p in (
        ("__extract__", extract_path),
        ("__digest__", ROOT / "engine" / "digest.py"),
        ("__mdr_candidates__", ROOT / "engine" / "_mdr_candidates.py"),
        ("__hydration__", ROOT / "probe" / "hydration.py"),
        ("__paths__", ROOT / "probe" / "paths.py"),
    ):
        if p.exists():
            try:
                items.append((label, p.stat().st_size, p.stat().st_mtime_ns))
            except OSError:
                pass
    diag = load_json(run_dir / "diagnosis.json")
    for i, result in enumerate(diag.get("results") or []):
        body_path = result.get("body_path") if isinstance(result, dict) else None
        if not body_path:
            continue
        p = Path(str(body_path))
        if not p.is_absolute():
            p = run_dir / p
        if p.exists():
            try:
                st = p.stat()
                items.append((f"__diag_body_{i}__", st.st_size, st.st_mtime_ns))
            except OSError:
                pass
    return {"slug": slug, "items": items}


def pick_har_showcases(top_n: int = 5) -> list[tuple[str, Path]]:
    """Pick up to five probe runs for Figure 4."""
    pdir = ROOT / "output" / "probe"
    if not pdir.exists():
        return []

    recent_ok_urls: set[str] = set()
    bot_db = ROOT / "output" / "bot.sqlite3"
    if bot_db.exists():
        try:
            con = sqlite3.connect(str(bot_db))
            try:
                for row in con.execute(
                    "SELECT url FROM jobs WHERE result_rc = 0 AND finished_at IS NOT NULL"
                ):
                    u = str(row[0] or "")
                    if u:
                        recent_ok_urls.add(u)
            finally:
                con.close()
        except sqlite3.Error:
            pass

    previous_panel_slug = ""
    cached = load_json(_HAR_DETAIL_CACHE_PATH)
    if isinstance(cached, dict):
        panels = cached.get("panels") or []
        if panels and isinstance(panels[0], dict):
            previous_panel_slug = str((panels[0].get("manifest") or {}).get("slug") or "")

    eligible: list[tuple[int, int, int, str, Path]] = []
    for run_dir in pdir.iterdir():
        if not run_dir.is_dir():
            continue
        primary = run_dir / "traffic.har"
        if not primary.exists():
            others = sorted(run_dir.glob("traffic*.har"))
            primary = others[0] if others else None
        if primary is None:
            continue
        cfg_path = ROOT / "configs" / f"{run_dir.name}.json"
        if not cfg_path.exists():
            continue
        # Cheap eligibility floor.
        try:
            har = json.loads(primary.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = (har.get("log") or {}).get("entries") or []
        n_entries = len(entries)
        if n_entries < 50:
            continue
        # JSON-ish count in first 500 entries.
        json_n = 0
        for e in entries[:500]:
            mime = ((e.get("response") or {}).get("content") or {}).get("mimeType") or ""
            if "json" in mime.lower():
                json_n += 1
                if json_n >= 3:
                    break
        feed_cand = run_dir / "feed_candidates.json"
        has_feed = feed_cand.exists() and bool(load_json(feed_cand))
        if json_n < 3 and not has_feed:
            continue
        # Score (codex v4 §1).
        score = 3  # configs/<slug>.json exists (floor already enforced)
        if n_entries >= 50:
            score += 1
        if n_entries >= 200:
            score += 1
        if 50 <= n_entries <= 3000:
            score += 1
        if json_n >= 3:
            score += 2
        if has_feed:
            score += 1
        env_path = run_dir / "environment.json"
        if env_path.exists():
            env_data = load_json(env_path)
            src_url = str(env_data.get("url") or env_data.get("source_url") or "")
            if src_url and src_url in recent_ok_urls:
                score += 1
        # Tie-break primaries: entries band, json count.
        band_bonus = 1 if 50 <= n_entries <= 3000 else 0
        eligible.append((score, band_bonus, json_n, run_dir.name, primary))

    if not eligible:
        return []

    # Sticky: if previous slug still in eligible, prefer it as long as score
    # is within 1 of the current max.
    eligible.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]))
    top_score = eligible[0][0]
    if previous_panel_slug:
        for score, band, json_n, slug, primary in eligible:
            if slug == previous_panel_slug and top_score - score <= 1:
                eligible = [(score, band, json_n, slug, primary)] + [
                    item for item in eligible if item[3] != slug
                ]
                break
    return [(slug, primary) for _, _, _, slug, primary in eligible[:top_n]]


def _row_api(c: dict) -> dict:
    hits = c.get("list_hits") or []
    first = hits[0] if hits else {}
    keys = ", ".join(str(k) for k in (first.get("sample_keys") or [])[:6])
    return {
        "type": "api",
        "badge": "API",
        "badge_class": "sig-api",
        "host": _host_mask(c.get("url")),
        "meta": (
            f"score={c.get('relevance_score')} · "
            f"{c.get('method') or '?'} {c.get('status') or '?'} · "
            f"{c.get('resource_type') or '-'} · "
            f"{_short_text(c.get('content_type'), 60)}"
        ),
        "evidence": f"list_hits={len(hits)} · best_count={first.get('count') or 0} · keys={keys}",
    }


def _row_body(c: dict) -> dict:
    return {
        "type": "body",
        "badge": "BODY",
        "badge_class": "sig-body",
        "host": _host_mask(c.get("url")),
        "meta": (
            f"len={c.get('body_len') or 0} · "
            f"{c.get('method') or '?'} {c.get('status') or '?'} · "
            f"key={c.get('body_key') or '-'} · "
            f"path={_short_text(c.get('body_field_path'), 40)}"
        ),
        "evidence": "[sample redacted — see dashboard /probe-har for raw]",
    }


def _row_simple(c: dict, keys: list[str], signal_type: str, badge: str) -> dict:
    if not c:
        return {"type": signal_type, "badge": badge, "badge_class": f"sig-{signal_type}",
                "host": "", "meta": "", "evidence": ""}
    return {
        "type": signal_type,
        "badge": badge,
        "badge_class": f"sig-{signal_type}",
        "host": _host_mask(
            c.get("url") or c.get("sample_url") or c.get("url_template")
        ),
        "meta": " · ".join(
            f"{k}={_host_mask(c.get(k)) if 'url' in k else _short_text(c.get(k), 40)}"
            for k in keys
            if c.get(k) not in (None, "")
        ),
        "evidence": "[evidence URL host-masked]" if (c.get("evidence_url") or c.get("evidence")) else "",
    }


def _lazy_digest_build():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from engine.digest import build_digest
    except Exception:
        return None
    return build_digest


def _digest_signal_rows(*, slug: str, base_url: str, run_dir: Path) -> tuple[list[dict], object]:
    build_digest = _lazy_digest_build()
    if build_digest is None:
        return [], None
    try:
        digest = build_digest(slug=slug, url=base_url, probe_dir=run_dir)
    except Exception:
        return [], None
    rows: list[dict] = []
    site_kind = digest.get("site_kind") or {}
    primary_feed = _host_mask(site_kind.get("primary_feed_url"))
    if primary_feed:
        rows.append({
            "type": "digest",
            "badge": "DIGEST",
            "badge_class": "sig-digest",
            "host": primary_feed,
            "meta": "site_kind/primary_feed",
            "evidence": "primary feed host",
        })
    for key, label in (("list_html", "list_html/source"),
                       ("article_sample", "article_sample/source")):
        item = digest.get(key) or {}
        source = item.get("source")
        if source:
            rows.append({
                "type": "digest",
                "badge": "DIGEST",
                "badge_class": "sig-digest",
                "host": "—",
                "meta": label,
                "evidence": _short_text(source, 90),
            })
    list_cands = digest.get("list_candidates") or {}
    api_n = len(list_cands.get("traffic_json_api_candidates") or [])
    rss_n = len(digest.get("feed_candidates") or [])
    pag_n = len(list_cands.get("pagination_hints") or [])
    rows.append({
        "type": "digest",
        "badge": "DIGEST",
        "badge_class": "sig-digest",
        "host": "—",
        "meta": f"api={api_n} rss={rss_n} pag={pag_n}",
        "evidence": "signal counts",
    })
    notes = digest.get("notes") or []
    if notes:
        rows.append({
            "type": "digest",
            "badge": "DIGEST",
            "badge_class": "sig-digest",
            "host": "—",
            "meta": "recommendation",
            "evidence": _redact_public_text(_short_text(notes[0], 160)),
        })
    return rows[:_HAR_DETAIL_SECTION_ROW_CAP], _redact_json({
        "site_kind": digest.get("site_kind"),
        "list_html": digest.get("list_html"),
        "article_sample": digest.get("article_sample"),
        "list_candidates": digest.get("list_candidates"),
        "feed_candidates": digest.get("feed_candidates"),
    })


def build_har_detail(slug: str, har_path: Path) -> dict:
    """Mirror dashboard `har_view.build_har_detail` for one probe run with
    public-site privacy filters applied (host-masked URLs, redacted raw
    JSON, capped row counts). The `digest` artifact section is deferred
    here because it requires `engine.digest.build_digest` which we keep
    out of the static generator dependency surface."""
    run_dir = har_path.parent
    diagnosis = load_json(run_dir / "diagnosis.json")
    list_candidates = load_json(run_dir / "list_candidates.json")
    base_url = str(diagnosis.get("url") or "")
    first_article_url = str(list_candidates.get("first_article_url") or "")

    page_html = ""
    list_html_path = run_dir / "list.html"
    if list_html_path.exists():
        try:
            page_html = list_html_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            page_html = ""

    fns = _lazy_extract()
    raw_api: list = []
    raw_body: list = []
    feeds: list = []
    page_hints: list = []
    audio = None
    if fns is not None:
        api_fn, body_fn, rss_fn, pag_fn, audio_fn = fns
        try:
            raw_api = list(api_fn(har_path, page_url=base_url) or [])
        except Exception:
            raw_api = []
        try:
            raw_body = list(body_fn(har_path, article_url=first_article_url) or [])
        except Exception:
            raw_body = []
        if base_url and page_html:
            try:
                feeds = list(rss_fn(html=page_html, base_url=base_url, har_path=har_path) or [])
            except Exception:
                feeds = []
            try:
                page_hints = list(pag_fn(html=page_html, base_url=base_url, har_path=har_path) or [])
            except Exception:
                page_hints = []
            try:
                html_candidates = list_candidates.get("html_repeating_patterns") or []
                if not isinstance(html_candidates, list):
                    html_candidates = []
                audio = audio_fn(
                    base_url=base_url,
                    first_article_url=first_article_url or None,
                    html_candidates=html_candidates,
                    feeds=feeds,
                    har_path=har_path,
                )
            except Exception:
                audio = None

    summary = _har_kpi_summary(har_path)
    try:
        mtime = datetime.fromtimestamp(har_path.stat().st_mtime, tz=KST).isoformat(timespec="seconds")
    except OSError:
        mtime = ""

    config_strategy = ""
    cfg_path = ROOT / "configs" / f"{slug}.json"
    if cfg_path.exists():
        config_strategy = str(load_json(cfg_path).get("strategy") or "")

    def _section(key: str, title: str, source: str, raw: list, row_fn) -> dict:
        rows = [row_fn(c) for c in raw]
        visible = rows[: _HAR_DETAIL_SECTION_ROW_CAP]
        return {
            "key": key,
            "title": title,
            "source": source,
            "rows": visible,
            "total_rows": len(rows),
            "more": max(0, len(rows) - len(visible)),
            "raw_redacted": _redact_json(raw),
        }

    audio_section = {
        "key": "audio_share_signal",
        "title": "Audio share / player signal",
        "source": "probe.extract.audio_share_signal(...)",
        "rows": ([_row_simple(audio, ["host", "base_host", "confidence", "evidence", "sample_url"], "audio", "AUDIO")]
                 if audio else []),
        "total_rows": 1 if audio else 0,
        "more": 0,
        "raw_redacted": _redact_json(audio) if audio else None,
    }

    sections = [
        _section("traffic_api_candidates", "List JSON API candidates",
                 "probe.extract.traffic_api_candidates(har, page_url)", raw_api, _row_api),
        _section("traffic_article_body_candidates", "Article body JSON candidates",
                 "probe.extract.traffic_article_body_candidates(har, article_url)", raw_body, _row_body),
        _section("rss_feed_urls", "RSS / Atom candidates",
                 "probe.extract.rss_feed_urls(html, base_url, har)", feeds,
                 lambda c: _row_simple(c, ["url", "source", "type"], "rss", "RSS")),
        _section("pagination_hints", "Pagination candidates",
                 "probe.extract.pagination_hints(html, base_url, har)", page_hints,
                 lambda c: _row_simple(c, ["kind", "param", "source", "url_template", "evidence_url"], "pag", "PAG")),
        audio_section,
    ]
    digest_rows, digest_raw = _digest_signal_rows(slug=slug, base_url=base_url, run_dir=run_dir)
    sections.append({
        "key": "digest",
        "title": "Digest allow-list summary",
        "source": "engine.digest.build_digest(...)",
        "rows": digest_rows,
        "total_rows": len(digest_rows),
        "more": 0,
        "raw_redacted": digest_raw,
    })

    artifact_rows = []
    if isinstance(list_candidates, dict):
        for key in sorted(list_candidates.keys()):
            value = list_candidates[key]
            artifact_rows.append({
                "key": key,
                "kind": type(value).__name__ if value is not None else "null",
                "count": (str(len(value)) if isinstance(value, (list, dict, str)) else ""),
                "preview": "[redacted]" if isinstance(value, (dict, list, str)) and str(key).lower() in _REDACT_KEYS
                           else _short_text(json.dumps(_redact_json(value), ensure_ascii=False), 180),
            })

    return {
        "slug": slug,
        "host_label": _short_host(base_url) or "host masked",
        "har_name": har_path.name,
        "har_mtime": mtime,
        "probe_host": _host_mask(base_url),
        "article_host": _host_mask(first_article_url),
        "verdict": str(diagnosis.get("verdict") or ""),
        "config_strategy": config_strategy,
        "summary": summary,
        "sections": sections,
        "artifact_list_candidates": {
            "title": "Stored probe summary (list_candidates.json)",
            "source": "list_candidates.json",
            "rows": artifact_rows,
        },
    }


def read_har_details(*, force_recompute: bool = False) -> dict:
    """Build or read the up-to-five Figure 4 panel payload."""
    picks = pick_har_showcases(top_n=5)
    if not picks:
        return {"computed_at": datetime.now(KST).isoformat(), "panels": []}
    manifests = [_manifest_for(har_path.parent, slug) for slug, har_path in picks]
    cached = load_json(_HAR_DETAIL_CACHE_PATH)
    if (
        not force_recompute
        and isinstance(cached, dict)
        and [p.get("manifest") for p in (cached.get("panels") or [])] == manifests
    ):
        return cached
    panels = []
    for i, ((slug, har_path), manifest) in enumerate(zip(picks, manifests)):
        detail = build_har_detail(slug, har_path)
        panels.append({
            "panel_id": f"har-panel-{i}",
            "host_label": detail.get("host_label") or "host masked",
            "manifest": manifest,
            "detail": detail,
        })
    payload = {
        "computed_at": datetime.now(KST).isoformat(),
        "panels": panels,
    }
    try:
        _HAR_DETAIL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HAR_DETAIL_CACHE_PATH.with_suffix(_HAR_DETAIL_CACHE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, _HAR_DETAIL_CACHE_PATH)
    except OSError:
        pass
    return payload


def _placeholder_har_panel() -> dict:
    return {
        "panel_id": "har-panel-0",
        "host_label": "No probe artifact",
        "detail": {
            "host_label": "No probe artifact",
            "har_name": "—",
            "har_mtime": "",
            "verdict": "—",
            "config_strategy": "—",
            "probe_host": "—",
            "article_host": "—",
            "summary": {"entry_count": 0, "json_count": 0, "xhr_count": 0,
                        "status_error_count": 0, "content_types": []},
            "sections": [],
        },
    }


def render_har_detail_html(payload: dict | None) -> str:
    panels = (payload or {}).get("panels") or []
    if not panels:
        panels = [_placeholder_har_panel()]
    options = "".join(
        f'<option value="{esc(panel["panel_id"])}">{esc(panel["host_label"])}</option>'
        for panel in panels
    )
    panel_html = "".join(
        _render_har_detail_panel(panel, hidden=i != 0)
        for i, panel in enumerate(panels)
    )
    return (
        '<label class="har-picker">Probe host '
        f'<select id="harSlugPicker">{options}</select></label>'
        f"{panel_html}"
    )


def _render_har_detail_panel(panel: dict, *, hidden: bool) -> str:
    detail = panel["detail"]
    s = detail["summary"]
    kpis = (
        '<div class="har-kpis">'
        f'<div class="kpi"><div class="kpi-label">entries</div>'
        f'<div class="kpi-value">{esc(s["entry_count"])}</div></div>'
        f'<div class="kpi"><div class="kpi-label">JSON-ish</div>'
        f'<div class="kpi-value">{esc(s["json_count"])}</div></div>'
        f'<div class="kpi"><div class="kpi-label">xhr/fetch</div>'
        f'<div class="kpi-value">{esc(s["xhr_count"])}</div></div>'
        f'<div class="kpi"><div class="kpi-label">HTTP 4xx/5xx</div>'
        f'<div class="kpi-value">{esc(s["status_error_count"])}</div></div>'
        "</div>"
    )

    meta_dl = (
        '<dl class="har-meta">'
        f"<dt>HAR mtime</dt><dd><code>{esc(detail['har_mtime'] or '—')}</code></dd>"
        f"<dt>verdict</dt><dd>{esc(detail['verdict'] or '—')}</dd>"
        f"<dt>config strategy</dt><dd><code>{esc(detail['config_strategy'] or '—')}</code></dd>"
        f"<dt>host</dt><dd><code>{esc(detail['host_label'] or 'host masked')}</code></dd>"
        "</dl>"
        '<details class="har-meta-extra">'
        '<summary>more</summary>'
        '<dl class="har-meta">'
        f"<dt>probe host</dt><dd><code>{esc(detail['probe_host'] or '—')}</code></dd>"
        f"<dt>first article host</dt><dd><code>{esc(detail['article_host'] or '—')}</code></dd>"
        "</dl></details>"
    )

    cts = s.get("content_types") or []
    if cts:
        ct_rows = "".join(
            f"<tr><td><code>{esc(ct)}</code></td><td>{esc(n)}</td></tr>"
            for ct, n in cts
        )
        ct_block = (
            '<details class="har-fold">'
            "<summary><strong>content-type distribution</strong></summary>"
            '<table class="compact">'
            "<thead><tr><th>content-type</th><th>count</th></tr></thead>"
            f"<tbody>{ct_rows}</tbody></table>"
            "</details>"
        )
    else:
        ct_block = ""

    signal_rows: list[dict] = []
    raw_dump: dict[str, object] = {}
    for sec in detail.get("sections") or []:
        raw_dump[sec["key"]] = sec.get("raw_redacted")
        signal_rows.extend(sec.get("rows") or [])
        if sec.get("more"):
            signal_rows.append({
                "badge": "MORE",
                "badge_class": "sig-empty",
                "host": "—",
                "meta": sec["title"],
                "evidence": f"+{sec['more']} more rows not shown",
            })
    present = {r.get("type") for r in signal_rows}
    for signal_type, badge in (
        ("api", "API"), ("body", "BODY"), ("rss", "RSS"),
        ("pag", "PAG"), ("audio", "AUDIO"),
    ):
        if signal_type not in present:
            signal_rows.append({
                "type": signal_type,
                "badge": badge,
                "badge_class": f"sig-{signal_type} sig-empty",
                "host": "—",
                "meta": "Not detected for this probe.",
                "evidence": "—",
            })
    if "digest" not in present:
        signal_rows.append({
            "type": "digest",
            "badge": "DIGEST",
            "badge_class": "sig-digest sig-empty",
            "host": "—",
            "meta": "Not detected for this probe.",
            "evidence": "—",
        })
    body = (
        '<table class="har-signals">'
        "<thead><tr><th>signal type</th><th>host</th>"
        "<th>meta</th><th>evidence</th></tr></thead><tbody>"
    )
    for item in signal_rows:
        empty_cls = ' class="sig-empty"' if "sig-empty" in str(item.get("badge_class")) else ""
        body += (
            f"<tr{empty_cls}>"
            f'<td><span class="sig-badge {esc(item["badge_class"])}">{esc(item["badge"])}</span></td>'
            f'<td class="mono">{esc(item.get("host") or "—")}</td>'
            f"<td><small>{esc(item.get('meta') or '')}</small></td>"
            f"<td><small class=\"muted\">{esc(item.get('evidence') or '')}</small></td>"
            "</tr>"
        )
    body += "</tbody></table>"
    raw_pre = json.dumps(raw_dump, ensure_ascii=False, indent=2) if raw_dump else "(empty)"
    raw_block = (
        '<details class="har-fold">'
        "<summary>raw signals (redacted)</summary>"
        f'<pre class="tail">{esc(raw_pre)}</pre>'
        "</details>"
    )
    hidden_attr = " hidden" if hidden else ""
    return (
        f'<div class="har-detail-panel" id="{esc(panel["panel_id"])}"{hidden_attr}>'
        f"{kpis}{meta_dl}{ct_block}{body}{raw_block}</div>"
    )


def metric(label: str, value: object, note: str = "") -> str:
    note_html = f"<span>{esc(note)}</span>" if note else ""
    return f'<div class="metric"><strong>{esc(value)}</strong><em>{esc(label)}</em>{note_html}</div>'


def render_html(
    configs: dict,
    poll: dict,
    jobs: dict,
    generated_at: datetime,
    *,
    case_records: list[dict] | None = None,
    har_detail: dict | None = None,
) -> str:
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

    case_records = case_records or []
    timeline_svg = svg_case_blocks(case_records, EVENT_ANNOTATIONS)
    case_db_html = render_case_db(case_records)
    bucket_counts = Counter(r["bucket"] for r in case_records)
    timeline_legend_html = "".join(
        f'<li><button type="button" class="legend-toggle" data-bucket="{esc(b)}" '
        f'aria-pressed="true">'
        f'<span class="swatch" style="background:{BUCKET_COLORS[b]}"></span>'
        f"{esc(BUCKET_LABELS[b])}"
        f'<b>{esc(bucket_counts.get(b, 0))}</b>'
        f"</button></li>"
        for b in reversed(BUCKET_ORDER)
    ) or '<li><button type="button" class="legend-toggle" disabled>No case history</button></li>'

    har_funnel_svg = svg_har_funnel()
    har_stage_panels_html = render_stage_panels()
    har_detail_html = render_har_detail_html(har_detail)

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
    .panel-title {{
      fill: var(--ink);
      font: 600 13px Georgia, "Times New Roman", serif;
      letter-spacing: 0.02em;
    }}
    .panel-sub {{
      fill: var(--muted);
      font: 11.5px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .axis-grid {{ stroke: var(--line); stroke-width: 0.6; stroke-dasharray: 2 4; opacity: 0.6; }}
    .axis-tick {{ fill: var(--muted); font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .engine-baseline {{ stroke: var(--ink); stroke-width: 1.4; opacity: 0.85; }}
    .case-block {{ cursor: pointer; opacity: 0.92; transition: transform 80ms ease, opacity 80ms ease; stroke: rgba(31,37,40,0.0); stroke-width: 0.6; }}
    .case-block:hover, .case-block:focus {{ opacity: 1; transform: translateY(-1px); outline: none; }}
    .case-block.outcome-improved {{ stroke: rgba(31,37,40,0.85); stroke-width: 0.8; }}
    .case-block.outcome-rejected {{ opacity: 0.55; }}
    .bucket-F {{ fill: #3d737f; }}
    .bucket-C {{ fill: #8a6f4d; }}
    .bucket-A {{ fill: #7b5c8c; }}
    .bucket-B-D-E {{ fill: #6f7f52; }}
    .bucket-no-change {{ fill: #c8c0ad; }}
    .modal {{
      position: fixed;
      inset: 0;
      z-index: 60;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .modal[hidden] {{ display: none; }}
    .modal-backdrop {{
      position: absolute;
      inset: 0;
      background: rgba(15, 18, 20, 0.55);
    }}
    .modal-inner {{
      position: relative;
      max-width: 640px;
      width: calc(100% - 32px);
      max-height: 80vh;
      overflow-y: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 22px 24px 18px;
      box-shadow: 0 12px 40px rgba(15, 18, 20, 0.3);
      border-radius: 4px;
    }}
    .modal-close {{
      position: absolute;
      top: 10px;
      right: 14px;
      background: none;
      border: none;
      font-size: 1.8rem;
      line-height: 1;
      color: var(--muted);
      cursor: pointer;
    }}
    .modal-close:hover {{ color: var(--ink); }}
    .modal-meta {{
      color: var(--muted);
      font-size: 0.84rem;
      margin: 0 0 6px;
    }}
    .modal-title {{
      font-family: Georgia, "Times New Roman", serif;
      margin: 0 0 14px;
      font-size: 1.2rem;
      line-height: 1.35;
    }}
    .modal-body {{
      color: var(--ink);
      font-size: 0.97rem;
      line-height: 1.55;
      margin: 0 0 14px;
    }}
    .modal-link a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    .modal-link a:hover {{ text-decoration: underline; }}
    .annot-line {{ stroke: #1f2528; stroke-width: 1; stroke-dasharray: 3 3; opacity: 0.55; }}
    .annot:hover .annot-line {{ opacity: 1; }}
    .annot-marker {{
      fill: var(--ink);
      font: 600 10.5px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0.02em;
    }}
    .timeline-legend {{ gap: 4px 12px; }}
    .timeline-legend .legend-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      background: none;
      border: 1px solid transparent;
      padding: 3px 8px;
      border-radius: 12px;
      color: var(--muted);
      font: inherit;
      font-size: 0.86rem;
      cursor: pointer;
      transition: background 80ms, border-color 80ms, opacity 80ms;
    }}
    .timeline-legend .legend-toggle:hover {{ background: var(--paper); border-color: var(--line); }}
    .timeline-legend .legend-toggle:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 1px;
    }}
    .timeline-legend .legend-off {{ opacity: 0.42; text-decoration: line-through; }}
    .timeline-legend b {{ color: var(--ink); margin-left: 4px; }}
    .funnel-stage {{ cursor: pointer; color: var(--accent-2); }}
    .funnel-stage:focus {{ outline: none; }}
    .funnel-stage:focus-visible .funnel-box {{
      outline: 2px solid var(--accent);
      outline-offset: 3px;
    }}
    .funnel-box {{ fill: var(--panel); stroke: var(--accent); stroke-width: 1.2; transition: fill 100ms, stroke-width 100ms; }}
    .funnel-stage:hover .funnel-box {{ fill: #eaf1f2; }}
    .funnel-stage.active .funnel-box {{ fill: #d6e6e9; stroke-width: 2.4; }}
    .funnel-step {{ fill: var(--muted); font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing: 0.08em; text-transform: uppercase; }}
    .funnel-label {{ fill: var(--ink); font: 600 15px Georgia, "Times New Roman", serif; }}
    .funnel-tagline {{ fill: var(--muted); font: italic 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .funnel-arrow {{ stroke: var(--accent-2); stroke-width: 1.8; color: var(--accent-2); }}
    /* Scoped section-gap tokens (codex v4 review §8 — global selector over-fires). */
    main > section + section {{ margin-top: var(--section-gap, 36px); }}
    #figures figure + figure {{ margin-top: var(--subsection-gap, 22px); }}
    #harDetailFigure {{ margin-top: var(--section-gap, 36px); }}
    #harDetailFigure .har-section + .har-section {{ margin-top: var(--subsection-gap, 22px); }}

    .stage-panels {{ margin: 18px 0 6px; }}
    .stage-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px 18px 14px;
      margin: 0 0 14px;
    }}
    .stage-panel-head {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin: 0 0 12px; }}
    .stage-panel-head h3 {{ margin: 0; font-family: Georgia, "Times New Roman", serif; font-size: 1.15rem; }}
    .stage-panel-num {{
      display: inline-block;
      padding: 2px 9px;
      background: var(--paper);
      border-radius: 10px;
      color: var(--accent);
      font: 600 0.76rem -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .stage-panel-summary {{ flex-basis: 100%; margin: 4px 0 0; color: var(--muted); font-size: 0.94rem; }}
    /* Figure 3 stage rail. */
    .stage-flow {{
      border-left: 1px solid var(--line);
      padding: 0 0 0 18px;
      margin: 0;
      list-style: none;
    }}
    .step-row {{
      display: flex;
      gap: 12px;
      margin: 0 0 14px;
    }}
    .step-num {{
      width: 24px;
      height: 24px;
      margin-left: -31px;
      border-radius: 50%;
      background: var(--panel);
      border: 1px solid var(--accent);
      text-align: center;
      line-height: 22px;
      font: 700 0.9rem Georgia, "Times New Roman", serif;
      color: var(--accent);
      flex: 0 0 24px;
    }}
    .step-body {{
      min-width: 0;
      flex: 1;
    }}
    .step-file {{
      display: inline;
      font: 600 0.82rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--ink);
      word-break: break-all;
      overflow-wrap: anywhere;
    }}
    .step-sep {{ color: var(--muted); margin: 0 6px; }}
    .step-fn {{
      display: inline;
      font: 0.78rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--accent);
      word-break: break-all;
      overflow-wrap: anywhere;
    }}
    .step-role {{
      margin: 4px 0 0;
      font-size: 0.8rem;
      color: var(--muted);
      line-height: 1.4;
    }}
    /* Figure 4 — live HAR detail */
    #harDetailFigure {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 18px 22px 14px;
      margin-left: 0;
      margin-right: 0;
    }}
    #harDetailFigure > h3 {{
      margin: 0 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.2rem;
    }}
    #harDetailFigure figcaption {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.55;
    }}
    .har-kpis {{
      display: flex;
      flex-wrap: nowrap;
      gap: 10px;
      margin: 0 0 16px;
      overflow-x: auto;
    }}
    .har-kpis .kpi {{
      flex: 1 0 120px;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 10px 12px;
      text-align: center;
    }}
    .har-kpis .kpi-label {{
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .har-kpis .kpi-value {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.6rem;
      color: var(--ink);
      margin-top: 4px;
    }}
    .har-meta {{
      display: flex;
      gap: 1rem;
      flex-wrap: nowrap;
      overflow-x: auto;
      margin: 0 0 18px;
      font-size: 0.9rem;
    }}
    .har-meta dt {{ color: var(--muted); text-transform: uppercase; font-size: 0.74rem; letter-spacing: 0.08em; padding-top: 4px; }}
    .har-meta dd {{ margin: 0; word-break: break-all; }}
    .har-picker {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .har-picker select {{
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--ink);
      padding: 5px 8px;
      border-radius: 4px;
    }}
    .har-detail-panel {{ margin-top: 4px; }}
    .har-meta-extra {{ margin: -10px 0 16px; }}
    .har-section {{
      border-top: 1px solid var(--line);
      padding-top: 14px;
    }}
    .har-section-head {{
      display: flex;
      align-items: baseline;
      gap: 12px;
      flex-wrap: wrap;
      margin: 0 0 10px;
    }}
    .har-section-head h4 {{ margin: 0; font-family: Georgia, "Times New Roman", serif; font-size: 1rem; }}
    .har-section-head code {{
      font-size: 0.78rem;
    }}
    .har-section-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }}
    .har-section-table th {{
      text-align: left;
      color: var(--muted);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
    }}
    .har-section-table td {{ padding: 6px 8px; vertical-align: top; border-bottom: 1px solid var(--line); }}
    .har-section-table td.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break: break-all; }}
    .har-signals {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }}
    .har-signals th {{
      text-align: left;
      color: var(--muted);
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
    }}
    .har-signals td {{ padding: 6px 8px; vertical-align: top; border-bottom: 1px solid var(--line); }}
    .har-signals td.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; word-break: break-all; }}
    .badge {{
      display: inline-block;
      padding: 1px 7px;
      border-radius: 10px;
      background: var(--paper);
      border: 1px solid var(--line);
      font-size: 0.74rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--ink);
    }}
    .sig-badge {{
      display: inline-block;
      padding: 1px 7px;
      border-radius: 10px;
      border: 1px solid var(--line);
      font-size: 0.74rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--ink);
      background: var(--paper);
    }}
    .sig-api {{ border-color: #3d737f; }}
    .sig-body {{ border-color: #8a6f4d; }}
    .sig-rss {{ border-color: #6f7f52; }}
    .sig-pag {{ border-color: #7b5c8c; }}
    .sig-audio {{ border-color: #9b6b6b; }}
    .sig-digest {{ border-color: #1f2528; }}
    .sig-empty {{ color: var(--muted); opacity: 0.78; }}
    .har-fold {{ margin: 8px 0 0; }}
    .har-fold summary {{
      cursor: pointer;
      font-size: 0.86rem;
      color: var(--muted);
    }}
    .har-fold[open] summary {{ color: var(--ink); }}
    .har-fold pre {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 8px 10px;
      margin: 6px 0 0;
      max-height: 320px;
      overflow: auto;
      font-size: 0.78rem;
      line-height: 1.5;
    }}
    .har-section-more {{ margin: 6px 0 0; font-size: 0.78rem; }}
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
        same fetch method and see the domain.</figcaption>
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
          tip.innerHTML = '<b>' + domain + '</b>'
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
    <figure>
      {timeline_svg}
      <ul class="legend timeline-legend">{timeline_legend_html}</ul>
      <div id="timelineTip" class="dot-tip" hidden></div>
      <figcaption><strong>Figure 2.</strong> Every time the auto-solver fails on a new
        site, a human reads through what happened and writes a short note in
        <code>docs/cases/</code>. One block per note, stacked on the day it landed. The thick
        baseline is "the engine that runs today"; each block above it is a piece of evidence that
        the engine wasn't enough on its own that day. <strong>Tall columns</strong> are batch runs
        (05-21 = 5 site batches in parallel = 118 notes). <strong>Colour</strong> marks the layer
        that needed touching —
        <span style="color:#3d737f">F</span> recognizer / platform code,
        <span style="color:#8a6f4d">C</span> probe heuristic,
        <span style="color:#7b5c8c">A</span> prompt / agentic,
        <span style="color:#6f7f52">B/D/E</span> engine / writer / validate, or
        <span style="color:#888">no-change</span> (we wrote a note but no code moved).
        <strong>Solid borders</strong> mark the cases that became <em>improvements</em> — patterns
        the solver now handles on its own next time. Dashed verticals are infra milestones
        (hover for what shipped). <strong>Click any block</strong> to read its note inline, or
        open its redacted note inline.</figcaption>
    </figure>
    {case_db_html}
    <div id="caseModal" class="modal" hidden role="dialog" aria-labelledby="caseModalTitle" aria-modal="true">
      <div class="modal-backdrop" data-close="1"></div>
      <div class="modal-inner">
        <button type="button" class="modal-close" aria-label="Close" data-close="1">×</button>
        <p class="modal-meta" id="caseModalMeta"></p>
        <h3 class="modal-title" id="caseModalTitle"></h3>
        <p class="modal-body" id="caseModalBody"></p>
      </div>
    </div>
    <script>
      (function () {{
        var svg = document.getElementById('caseTimeline');
        var tip = document.getElementById('timelineTip');
        var modal = document.getElementById('caseModal');
        if (!svg) return;
        var blocksByBucket = {{}};
        svg.querySelectorAll('.case-block').forEach(function (b) {{
          var bk = b.getAttribute('data-bucket');
          if (!bk) return;
          (blocksByBucket[bk] = blocksByBucket[bk] || []).push(b);
        }});
        function showTip(html, e) {{
          if (!tip) return;
          tip.innerHTML = html;
          tip.hidden = false;
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }}
        function hideTip() {{ if (tip) tip.hidden = true; }}
        function recordFor(caseId) {{
          return document.querySelector('#caseDB .case-record[data-case-id="' + caseId.replace(/"/g, '\\\\"') + '"]');
        }}
        function openCase(caseId) {{
          var rec = recordFor(caseId);
          if (!rec || !modal) return;
          var status = rec.getAttribute('data-status') || caseId;
          var date = rec.getAttribute('data-date') || '';
          var bucket = rec.getAttribute('data-bucket') || '';
          var outcome = rec.getAttribute('data-outcome') || '';
          var fix = rec.getAttribute('data-fix-layer') || '';
          var host = rec.getAttribute('data-host') || 'host masked';
          document.getElementById('caseModalTitle').textContent = status;
          document.getElementById('caseModalMeta').textContent =
            date + ' · ' + host + ' · ' + bucket + ' · outcome: ' + (outcome || '—') +
            (fix ? ' · fix_layer: ' + fix : '');
          document.getElementById('caseModalBody').textContent = rec.textContent || '(no body excerpt)';
          modal.hidden = false;
        }}
        function closeModal() {{ if (modal) modal.hidden = true; }}
        svg.addEventListener('mousemove', function (e) {{
          if (!tip || tip.hidden) return;
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }});
        svg.addEventListener('mouseover', function (e) {{
          var block = e.target.closest ? e.target.closest('.case-block') : null;
          if (block) {{
            var caseId = block.getAttribute('data-case-id') || '';
            var bucket = block.getAttribute('data-bucket') || '';
            showTip('<b>' + caseId + '</b><span>' + bucket + ' · click to open</span>', e);
            return;
          }}
          var annot = e.target.closest ? e.target.closest('.annot') : null;
          if (annot) {{
            var d = annot.getAttribute('data-date') || '';
            var full = annot.getAttribute('data-full') || '';
            showTip('<b>' + d + '</b><span>' + full + '</span>', e);
            return;
          }}
          hideTip();
        }});
        svg.addEventListener('mouseleave', hideTip);
        svg.addEventListener('click', function (e) {{
          var block = e.target.closest ? e.target.closest('.case-block') : null;
          if (block) {{
            openCase(block.getAttribute('data-case-id') || '');
          }}
        }});
        svg.addEventListener('keydown', function (e) {{
          if (e.key !== 'Enter' && e.key !== ' ') return;
          var block = e.target.closest ? e.target.closest('.case-block') : null;
          if (block) {{
            e.preventDefault();
            openCase(block.getAttribute('data-case-id') || '');
          }}
        }});
        if (modal) {{
          modal.addEventListener('click', function (e) {{
            if (e.target && e.target.getAttribute && e.target.getAttribute('data-close') === '1') {{
              closeModal();
            }}
          }});
          document.addEventListener('keydown', function (e) {{
            if (e.key === 'Escape' && !modal.hidden) closeModal();
          }});
        }}
        document.querySelectorAll('.timeline-legend .legend-toggle').forEach(function (btn) {{
          btn.addEventListener('click', function () {{
            var bk = btn.getAttribute('data-bucket');
            var visible = btn.getAttribute('aria-pressed') !== 'false';
            var next = !visible;
            btn.setAttribute('aria-pressed', next ? 'true' : 'false');
            btn.classList.toggle('legend-off', !next);
            (blocksByBucket[bk] || []).forEach(function (b) {{
              b.style.display = next ? '' : 'none';
            }});
          }});
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

  <section aria-labelledby="har">
    <h2 id="har">How the probe reads a site (HAR)</h2>
    <p class="lead">When a new URL is offered, probe runs in five stages. The funnel below
      shows the order — <strong>click any stage</strong> (or focus + Enter / Space) to see which
      files in this repo actually execute during that stage and in what order.</p>
    <figure id="harPipeline">
      {har_funnel_svg}
      <figcaption>Figure 3. Probe pipeline — click any stage to see the files executed in
        that stage. The detail expands inside the same panel below.</figcaption>
    </figure>
    <div class="stage-panels" id="harStagePanels">
      {har_stage_panels_html}
    </div>
    <figure id="harDetailFigure">
      <h3>Figure 4. Live HAR analysis for one auto-selected probe</h3>
      {har_detail_html}
      <figcaption>Auto-selected each cycle (score-based; sticky to the previous slug when it
        still qualifies) from <code>output/probe/&lt;slug&gt;/</code>. Same shape as the dev
        dashboard's <code>/probe-har</code> view, but URLs are host-masked, raw JSON is
        redacted, and each section caps at 5 visible rows (ADR 0010 §17).</figcaption>
    </figure>
    <script>
      (function () {{
        var funnel = document.getElementById('harFunnel');
        var panels = document.getElementById('harStagePanels');
        if (funnel && panels) {{
          function setActive(stageId) {{
            funnel.querySelectorAll('.funnel-stage').forEach(function (g) {{
              var match = g.getAttribute('data-stage-id') === stageId;
              g.classList.toggle('active', match);
              g.setAttribute('aria-expanded', match ? 'true' : 'false');
            }});
            panels.querySelectorAll('.stage-panel').forEach(function (p) {{
              var match = p.getAttribute('data-stage-id') === stageId;
              p.hidden = !match;
            }});
          }}
          funnel.addEventListener('click', function (e) {{
            var g = e.target.closest ? e.target.closest('.funnel-stage') : null;
            if (!g) return;
            setActive(g.getAttribute('data-stage-id') || '');
          }});
          funnel.addEventListener('keydown', function (e) {{
            if (e.key !== 'Enter' && e.key !== ' ') return;
            var g = e.target.closest ? e.target.closest('.funnel-stage') : null;
            if (!g) return;
            e.preventDefault();
            setActive(g.getAttribute('data-stage-id') || '');
          }});
        }}
        var picker = document.getElementById('harSlugPicker');
        var detailPanels = document.querySelectorAll('.har-detail-panel');
        if (picker && detailPanels.length) {{
          picker.addEventListener('change', function () {{
            var targetId = picker.value;
            detailPanels.forEach(function (el) {{
              el.hidden = el.id !== targetId;
            }});
          }});
        }}
      }})();
    </script>
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

    t0 = time.monotonic()
    configs = read_configs()
    poll = read_poll_state()
    jobs = read_jobs()
    case_records = read_case_records()
    har_detail = read_har_details()
    generated_at = datetime.now(KST)
    page = render_html(
        configs,
        poll,
        jobs,
        generated_at,
        case_records=case_records,
        har_detail=har_detail,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(page, encoding="utf-8")
    os.replace(tmp_path, out_path)

    elapsed = time.monotonic() - t0
    print(
        "[generate_site] wrote "
        f"{out_path} ({len(configs['items'])} configs, {poll['total']} polling, "
        f"{len(jobs['recent'])} recent jobs, "
        f"{len(case_records)} cases, "
        f"{len((har_detail or {}).get('panels') or [])} HAR panels) "
        f"elapsed={elapsed:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
