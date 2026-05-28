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

# Bump when funnel/extraction logic changes — invalidates cached HAR aggregate.
EXTRACTOR_VERSION = "v1-2026-05-28"

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
    width = 920
    height = 840
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
        f'<svg id="siteScatter" xmlns:xlink="http://www.w3.org/1999/xlink" '
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


GITHUB_CASES_BASE = "https://github.com/poisonous60/notice-watcher/blob/main/docs/cases/"
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
                f'data-slug="{esc(rec["slug"])}" '
                f'data-bucket="{esc(bucket)}" '
                f'tabindex="0" role="button" '
                f'aria-label="{esc(rec["date"])} · {esc(rec["slug"])} · {esc(bucket)}"></rect>'
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
    for rec in records:
        gh_url = GITHUB_CASES_BASE + rec["filename"]
        parts.append(
            f'<div class="case-record" data-slug="{esc(rec["slug"])}" '
            f'data-date="{esc(rec["date"])}" '
            f'data-bucket="{esc(rec["bucket"])}" '
            f'data-fix-layer="{esc(rec["fix_layer"])}" '
            f'data-outcome="{esc(rec["outcome"])}" '
            f'data-status="{esc(rec["status"])}" '
            f'data-url="{esc(rec["url"])}" '
            f'data-gh="{esc(gh_url)}">'
            f"{esc(rec['first_paragraph'])}"
            f"</div>"
        )
    return f'<div id="caseDB" hidden>{"".join(parts)}</div>'


# ────────────────────────────────────────────────────────────────────────────
# HAR section — aggregate funnel + row anatomy + dynamic case sample
# ────────────────────────────────────────────────────────────────────────────


def _short_host(value: object) -> str:
    """ADR 0010 §17 whitelist helper — host only, no path/query/fragment.

    Used everywhere the HAR section surfaces a URL-derived value to the public
    page. Never emit `request.url` raw text; route through this.
    """
    host = hostname_from_url(value) if value is not None else ""
    if not host:
        return ""
    host = host.lower()
    return host if len(host) <= 60 else host[:57] + "…"


def _fmt_bytes(n: object) -> str:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "—"
    if v < 0:
        return "—"
    if v < 1024:
        return f"{v} B"
    if v < 1024 * 1024:
        return f"{v / 1024:.1f} KB"
    return f"{v / 1024 / 1024:.2f} MB"


def _short_text(value: object, limit: int = 40) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _extractor_fingerprint() -> tuple[int, str]:
    extract_mtime = 0
    extract_path = ROOT / "probe" / "extract.py"
    if extract_path.exists():
        try:
            extract_mtime = extract_path.stat().st_mtime_ns
        except OSError:
            pass
    return extract_mtime, EXTRACTOR_VERSION


def _slug_har_fingerprint(run_dir: Path) -> list[list]:
    """Per-slug fingerprint = list of [name, size, mtime_ns] for every traffic*.har.

    Used to detect whether a single probe run's HAR set changed since the
    last aggregate computation — keeps the per-slug cache valid even when
    other slugs' HARs change.
    """
    out: list[list] = []
    for p in sorted(run_dir.glob("traffic*.har")):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append([p.name, st.st_size, st.st_mtime_ns])
    return out


def _lazy_extract():
    """Returns (api_fn, body_fn, rss_fn, pag_fn, plat_fn) or None on ImportError.

    When this script is invoked as ``python scripts/generate_site.py``,
    ``sys.path[0]`` is ``scripts/`` and `probe.extract` is unreachable. Inject
    the repo root before the import so the lazy load works under both invocation
    patterns.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from probe.extract import (
            traffic_api_candidates,
            traffic_article_body_candidates,
            rss_feed_urls,
            pagination_hints,
            detect_common_platform,
        )
    except ImportError:
        return None
    return (
        traffic_api_candidates,
        traffic_article_body_candidates,
        rss_feed_urls,
        pagination_hints,
        detect_common_platform,
    )


def _read_har_entries(path: Path, *, cap: int = 1000) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    entries = (har.get("log") or {}).get("entries") or []
    return entries[:cap] if cap > 0 else entries


def _scan_slug_signals(run_dir: Path, fns) -> dict:
    """Run signal extractors against a single probe directory. Returns the
    per-slug record cached in ``_har_per_slug.json``. Expensive — only called
    for slugs whose fingerprint changed since the last computation.
    """
    api_fn, _body_fn, rss_fn, pag_fn, plat_fn = fns
    entries_total = 0
    sig = {"api": False, "rss": False, "pagination": False, "platform": False, "article_body": False}
    har_paths = sorted(run_dir.glob("traffic*.har"))
    for hp in har_paths:
        entries = _read_har_entries(hp, cap=2000)
        entries_total += len(entries)
        if not sig["api"]:
            try:
                if api_fn(hp):
                    sig["api"] = True
            except Exception:
                pass

    list_html_path = run_dir / "list.html"
    if list_html_path.exists():
        try:
            list_html_text = list_html_path.read_text(
                encoding="utf-8", errors="replace"
            )[:120_000]
        except OSError:
            list_html_text = ""
        if list_html_text:
            try:
                if rss_fn(html=list_html_text, base_url="https://example.invalid/"):
                    sig["rss"] = True
            except Exception:
                pass
            try:
                if pag_fn(list_html_text, "https://example.invalid/"):
                    sig["pagination"] = True
            except Exception:
                pass
            try:
                if plat_fn(list_html_text, "https://example.invalid/"):
                    sig["platform"] = True
            except Exception:
                pass
    return {"entries": entries_total, "signals": sig}


def _compute_har_aggregate(
    *, budget_seconds: float = 35.0, cache_dir: Path | None = None
) -> dict:
    """Walk probe artifacts incrementally to build the funnel stage counts.

    Strategy = **per-slug cache**. Each probe directory's HAR set has a
    fingerprint of ``[(name, size, mtime_ns), …]``. We keep the previously
    computed ``entries`` + ``signals`` per slug in ``_har_per_slug.json``.
    On each call we re-walk the slug list and only re-run the (expensive)
    signal extractors for slugs whose fingerprint changed since last time —
    so a brand-new probe arriving on N100 between 10-minute cycles only
    re-processes that one slug, not the whole 700-HAR set.

    Time budget guard kicks in only when many slugs changed at once.
    """
    pdir = ROOT / "output" / "probe"
    stages = {
        "probe_runs": 0,
        "har_captured": 0,
        "entries_total": 0,
        "signals": {"api": 0, "rss": 0, "pagination": 0, "platform": 0, "article_body": 0},
        "strategies_lane_A": {},
        "strategies_lane_B": {},
        "unmatched_configs": 0,
        "_truncated": False,
        "_reused_slugs": 0,
        "_rescanned_slugs": 0,
    }
    if not pdir.exists():
        return stages
    fns = _lazy_extract()
    if fns is None:
        return stages

    extractor_mt, extractor_ver = _extractor_fingerprint()
    cache_root = cache_dir if cache_dir is not None else (ROOT / "output" / "site")
    per_slug_cache_path = cache_root / "_har_per_slug.json"
    prior: dict = {}
    if per_slug_cache_path.exists():
        cached_blob = load_json(per_slug_cache_path)
        # Extractor change forces a full re-scan.
        if (
            cached_blob.get("extractor_version") == extractor_ver
            and cached_blob.get("extractor_mtime_ns") == extractor_mt
        ):
            prior = cached_blob.get("per_slug") or {}

    new_per_slug: dict[str, dict] = {}
    har_signal_slugs: dict[str, bool] = {}
    deadline = time.monotonic() + budget_seconds

    for run_dir in sorted(pdir.iterdir()):
        if not run_dir.is_dir():
            continue
        stages["probe_runs"] += 1
        slug = run_dir.name
        fp = _slug_har_fingerprint(run_dir)
        if not fp:
            continue
        stages["har_captured"] += 1

        # Try cache: if fingerprint unchanged, reuse last record.
        cached_entry = prior.get(slug)
        reuse = bool(cached_entry) and cached_entry.get("fp") == fp
        if reuse:
            entry_data = cached_entry
            stages["_reused_slugs"] += 1
        else:
            if time.monotonic() > deadline:
                stages["_truncated"] = True
                # Preserve old data for slugs we did not rescan in time.
                if cached_entry:
                    entry_data = cached_entry
                else:
                    new_per_slug[slug] = {"fp": fp, "entries": 0,
                                           "signals": {"api": False, "rss": False,
                                                       "pagination": False,
                                                       "platform": False,
                                                       "article_body": False}}
                    continue
            else:
                scanned = _scan_slug_signals(run_dir, fns)
                entry_data = {"fp": fp, **scanned}
                stages["_rescanned_slugs"] += 1
        new_per_slug[slug] = entry_data
        stages["entries_total"] += int(entry_data.get("entries") or 0)
        for k, v in (entry_data.get("signals") or {}).items():
            if v and k in stages["signals"]:
                stages["signals"][k] += 1
        har_signal_slugs[slug] = any((entry_data.get("signals") or {}).values())

    # Persist per-slug cache.
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        blob = {
            "computed_at": datetime.now(KST).isoformat(),
            "extractor_version": extractor_ver,
            "extractor_mtime_ns": extractor_mt,
            "per_slug": new_per_slug,
        }
        tmp = per_slug_cache_path.with_suffix(per_slug_cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(blob), encoding="utf-8")
        os.replace(tmp, per_slug_cache_path)
    except OSError:
        pass

    cfg_dir = ROOT / "configs"
    if cfg_dir.exists():
        for cfg_path in sorted(cfg_dir.glob("*.json")):
            slug = cfg_path.stem
            data = load_json(cfg_path)
            strategy = str(data.get("strategy") or "unknown")
            recognized = bool(data.get("_recognized_platform"))
            has_har_signal = har_signal_slugs.get(slug, False)
            if has_har_signal:
                d = stages["strategies_lane_A"]
                d[strategy] = d.get(strategy, 0) + 1
            elif recognized:
                d = stages["strategies_lane_B"]
                d[strategy] = d.get(strategy, 0) + 1
            else:
                stages["unmatched_configs"] += 1
    return stages


def read_har_aggregate(*, cache_dir: Path | None = None) -> dict:
    """Return funnel stage counts. Cache lives in ``_har_per_slug.json`` (per
    probe directory) so new HARs only force a rescan of *their own* slug. The
    aggregate is rebuilt every call but the per-slug work is incremental.
    """
    aggregate = _compute_har_aggregate(cache_dir=cache_dir)
    return {
        "computed_at": datetime.now(KST).isoformat(),
        "stages": aggregate,
    }


def _entry_first_get(entries: list[dict]) -> dict:
    for e in entries:
        req = e.get("request") or {}
        if (req.get("method") or "").upper() != "GET":
            continue
        resp = e.get("response") or {}
        mime = ((resp.get("content") or {}).get("mimeType") or "").lower()
        if any(skip in mime for skip in ("image/", "font/", "css", "javascript", "video/", "audio/")):
            continue
        ct = ""
        for h in resp.get("headers") or []:
            if (h.get("name") or "").lower() == "content-type":
                ct = h.get("value") or ""
                break
        return {
            "host": _short_host(req.get("url")),
            "method": req.get("method") or "",
            "status": resp.get("status"),
            "content_type": ct or mime or "—",
            "size": (resp.get("content") or {}).get("size"),
        }
    return {}


def pick_case_sample() -> dict:
    """Score-based selection of one probe run to showcase in the HAR case-sample
    panel. Returns dict with `slug, host, score, steps, row_anatomy_example,
    strategy`. Empty dict when nothing qualifies.
    """
    pdir = ROOT / "output" / "probe"
    if not pdir.exists():
        return {}

    recent_ok_urls: set[str] = set()
    bot_db = ROOT / "output" / "bot.sqlite3"
    if bot_db.exists():
        try:
            con = sqlite3.connect(str(bot_db))
            with con:
                for row in con.execute(
                    "SELECT url FROM jobs WHERE result_rc = 0 AND finished_at IS NOT NULL"
                ):
                    u = str(row[0] or "")
                    if u:
                        recent_ok_urls.add(u)
        except sqlite3.Error:
            pass
        finally:
            try:
                con.close()
            except (sqlite3.Error, UnboundLocalError):
                pass

    candidates: list[tuple[int, str, Path, list[dict], int]] = []
    for run_dir in pdir.iterdir():
        if not run_dir.is_dir():
            continue
        primary = run_dir / "traffic.har"
        if not primary.exists():
            others = sorted(run_dir.glob("traffic*.har"))
            primary = others[0] if others else None
        if primary is None:
            continue
        entries_all = _read_har_entries(primary, cap=0)
        n_entries = len(entries_all)
        if n_entries < 30:
            continue
        score = 0
        if n_entries >= 50:
            score += 1
        if n_entries >= 200:
            score += 1
        if 50 <= n_entries <= 3000:
            score += 1
        json_n = 0
        for e in entries_all[:500]:
            mime = ((e.get("response") or {}).get("content") or {}).get("mimeType") or ""
            if "json" in mime.lower():
                json_n += 1
                if json_n >= 3:
                    break
        if json_n >= 3:
            score += 2
        feed_cand = run_dir / "feed_candidates.json"
        if feed_cand.exists():
            try:
                if load_json(feed_cand):
                    score += 1
            except Exception:
                pass
        env_path = run_dir / "environment.json"
        if env_path.exists():
            env_data = load_json(env_path)
            src_url = str(env_data.get("url") or env_data.get("source_url") or "")
            if src_url and src_url in recent_ok_urls:
                score += 1
        candidates.append((score, run_dir.name, run_dir, entries_all, json_n))

    candidates.sort(key=lambda c: (-c[0], c[1]))
    if not candidates or candidates[0][0] < 4:
        return {}
    score, slug, run_dir, entries_all, json_n = candidates[0]

    env_path = run_dir / "environment.json"
    src_url = ""
    if env_path.exists():
        env_data = load_json(env_path)
        src_url = str(env_data.get("url") or env_data.get("source_url") or "")
    src_host = _short_host(src_url)
    if not src_host:
        # environment.json doesn't always store the source URL — fall back to the
        # first GET entry's host (matches the probe's actual target).
        first_anatomy = _entry_first_get(entries_all)
        src_host = first_anatomy.get("host") or ""

    filtered = 0
    for e in entries_all:
        req = e.get("request") or {}
        if (req.get("method") or "").upper() != "GET":
            continue
        mime = ((e.get("response") or {}).get("content") or {}).get("mimeType") or ""
        if any(s in mime.lower() for s in ("image/", "font/", "css", "javascript", "video/", "audio/")):
            continue
        filtered += 1

    api_n = rss_n = pag_n = plat_n = body_n = 0
    fns = _lazy_extract()
    primary = run_dir / "traffic.har"
    if not primary.exists():
        others = sorted(run_dir.glob("traffic*.har"))
        primary = others[0] if others else None
    if fns and primary is not None and primary.exists():
        api_fn, body_fn, rss_fn, pag_fn, plat_fn = fns
        try:
            api_n = len(api_fn(primary, page_url=src_url) or [])
        except Exception:
            pass
        try:
            body_n = len(body_fn(primary, article_url="") or [])
        except Exception:
            pass
        list_html_p = run_dir / "list.html"
        if list_html_p.exists():
            try:
                text = list_html_p.read_text(encoding="utf-8", errors="replace")[:200_000]
                base = src_url or "https://example.invalid/"
                try:
                    rss_n = len(rss_fn(html=text, base_url=base) or [])
                except Exception:
                    pass
                try:
                    pag_n = len(pag_fn(text, base) or [])
                except Exception:
                    pass
                try:
                    plat_n = 1 if plat_fn(text, base) else 0
                except Exception:
                    pass
            except OSError:
                pass

    strategy = ""
    cfg_path = ROOT / "configs" / f"{slug}.json"
    if cfg_path.exists():
        cfg = load_json(cfg_path)
        strategy = str(cfg.get("strategy") or "")

    steps = [
        {
            "stage": 1,
            "label": "Visit URL",
            "count": None,
            "detail": (
                f"playwright drove a headless browser at host {src_host or '(unknown)'} "
                f"and saved every network request to traffic.har."
            ),
        },
        {
            "stage": 2,
            "label": "Entries inspected",
            "count": len(entries_all),
            "detail": "Raw HAR log[].entries — every request the page made.",
        },
        {
            "stage": 3,
            "label": "Filtered (GET + non-asset)",
            "count": filtered,
            "detail": "Drop non-GET and image/font/css/javascript/media MIME types.",
        },
        {
            "stage": 4,
            "label": "Signals matched",
            "count": api_n + rss_n + pag_n + plat_n + body_n,
            "detail": (
                f"JSON API: {api_n} · RSS: {rss_n} · pagination: {pag_n} · "
                f"platform: {plat_n} · article-body: {body_n}"
            ),
        },
        {
            "stage": 5,
            "label": "Strategy chosen",
            "count": None,
            "detail": f"config strategy = {strategy or '(none)'}",
        },
    ]
    return {
        "slug": slug,
        "host": src_host,
        "score": score,
        "steps": steps,
        "row_anatomy_example": _entry_first_get(entries_all),
        "strategy": strategy,
    }


def svg_har_funnel(stages: dict) -> str:
    width = 920
    height = 360
    margin_x = 24
    col_w = (width - 2 * margin_x) / 5

    sig = stages.get("signals") or {}
    laneA = stages.get("strategies_lane_A") or {}
    laneB = stages.get("strategies_lane_B") or {}
    unmatched = stages.get("unmatched_configs", 0)

    cols = [
        ("Probe runs", stages.get("probe_runs", 0), "Probe directories on disk."),
        ("HAR captured", stages.get("har_captured", 0), "Runs with at least one traffic*.har file."),
        (
            "Entries scanned",
            stages.get("entries_total", 0),
            "HAR log[].entries summed (capped at 1000 per file).",
        ),
        (
            "Signals matched",
            sum(sig.values()),
            (
                f"API {sig.get('api', 0)} · RSS {sig.get('rss', 0)} · "
                f"pagination {sig.get('pagination', 0)} · "
                f"platform {sig.get('platform', 0)} · article-body {sig.get('article_body', 0)}"
            ),
        ),
        (
            "Strategy chosen",
            sum(laneA.values()) + sum(laneB.values()),
            (
                f"Lane A (HAR-driven) {sum(laneA.values())} · "
                f"Lane B (recognizer, no HAR) {sum(laneB.values())} · "
                f"Unmatched configs {unmatched}"
            ),
        ),
    ]

    box_h = 80
    y_mid = 130
    boxes = []
    arrows = []
    last_x_right = None
    for i, (label, value, detail) in enumerate(cols):
        x = margin_x + i * col_w
        bx = x + 4
        bw = col_w - 8
        by = y_mid - box_h / 2
        boxes.append(
            f'<g class="funnel-stage" data-label="{esc(label)}" data-detail="{esc(detail)}">'
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{box_h}" '
            f'rx="6" ry="6" class="funnel-box"></rect>'
            f'<text class="funnel-label" x="{bx + bw / 2:.1f}" y="{by + 26:.0f}" '
            f'text-anchor="middle">{esc(label)}</text>'
            f'<text class="funnel-value" x="{bx + bw / 2:.1f}" y="{by + 58:.0f}" '
            f'text-anchor="middle">{esc(value)}</text>'
            f"</g>"
        )
        if last_x_right is not None:
            arrows.append(
                f'<line class="funnel-arrow" x1="{last_x_right:.1f}" y1="{y_mid:.0f}" '
                f'x2="{bx:.1f}" y2="{y_mid:.0f}"></line>'
            )
        last_x_right = bx + bw

    lane_y = y_mid + box_h / 2 + 30
    lane_x = margin_x + 4 * col_w + 4
    lane_w = col_w - 8

    def _lane_top5(d: dict) -> str:
        if not d:
            return "(none)"
        items = sorted(d.items(), key=lambda kv: -kv[1])[:5]
        return ", ".join(f"{esc(k)}: {esc(v)}" for k, v in items)

    laneA_text = _lane_top5(laneA)
    laneB_text = _lane_top5(laneB)

    lanes_svg = (
        f'<g class="funnel-lane" data-label="Lane A" '
        f'data-detail="HAR-driven: configs whose probe HAR matched a signal.">'
        f'<text class="funnel-sub" x="{lane_x:.1f}" y="{lane_y:.0f}">'
        f"Lane A — HAR-driven</text>"
        f'<text class="funnel-sub-detail" x="{lane_x:.1f}" y="{lane_y + 16:.0f}">{laneA_text}</text>'
        f"</g>"
        f'<g class="funnel-lane" data-label="Lane B" '
        f'data-detail="Recognizer-only: configs issued by URL-pattern recognizers '
        f'without needing HAR.">'
        f'<text class="funnel-sub" x="{lane_x:.1f}" y="{lane_y + 48:.0f}">'
        f"Lane B — Recognizer (no HAR)</text>"
        f'<text class="funnel-sub-detail" x="{lane_x:.1f}" y="{lane_y + 64:.0f}">{laneB_text}</text>'
        f"</g>"
    )

    note = ""
    if unmatched > 0:
        note = (
            f'<text class="funnel-note" x="{margin_x:.0f}" y="{height - 14:.0f}">'
            f"Side note · {esc(unmatched)} configs in this snapshot have neither a HAR signal "
            f"nor a recognizer match (legacy or pre-HAR registrations)."
            f"</text>"
        )

    return (
        f'<svg id="harFunnel" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="HAR analysis funnel">'
        f'<rect class="scatter-bg" x="0" y="0" width="{width}" height="{height}"></rect>'
        + "".join(arrows)
        + "".join(boxes)
        + lanes_svg
        + note
        + "</svg>"
    )


def render_har_anatomy(sample: dict) -> str:
    ex = sample.get("row_anatomy_example") or {}
    rows = [
        ("request.url", "URL that the headless browser fetched", "Host filter (ad/tracker drop); cross-host API detection.", ex.get("host") or "—"),
        ("request.method", "HTTP method", "Only GET considered for list extraction.", ex.get("method") or "—"),
        ("response.status", "HTTP status code", "Drop non-2xx responses before signal extraction.", str(ex.get("status") or "—")),
        ("response.headers.content-type", "MIME from response headers", "Route JSON candidates to API lane, HTML to platform/RSS lanes.", _short_text(ex.get("content_type") or "—", 38)),
        ("response.content.size", "Response body size", "Drop empty / tracker pixels; rank list endpoints.", _fmt_bytes(ex.get("size"))),
    ]
    body = "".join(
        '<tr><td><code>{f}</code></td><td>{w}</td><td>{y}</td><td><code>{v}</code></td></tr>'.format(
            f=esc(field), w=esc(what), y=esc(why), v=esc(value)
        )
        for field, what, why, value in rows
    )
    return (
        '<table class="har-anatomy">'
        '<thead><tr><th>HAR field</th><th>What it is</th><th>Why probe cares</th>'
        '<th>This case sample</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def render_har_case_steps(sample: dict) -> str:
    if not sample:
        return (
            '<p class="meta">No qualifying probe artifact for the case-sample panel '
            "right now — it auto-fills once a recent run scores at least 4.</p>"
        )
    items = []
    steps = sample.get("steps") or []
    for i, step in enumerate(steps):
        cnt_html = ""
        if step.get("count") is not None:
            cnt_html = f' <span class="step-count">{esc(step["count"])}</span>'
        open_attr = " open" if i == 0 else ""
        items.append(
            f'<details class="case-step"{open_attr}>'
            f"<summary>Step {esc(step['stage'])}. {esc(step['label'])}{cnt_html}</summary>"
            f'<div class="step-detail">{esc(step["detail"])}</div>'
            f"</details>"
        )
    return (
        f'<p class="meta">Case sample host: <code>{esc(sample.get("host") or "(unknown)")}</code>'
        f' · selection score <code>{esc(sample.get("score", "-"))}</code>'
        f' · final strategy <code>{esc(sample.get("strategy") or "(none)")}</code></p>'
        + "".join(items)
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
    har_aggregate: dict | None = None,
    har_sample: dict | None = None,
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

    har_data = har_aggregate or {"stages": {}}
    har_stages = har_data.get("stages") or {}
    har_funnel_svg = svg_har_funnel(har_stages)
    har_anatomy_html = render_har_anatomy(har_sample or {})
    har_case_html = render_har_case_steps(har_sample or {})
    har_extractor_ok = bool(har_stages.get("har_captured", 0)) or bool(har_stages.get("probe_runs", 0))
    har_meta_line = (
        f'Aggregate computed at {esc(har_data.get("computed_at", "—"))} '
        f'· extractor {esc(EXTRACTOR_VERSION)}'
        if har_extractor_ok
        else "HAR extraction is unavailable on this host (probe artifacts or `probe.extract` module not reachable)."
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
    .funnel-box {{ fill: var(--panel); stroke: var(--accent); stroke-width: 1.4; transition: fill 100ms ease; }}
    .funnel-stage:hover .funnel-box, .funnel-lane:hover {{ cursor: help; }}
    .funnel-stage:hover .funnel-box {{ fill: #eaf1f2; }}
    .funnel-label {{ fill: var(--ink); font: 600 13px Georgia, "Times New Roman", serif; }}
    .funnel-value {{ fill: var(--accent); font: 700 22px Georgia, "Times New Roman", serif; }}
    .funnel-arrow {{ stroke: var(--accent-2); stroke-width: 1.6; }}
    .funnel-sub {{ fill: var(--ink); font: 700 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .funnel-sub-detail {{ fill: var(--muted); font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .funnel-note {{ fill: var(--muted); font: italic 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .har-subheader {{
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.1rem;
      margin: 26px 0 10px;
    }}
    .har-anatomy code {{
      background: var(--paper);
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 0.86rem;
    }}
    .case-step {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 4px;
      margin: 6px 0;
      padding: 0;
    }}
    .case-step summary {{
      list-style: none;
      cursor: pointer;
      padding: 10px 14px;
      font-weight: 600;
      color: var(--ink);
    }}
    .case-step summary::-webkit-details-marker {{ display: none; }}
    .case-step[open] summary {{ border-bottom: 1px solid var(--line); }}
    .step-count {{
      display: inline-block;
      margin-left: 8px;
      padding: 1px 8px;
      background: var(--paper);
      border-radius: 10px;
      color: var(--accent);
      font-family: Georgia, "Times New Roman", serif;
      font-size: 0.96rem;
    }}
    .step-detail {{ padding: 10px 14px; color: var(--muted); font-size: 0.92rem; }}
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
        open the full markdown on GitHub from the modal footer.</figcaption>
    </figure>
    {case_db_html}
    <div id="caseModal" class="modal" hidden role="dialog" aria-labelledby="caseModalTitle" aria-modal="true">
      <div class="modal-backdrop" data-close="1"></div>
      <div class="modal-inner">
        <button type="button" class="modal-close" aria-label="Close" data-close="1">×</button>
        <p class="modal-meta" id="caseModalMeta"></p>
        <h3 class="modal-title" id="caseModalTitle"></h3>
        <p class="modal-body" id="caseModalBody"></p>
        <p class="modal-link"><a id="caseModalLink" href="#" target="_blank" rel="noopener noreferrer">Read full case on GitHub →</a></p>
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
        function recordFor(slug) {{
          return document.querySelector('#caseDB .case-record[data-slug="' + slug.replace(/"/g, '\\\\"') + '"]');
        }}
        function openCase(slug) {{
          var rec = recordFor(slug);
          if (!rec || !modal) return;
          var status = rec.getAttribute('data-status') || slug;
          var date = rec.getAttribute('data-date') || '';
          var bucket = rec.getAttribute('data-bucket') || '';
          var outcome = rec.getAttribute('data-outcome') || '';
          var fix = rec.getAttribute('data-fix-layer') || '';
          var gh = rec.getAttribute('data-gh') || '#';
          document.getElementById('caseModalTitle').textContent = status;
          document.getElementById('caseModalMeta').textContent =
            date + ' · ' + bucket + ' · outcome: ' + (outcome || '—') +
            (fix ? ' · fix_layer: ' + fix : '');
          document.getElementById('caseModalBody').textContent = rec.textContent || '(no body excerpt)';
          var link = document.getElementById('caseModalLink');
          link.setAttribute('href', gh);
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
            var slug = block.getAttribute('data-slug') || '';
            var bucket = block.getAttribute('data-bucket') || '';
            showTip('<b>' + slug + '</b><span>' + bucket + ' · click to open</span>', e);
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
            openCase(block.getAttribute('data-slug') || '');
          }}
        }});
        svg.addEventListener('keydown', function (e) {{
          if (e.key !== 'Enter' && e.key !== ' ') return;
          var block = e.target.closest ? e.target.closest('.case-block') : null;
          if (block) {{
            e.preventDefault();
            openCase(block.getAttribute('data-slug') || '');
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
    <p class="lead">When a new URL is offered, a headless browser visits it and records every
      network request to a <code>traffic.har</code> file. The pipeline then asks five questions of
      that file to decide how to fetch the site afterwards. The funnel below counts how many
      probes traveled through each question this snapshot; below it, one live case sample shows the
      same five questions answered for a real site.</p>
    <p class="meta">{har_meta_line}</p>
    <figure>
      {har_funnel_svg}
      <div id="harFunnelTip" class="dot-tip" hidden></div>
      <figcaption>Figure 3. Stage counts roll up across every probe run with a <code>traffic*.har</code>
        on disk. Lane A counts configs where a HAR signal directly triggered the strategy; Lane B
        counts configs issued by URL-pattern recognizers that did not need HAR at all. Hover a
        stage for the breakdown.</figcaption>
    </figure>
    <h3 class="har-subheader">What fields are read from each HAR entry</h3>
    {har_anatomy_html}
    <h3 class="har-subheader">A live case sample (auto-selected each cycle)</h3>
    {har_case_html}
    <script>
      (function () {{
        var svg = document.getElementById('harFunnel');
        var tip = document.getElementById('harFunnelTip');
        if (!svg || !tip) return;
        function showTip(label, detail, e) {{
          tip.innerHTML = '<b>' + label + '</b><span>' + detail + '</span>';
          tip.hidden = false;
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }}
        svg.addEventListener('mousemove', function (e) {{
          if (tip.hidden) return;
          tip.style.left = (e.clientX + 14) + 'px';
          tip.style.top = (e.clientY + 14) + 'px';
        }});
        svg.addEventListener('mouseover', function (e) {{
          var stage = e.target.closest ? e.target.closest('.funnel-stage, .funnel-lane') : null;
          if (!stage) {{ tip.hidden = true; return; }}
          var label = stage.getAttribute('data-label') || '';
          var detail = stage.getAttribute('data-detail') || '';
          showTip(label, detail, e);
        }});
        svg.addEventListener('mouseleave', function () {{ tip.hidden = true; }});
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
    har_aggregate = read_har_aggregate(cache_dir=out_path.parent)
    har_sample = pick_case_sample()
    generated_at = datetime.now(KST)
    page = render_html(
        configs,
        poll,
        jobs,
        generated_at,
        case_records=case_records,
        har_aggregate=har_aggregate,
        har_sample=har_sample,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(page, encoding="utf-8")
    os.replace(tmp_path, out_path)

    elapsed = time.monotonic() - t0
    har_stages = (har_aggregate or {}).get("stages") or {}
    print(
        "[generate_site] wrote "
        f"{out_path} ({len(configs['items'])} configs, {poll['total']} polling, "
        f"{len(jobs['recent'])} recent jobs, "
        f"{len(case_records)} cases, "
        f"{har_stages.get('har_captured', 0)} HAR runs) "
        f"elapsed={elapsed:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
