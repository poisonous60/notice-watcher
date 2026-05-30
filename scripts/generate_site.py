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
import shutil
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

# Static narrative of the full /watch backend chain — used by the Figure 3 HAR
# section. Edit when bot / worker / register code refactors so the public page
# keeps describing the actual call order. Rendered as a flame-icicle SVG by
# `svg_watch_icicle()`. Each node optionally carries (file, fn, line) — those
# become a GitHub deep-link on click. Branches (skip / fast-path / early
# return) live inline in the tree with `branch: {tag: ...}` and render dashed.
# Line numbers can drift when code is refactored; treat them as best-effort
# anchors, not contracts (see `docs/공개 사이트 figure 설계.md` §2c).
GITHUB_BASE = "https://github.com/poisonous60/notice-watcher/blob/main"

LANE_COLORS = {
    "bot":        "#3d737f",   # bot asyncio (matches Figure 1/2 teal)
    "worker":     "#6f7f52",   # worker asyncio pool (olive)
    "subprocess": "#8a6f4d",   # register subprocess + probe + LLM (brown)
}

LANE_LABELS = {
    "bot":        "bot asyncio",
    "worker":     "worker asyncio",
    "subprocess": "register subprocess",
}

WATCH_CALL_TREE: dict = {
    "label": "/watch <url>", "file": "bot/main.py", "fn": "watch", "line": 173,
    "lane": "bot",
    "role": (
        "Discord slash command handler. defer 응답 → url_to_slug → 이미 등록된 "
        "slug 흡수 → is_blocked / is_registered 가드."
    ),
    "children": [
        {
            "label": "url_gate.check", "file": "bot/url_gate.py", "fn": "check", "line": 516,
            "lane": "bot",
            "role": (
                "probe 시작 전 URL 4 stage 검사. 하나라도 막히면 UrlRejected → "
                "ack 거부."
            ),
            "children": [
                {"label": "struct validate", "file": "bot/url_gate.py",
                 "fn": "_check_structural", "line": 330, "lane": "bot",
                 "role": "scheme/host 형식, user:pass@ / 제어문자 / IP 리터럴 (공인·사설·IPv6) 거부 (stdlib urllib만)."},
                {"label": "blacklist", "file": "bot/url_gate.py",
                 "fn": "_check_policy", "line": 371, "lane": "bot",
                 "role": "bot/url_blacklist.json — SNS · 동영상 · 축약 호스트 / 파일 직링 host_suffix · path_ext 매치."},
                {"label": "SSRF (DNS)", "file": "bot/url_gate.py",
                 "fn": "_check_ip", "line": 434, "lane": "bot",
                 "role": "host IDNA → DNS 해석. 모든 IP 가 private/loopback/link-local/reserved 면 거부."},
                {"label": "Safe Browsing v4", "file": "bot/url_gate.py",
                 "fn": "_check_safe_browsing", "line": 497, "lane": "bot",
                 "role": "Google Safe Browsing threatMatches:find. fail-closed — 키 미설정/네트워크 오류/non-200 도 거부."},
            ],
        },
        {
            "label": "is_registered?", "file": "bot/main.py",
            "fn": "watch", "line": 211, "lane": "bot",
            "branch": {"tag": "skip if already registered"},
            "role": (
                "이미 등록된 사이트면 subprocess 안 띄움 — subscription 추가 + 예시 "
                "글 1개 노출 후 종료. (분기 — 본 chain 안 옴)"
            ),
        },
        {
            "label": "db.enqueue_job", "file": "bot/db.py",
            "fn": "enqueue_job", "line": 1077, "lane": "bot",
            "role": (
                "jobs 큐 row insert (kind=register, priority=0=user). interaction 응답을 "
                "ack 메시지로 promote → worker 가 끝나면 channel edit (token 만료 무관)."
            ),
        },
        {
            "label": "worker._process_job_inner", "file": "bot/worker.py",
            "fn": "_process_job_inner", "line": 494, "lane": "worker",
            "role": (
                "worker pool task 가 claim 시점에 잡 꺼내 처리. slug_lock + chromium_lock "
                "잡고 subprocess. async hand-off 경계 (bot enqueue → worker claim)."
            ),
            "children": [
                {"label": "chromium_lock acquire", "file": "bot/site_ops.py",
                 "fn": "blocking_register", "line": 317, "lane": "worker",
                 "role": (
                     "scripts/_chromium_lock.py 의 cross-process flock — 동시 chromium "
                     "browser 차단. settings.chromium_lock.slots (보통 2)."
                 )},
                {"label": "blocking_register (subprocess)", "file": "bot/site_ops.py",
                 "fn": "blocking_register", "line": 291, "lane": "subprocess",
                 "role": (
                     "scripts/register.py 별 OS process spawn. start_new_session=True "
                     "+ timeout killer thread. async→subprocess 경계."
                 ),
                 "children": [
                     {"label": "_try_known_platform", "file": "scripts/register.py",
                      "fn": "_try_known_platform", "line": 2946, "lane": "subprocess",
                      "branch": {"tag": "fast-path: recognizer hit → publish, skip probe + generate"},
                      "role": (
                          "engine/recognizers/<plat>.py URL 클래스 매칭 (arca/discourse/"
                          "xenforo/reddit/…). 매치되면 probe + LLM 우회, 즉시 config 발급."
                      )},
                     {"label": "probe.py main", "file": "scripts/probe.py",
                      "fn": "main", "line": 524, "lane": "subprocess",
                      "role": (
                          "fetch_static (httpx) → 부족하면 fetch_headless (Playwright + "
                          "record_har_path). list.html / traffic.har / environment.json "
                          "산출. Figure 4 가 HAR 산출물 deep dive."
                      )},
                     {"label": "_preflight (article re-probe)", "file": "scripts/register.py",
                      "fn": "_preflight", "line": 2882, "lane": "subprocess",
                      "role": (
                          "probe 가 잡은 첫 글 페이지를 Playwright+HAR 로 re-probe → "
                          "article_candidates.json + digest.escalation_hint 주입. 1 라운드 "
                          "안 1회만 (--no-escalate 면 skip)."
                      )},
                     {"label": "build_digest", "file": "engine/digest.py",
                      "fn": "build_digest", "line": 839, "lane": "subprocess",
                      "role": (
                          "probe 산출물 + preflight 결과 → digest.json (LLM 입력용 압축 "
                          "evidence bundle)."
                      )},
                     {"label": "run_codex_agentic", "file": "generate/codex_agentic.py",
                      "fn": "run_codex_agentic", "line": 1254, "lane": "subprocess",
                      "role": (
                          "Codex CLI multi-turn agent. tmpdir 안 prompts/examples/validator "
                          "복사 → candidate.json + run_validator. parent 가 audit + publish. "
                          "Figure 4 가 packet 시각화."
                      )},
                     {"label": "_register_built_config", "file": "scripts/register.py",
                      "fn": "_register_built_config", "line": 3112, "lane": "subprocess",
                      "exit_chip": "→ configs/<slug>.json + poll_state/<slug>.json",
                      "role": (
                          "end-to-end validate (실제 fetch + parse + baseline 빌드). 통과 "
                          "시 atomic publish. ack 메시지 'OK', 폴링 대상 진입."
                      )},
                 ]},
            ],
        },
    ],
}

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


def _redact_public_text(value: object) -> str:
    return "" if value is None else str(value)


PROBE_PIPELINE: list[dict] = [
    {
        "id": "fetch",
        "title": "Probe fetches",
        "tagline": "static + browser",
        "summary": "Static GET first; Playwright captures the rendered page only when static fetch is insufficient.",
        "steps": [
            ("scripts/probe.py", "main(argv) → _run(args, url, slug)", "CLI entry and output/probe/<slug>/ setup."),
            ("probe/fetch_static.py", "fetch()", "First static httpx request with preset headers."),
            ("probe/fetch_headless.py", "fetch_with_capture()", "Browser fallback with HAR capture."),
        ],
    },
    {
        "id": "har",
        "title": "Capture HAR",
        "tagline": "network log + HTML",
        "summary": "Headless runs write traffic.har plus rendered HTML and related probe artifacts.",
        "steps": [
            ("output/probe/<slug>/traffic.har", "—", "Primary network log used by later extractors."),
            ("output/probe/<slug>/list.html", "—", "Rendered list-page HTML snapshot."),
            ("output/probe/<slug>/environment.json", "—", "Runtime metadata for diagnosing probe differences."),
        ],
    },
    {
        "id": "entries",
        "title": "Inspect entries",
        "tagline": "data calls, not assets",
        "summary": "Extractors parse HAR entries and ignore static assets, trackers, and low-value responses.",
        "steps": [
            ("probe/extract.py", "json.loads(har_path.read_text())", "Each extractor reads the HAR it needs."),
            ("probe/extract.py", "_entry_resource_type()", "Tags entries by xhr / fetch / document / asset type."),
            ("probe/extract.py", "_AD_TRACKER_RE + filters", "Drops noisy ad/tracker/static asset entries."),
        ],
    },
    {
        "id": "signals",
        "title": "Match signals",
        "tagline": "APIs · feeds · pages · platforms",
        "summary": "Probe extracts JSON API, body API, RSS, pagination, audio-share, and platform hints.",
        "steps": [
            ("probe/extract.py", "traffic_api_candidates()", "Detect JSON list endpoints."),
            ("probe/extract.py", "traffic_article_body_candidates()", "Detect per-article JSON payloads."),
            ("probe/extract.py", "rss_feed_urls() / pagination_hints()", "Find feeds and page templates."),
        ],
    },
    {
        "id": "decide",
        "title": "Choose path",
        "tagline": "digest · recognizer · writer",
        "summary": "Signals become a digest; register chooses a recognizer, API loop, or agentic config writer path.",
        "steps": [
            ("engine/digest.py", "build_digest(...)", "Fold artifacts and signals into model-facing evidence."),
            ("scripts/register.py", "probe-marker platform config", "Use known platform configs when probe markers match."),
            ("scripts/register.py", "auto: api_loop_once → agentic", "Generate, validate, and publish configs/<slug>.json."),
        ],
    },
]


def _icicle_leaf_count(node: dict) -> int:
    """Leaf count = horizontal weight. Branch nodes count as 1 leaf (they sit
    inline alongside happy-path siblings so they consume a slot)."""
    children = node.get("children") or []
    if not children:
        return 1
    return sum(_icicle_leaf_count(c) for c in children)


def _icicle_tree_depth(node: dict) -> int:
    children = node.get("children") or []
    if not children:
        return 1
    return 1 + max(_icicle_tree_depth(c) for c in children)


def _github_url(node: dict) -> str:
    f = node.get("file")
    if not f:
        return ""
    base = f"{GITHUB_BASE}/{f}"
    line_n = node.get("line")
    return f"{base}#L{int(line_n)}" if line_n else base


def _icicle_truncate(s: str, max_chars: int) -> str:
    if max_chars <= 1:
        return "…"
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _icicle_truncate_path(path: str, max_chars: int) -> str:
    """Truncate `dir/.../file.ext` preferring to keep the file basename (and
    its extension) intact. Falls back to plain trailing-ellipsis when even
    the basename won't fit."""
    if max_chars <= 1:
        return "…"
    if len(path) <= max_chars:
        return path
    if "/" in path:
        last = path.rsplit("/", 1)[1]
        if len(last) <= max_chars:
            return last
        return _icicle_truncate(last, max_chars)
    return _icicle_truncate(path, max_chars)


def _icicle_tooltip_html(node: dict) -> str:
    """Tooltip = file (bold) · fn · line · branch-tag (italic) · role.
    Each segment passes through esc() — the existing tip handler sets
    innerHTML from data-tip-html, so unsanitized angle brackets in label
    strings would break the page."""
    file = node.get("file", "") or ""
    fn = node.get("fn", "") or ""
    line_n = node.get("line")
    role = node.get("role", "") or node.get("label", "")
    branch_tag = ((node.get("branch") or {}).get("tag") or "")
    exit_chip = node.get("exit_chip", "")
    parts: list[str] = []
    head = esc(file or node.get("label", ""))
    if head:
        parts.append(f"<strong>{head}</strong>")
    if fn:
        line_str = f" · L{int(line_n)}" if line_n else ""
        parts.append(f"{esc(fn)}(){esc(line_str)}")
    if branch_tag:
        parts.append(f"<em>{esc(branch_tag)}</em>")
    if role:
        parts.append(esc(role))
    if exit_chip:
        parts.append(f"<small>{esc(exit_chip)}</small>")
    return "<br/>".join(parts)


def _render_icicle_node(node: dict, x: float, y: float, w: float,
                        row_h: float) -> list[str]:
    """Recursive: emit this node's <a><g><rect><text>...</g></a> then recurse
    children packed proportional to their leaf count."""
    out: list[str] = []
    is_branch = bool(node.get("branch"))
    lane = node.get("lane", "bot")
    color = LANE_COLORS.get(lane, "#9b6b6b")

    label = node.get("label", "")
    file_path = node.get("file", "")
    fn = node.get("fn", "")
    branch_tag = ((node.get("branch") or {}).get("tag") or "")
    exit_chip = node.get("exit_chip", "")
    href = _github_url(node)

    pad = 2
    bx = x + pad
    by = y + pad
    bw = max(2.0, w - 2 * pad)
    bh = max(8.0, row_h - 2 * pad)

    # Approximate char widths (sans 10px ~= 6px wide, 9px ~= 5.4px).
    char_w_file = 6.2
    char_w_fn = 5.6
    avail_file = max(1, int(bw / char_w_file) - 1)
    avail_fn = max(1, int(bw / char_w_fn) - 1)

    text_elems: list[str] = []
    if file_path and bw >= 46:
        text_elems.append(
            f'<text class="icicle-file" x="{bx + bw / 2:.1f}" '
            f'y="{by + bh / 2 - 2:.1f}" text-anchor="middle">'
            f'{esc(_icicle_truncate_path(file_path, avail_file))}</text>'
        )
        if fn:
            text_elems.append(
                f'<text class="icicle-fn" x="{bx + bw / 2:.1f}" '
                f'y="{by + bh / 2 + 12:.1f}" text-anchor="middle">'
                f'{esc(_icicle_truncate(fn + "()", avail_fn))}</text>'
            )
    else:
        text_elems.append(
            f'<text class="icicle-label" x="{bx + bw / 2:.1f}" '
            f'y="{by + bh / 2 + 4:.1f}" text-anchor="middle">'
            f'{esc(_icicle_truncate(label, avail_file))}</text>'
        )

    rect_classes = "icicle-box" + (" branch" if is_branch else "")
    extra_stroke = ' stroke-dasharray="6 3"' if is_branch else ""
    fill_opacity = ' fill-opacity="0.42"' if is_branch else ""
    rect = (
        f'<rect class="{rect_classes}" x="{bx:.1f}" y="{by:.1f}" '
        f'width="{bw:.1f}" height="{bh:.1f}" rx="4" ry="4" '
        f'fill="{color}"{fill_opacity} stroke="{color}" '
        f'stroke-width="{1.5 if is_branch else 0.8}"{extra_stroke}></rect>'
    )

    tag_elem = ""
    if branch_tag:
        tag_elem = (
            f'<text class="icicle-tag" x="{bx + bw / 2:.1f}" '
            f'y="{by - 2:.1f}" text-anchor="middle">'
            f'{esc(_icicle_truncate(branch_tag, avail_file + 6))}</text>'
        )

    exit_elem = ""
    if exit_chip:
        exit_elem = (
            f'<text class="icicle-exit" x="{bx + bw / 2:.1f}" '
            f'y="{by + bh + 14:.1f}" text-anchor="middle">'
            f'{esc(_icicle_truncate(exit_chip, avail_file + 12))}</text>'
        )

    g_attrs = (
        f'class="icicle-node lane-{esc(lane)}'
        + (' branch' if is_branch else '')
        + f'" data-tip-html="{esc(_icicle_tooltip_html(node))}"'
    )
    inner = rect + "".join(text_elems) + tag_elem + exit_elem
    g_open = f'<g {g_attrs}>'
    g_close = "</g>"

    if href:
        out.append(
            f'<a href="{esc(href)}" target="_blank" rel="noopener" '
            f'aria-label="{esc(file_path or label)} — open on GitHub">'
            + g_open + inner + g_close + "</a>"
        )
    else:
        out.append(g_open + inner + g_close)

    # Recurse children (packed proportional to leaf count).
    children = node.get("children") or []
    if children:
        child_y = y + row_h
        leaf_sum = sum(_icicle_leaf_count(c) for c in children) or 1
        cx = x
        for c in children:
            cw = w * _icicle_leaf_count(c) / leaf_sum
            out.extend(_render_icicle_node(c, cx, child_y, cw, row_h))
            cx += cw
    return out


def svg_watch_icicle(tree: dict, *, width: int = 920, row_h: int = 56,
                     header_h: int = 30, footer_h: int = 24) -> str:
    """Top-down flame icicle for the /watch backend chain.

    - Y row = call depth (root on top).
    - X = sequence; parent box spans its children horizontally.
    - Box width = leaf count under that node (cascade shape, NOT time).
    - Lane color = process boundary (bot / worker / subprocess).
    - Branch nodes = dashed border + tag chip above (skip / fast-path / exit).
    - Click = open file at line on GitHub. Hover = file · fn · line · role.
    """
    depth = _icicle_tree_depth(tree)
    inner_y0 = header_h
    height = header_h + depth * row_h + footer_h

    # Horizontal lane legend at the top — small swatch + label, inline.
    legend_x = 8
    legend_y = 12
    legend_elems: list[str] = []
    for key in ("bot", "worker", "subprocess"):
        legend_elems.append(
            f'<rect x="{legend_x:.1f}" y="{legend_y - 9:.1f}" width="12" '
            f'height="12" rx="2" fill="{LANE_COLORS[key]}"></rect>'
        )
        legend_elems.append(
            f'<text class="icicle-legend" x="{legend_x + 16:.1f}" '
            f'y="{legend_y + 1:.1f}">{esc(LANE_LABELS[key])}</text>'
        )
        legend_x += 16 + len(LANE_LABELS[key]) * 7 + 22

    body_nodes = _render_icicle_node(tree, 0, inner_y0, width, row_h)

    return (
        f'<svg id="watchIcicle" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'preserveAspectRatio="xMidYMin meet" '
        f'role="img" '
        f'aria-label="What runs when you /watch a new site — call icicle. '
        f'Lanes: bot asyncio, worker asyncio, register subprocess. '
        f'Dashed boxes = conditional branches. Click any box to open the '
        f'source file on GitHub.">'
        f'<rect class="scatter-bg" x="0" y="0" width="{width}" '
        f'height="{height}"></rect>'
        + "".join(legend_elems)
        + "".join(body_nodes)
        + "</svg>"
    )


# ────────────────────────────────────────────────────────────────────────────
# Figure 3b — legacy probe + register decide funnel (TEMP, to be removed once
# the icicle absorbs probe/register internal stage detail). Drives `PROBE_PIPELINE`.
# ────────────────────────────────────────────────────────────────────────────


def svg_har_funnel() -> str:
    """Legacy 5-step probe + register-decide funnel — kept as Figure 3b
    while the new icicle is still missing per-stage probe/register detail."""
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
_HAR_DETAIL_CACHE_VERSION = 4
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
_AGENTIC_MANIFEST_FILES = (
    "generate/codex_agentic.py",
    "prompts/register_agent_AGENTS.md",
    "prompts/register_agent_user.txt",
    "prompts/config_writer.system.txt",
    "scripts/validate_config.py",
    "schemas/register_agentic_result.json",
)
_AGENTIC_PACKET_FLOW = [
    ("01", "Probe artifacts", "The probe leaves HTML, HAR, diagnosis, and list-candidate files under output/probe/<slug>/."),
    ("02", "Digest build", "engine.digest folds those artifacts into digest.json, the compact evidence bundle the agent reads first."),
    ("03", "Tmpdir staging", "generate/codex_agentic.py copies prompts, examples, validator wrappers, and optional failure feedback into a throwaway workdir."),
    ("04", "Agent loop", "Codex reads only the staged packet, writes ./candidate.json, and runs ./run_validator.* inside the workdir."),
    ("05", "Parent publish", "The parent parses last.json, re-reads candidate.json, validates again, audits repo writes, then publishes configs/<slug>.json."),
]
def _host_mask(value: object) -> str:
    """Return a compact URL/path label for the public probe walkthrough."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    return _short_text(s, 180)


def _redact_json(obj, depth: int = 0):
    """Clip raw JSON samples for page weight while keeping probe values visible."""
    if depth > 8:
        return "[truncated]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = _redact_json(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_redact_json(x, depth + 1) for x in obj[:50]]
    if isinstance(obj, str):
        return obj if len(obj) <= 700 else obj[:699] + "…"
    return obj


def _agentic_public_json(obj, depth: int = 0):
    """Public preview for the agentic packet.

    Keep URLs/selectors visible because the point is to show what the model
    actually reasons over. Large strings are clipped for page weight.
    """
    if depth > 8:
        return "[truncated]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in {"html", "body", "body_text", "sample", "snippet"}:
                out[k] = _short_text(v, 500)
            else:
                out[k] = _agentic_public_json(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_agentic_public_json(x, depth + 1) for x in obj[:30]]
    if isinstance(obj, str):
        return obj if len(obj) <= 700 else obj[:699] + "…"
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
                items.append([name, st.st_size, st.st_mtime_ns])
            except OSError:
                items.append([name, -1, -1])
    cfg = ROOT / "configs" / f"{slug}.json"
    if cfg.exists():
        try:
            st = cfg.stat()
            items.append(["__config__", st.st_size, st.st_mtime_ns])
        except OSError:
            items.append(["__config__", -1, -1])
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
                st = p.stat()
                items.append([label, st.st_size, st.st_mtime_ns])
            except OSError:
                pass
    for rel in _AGENTIC_MANIFEST_FILES:
        p = ROOT / rel
        if p.exists():
            try:
                st = p.stat()
                items.append([f"__agentic__{rel}", st.st_size, st.st_mtime_ns])
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
                items.append([f"__diag_body_{i}__", st.st_size, st.st_mtime_ns])
            except OSError:
                pass
    return {"slug": slug, "items": items}


def _stat_item(label: str, path: Path) -> list[object]:
    try:
        st = path.stat()
        return [label, st.st_size, st.st_mtime_ns]
    except OSError:
        return [label, -1, -1]


def _har_selection_manifest() -> dict:
    """Cheap cache key for the set of registered probe examples.

    This intentionally uses filesystem stats only. The expensive HAR parsing
    happens only when this key changes or the detail cache is missing.
    """
    items: list[list[object]] = []
    slugs: list[str] = []
    pdir = ROOT / "output" / "probe"
    if pdir.exists():
        for run_dir in sorted(p for p in pdir.iterdir() if p.is_dir()):
            primary = run_dir / "traffic.har"
            if not primary.exists():
                others = sorted(run_dir.glob("traffic*.har"))
                primary = others[0] if others else None
            cfg_path = ROOT / "configs" / f"{run_dir.name}.json"
            if primary is None or not cfg_path.exists():
                continue
            slugs.append(run_dir.name)
            items.append(_stat_item(f"{run_dir.name}/traffic", primary))
            items.append(_stat_item(f"{run_dir.name}/config", cfg_path))
            for name in _HAR_DETAIL_MANIFEST_FILES:
                p = run_dir / name
                if p.exists():
                    items.append(_stat_item(f"{run_dir.name}/{name}", p))
    for rel in (
        "probe/extract.py",
        "engine/digest.py",
        "engine/_mdr_candidates.py",
        "probe/hydration.py",
        "probe/paths.py",
        *_AGENTIC_MANIFEST_FILES,
    ):
        p = ROOT / rel
        if p.exists():
            items.append(_stat_item(f"__source__/{rel}", p))
    return {"version": _HAR_DETAIL_CACHE_VERSION, "slugs": slugs, "items": items}


def pick_har_showcases(top_n: int | None = None) -> list[tuple[str, Path]]:
    """Pick registered probe runs for Figure 4."""
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

    eligible: list[tuple[int, str, Path]] = []
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
        score = 0
        env_path = run_dir / "environment.json"
        if env_path.exists():
            env_data = load_json(env_path)
            src_url = str(env_data.get("url") or env_data.get("source_url") or "")
            if src_url and src_url in recent_ok_urls:
                score += 1
        eligible.append((score, run_dir.name, primary))

    if not eligible:
        return []

    eligible.sort(key=lambda t: (-t[0], t[1]))
    if previous_panel_slug:
        for score, slug, primary in eligible:
            if slug == previous_panel_slug:
                eligible = [(score, slug, primary)] + [
                    item for item in eligible if item[1] != slug
                ]
                break
    picked = eligible if top_n is None else eligible[:top_n]
    return [(slug, primary) for _, slug, primary in picked]


def _row_api(c: dict) -> dict:
    hits = c.get("list_hits") or []
    first = hits[0] if hits else {}
    keys = ", ".join(str(k) for k in (first.get("sample_keys") or [])[:6])
    return {
        "key": _host_mask(c.get("url")),
        "kind": "List JSON API",
        "count": len(hits),
        "type": "api",
        "badge": "List JSON API",
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
        "key": _host_mask(c.get("url")),
        "kind": "Article body JSON",
        "count": c.get("body_len") or 0,
        "type": "body",
        "badge": "Article body JSON",
        "badge_class": "sig-body",
        "host": _host_mask(c.get("url")),
        "meta": (
            f"len={c.get('body_len') or 0} · "
            f"{c.get('method') or '?'} {c.get('status') or '?'} · "
            f"key={c.get('body_key') or '-'} · "
            f"path={_short_text(c.get('body_field_path'), 40)}"
        ),
        "evidence": "Article sample/body details are available in the raw view.",
    }


def _row_simple(c: dict, keys: list[str], signal_type: str, badge: str) -> dict:
    if not c:
        return {"type": signal_type, "badge": badge, "badge_class": f"sig-{signal_type}",
                "key": signal_type, "kind": badge, "count": 0,
                "host": "", "meta": "", "evidence": ""}
    signal_key = _host_mask(c.get("url") or c.get("sample_url") or c.get("url_template"))
    return {
        "key": signal_key or signal_type,
        "kind": badge,
        "count": 1,
        "type": signal_type,
        "badge": badge,
        "badge_class": f"sig-{signal_type}",
        "host": signal_key,
        "meta": " · ".join(
            f"{k}={_host_mask(c.get(k)) if 'url' in k else _short_text(c.get(k), 40)}"
            for k in keys
            if c.get(k) not in (None, "")
        ),
        "evidence": _short_text(c.get("evidence_url") or c.get("evidence"), 180)
                    if (c.get("evidence_url") or c.get("evidence")) else "",
    }


def _lazy_digest_build():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from engine.digest import build_digest
    except Exception:
        return None
    return build_digest


def _lazy_compress_digest_html():
    """The agent-feed digest compressor, so the site can show the EXACT digest
    codex reads (HTML repeat-sibling collapse + long-text/attr caps + 60K slice)
    — not the clean_html build_digest output. Parity with
    generate.codex_agentic._setup_workdir()."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from generate.codex_agentic import _compress_digest_html
    except Exception:
        return None
    return _compress_digest_html


def _digest_signal_rows(*, slug: str, base_url: str, run_dir: Path) -> tuple[list[dict], object, object]:
    build_digest = _lazy_digest_build()
    if build_digest is None:
        return [], None, None
    try:
        digest = build_digest(slug=slug, url=base_url, probe_dir=run_dir)
    except Exception:
        return [], None, None
    rows: list[dict] = []
    site_kind = digest.get("site_kind") or {}
    primary_feed = _host_mask(site_kind.get("primary_feed_url"))
    if primary_feed:
        rows.append({
            "key": "site_kind.primary_feed_url",
            "kind": "Register digest",
            "count": 1,
            "type": "digest",
            "badge": "Register digest",
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
                "key": label,
                "kind": "Register digest",
                "count": 1,
                "type": "digest",
                "badge": "Register digest",
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
        "key": "signal_counts",
        "kind": "Register digest",
        "count": api_n + rss_n + pag_n,
        "type": "digest",
        "badge": "Register digest",
        "badge_class": "sig-digest",
        "host": "—",
        "meta": f"api={api_n} rss={rss_n} pag={pag_n}",
        "evidence": "signal counts",
    })
    notes = digest.get("notes") or []
    if notes:
        rows.append({
            "key": "notes[0]",
            "kind": "Register digest",
            "count": len(notes),
            "type": "digest",
            "badge": "Register digest",
            "badge_class": "sig-digest",
            "host": "—",
            "meta": "recommendation",
            "evidence": _redact_public_text(_short_text(notes[0], 160)),
        })
    def _subset(d: dict) -> dict:
        return {
            "site_kind": d.get("site_kind"),
            "list_html": d.get("list_html"),
            "article_sample": d.get("article_sample"),
            "list_candidates": d.get("list_candidates"),
            "feed_candidates": d.get("feed_candidates"),
        }
    # Model-facing view = the digest AFTER the agent-feed compressor (HTML
    # collapse + 60K cap), kept UNREDACTED so the raw overlay shows the exact
    # bytes codex receives. Inline previews clip it separately for page weight.
    compress = _lazy_compress_digest_html()
    model_facing = None
    if compress is not None:
        try:
            model_facing = _subset(compress(digest, max_html_chars=60_000))
        except Exception:
            model_facing = None
    return rows[:_HAR_DETAIL_SECTION_ROW_CAP], _redact_json(_subset(digest)), model_facing


def build_har_detail(slug: str, har_path: Path) -> dict:
    """Mirror dashboard `har_view.build_har_detail` for one probe run with
    capped raw row counts. The `digest` artifact section is deferred here
    because it requires `engine.digest.build_digest` which we keep out of the
    static generator dependency surface."""
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
        "rows": ([_row_simple(audio, ["host", "base_host", "confidence", "evidence", "sample_url"], "audio", "Audio share")]
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
                 lambda c: _row_simple(c, ["url", "source", "type"], "rss", "RSS / Atom")),
        _section("pagination_hints", "Pagination candidates",
                 "probe.extract.pagination_hints(html, base_url, har)", page_hints,
                 lambda c: _row_simple(c, ["kind", "param", "source", "url_template", "evidence_url"], "pag", "Pagination")),
        audio_section,
    ]
    digest_rows, digest_raw, digest_model_facing = _digest_signal_rows(slug=slug, base_url=base_url, run_dir=run_dir)
    sections.append({
        "key": "digest",
        "title": "Digest allow-list summary",
        "source": "engine.digest.build_digest(...)",
        "rows": digest_rows,
        "total_rows": len(digest_rows),
        "more": 0,
        "raw_redacted": digest_raw,
        "model_facing": digest_model_facing,
    })

    artifact_rows = []
    if isinstance(list_candidates, dict):
        for key in sorted(list_candidates.keys()):
            value = list_candidates[key]
            artifact_rows.append({
                "key": key,
                "kind": type(value).__name__ if value is not None else "null",
                "count": (str(len(value)) if isinstance(value, (list, dict, str)) else ""),
                "preview": _short_text(json.dumps(_redact_json(value), ensure_ascii=False), 180),
            })

    parsed_base = urlparse(base_url) if base_url else None
    path_label = ""
    if parsed_base:
        raw_path = (parsed_base.path or "").rstrip("/")
        if raw_path:
            path_label = raw_path if len(raw_path) <= 30 else raw_path[:29] + "…"
    return {
        "slug": slug,
        "host_label": _short_host(base_url) or "host masked",
        "path_label": path_label,
        "probe_url": base_url,
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


def _read_text_excerpt(path: Path, *, max_chars: int = 1600) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(file unavailable)"
    text = text.strip()
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n..."


def _read_text_full(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(file unavailable)"


def _json_excerpt(obj: object, *, max_chars: int = 1800) -> str:
    text = json.dumps(_agentic_public_json(obj), ensure_ascii=False, indent=2)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n..."


def _json_full(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _clip_text(text: str, *, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n..."


def _asset_name(value: object) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return name.strip("._") or "raw"


_OVERLAY_SEQ = 0


def overlay_button(
    title: str,
    content: object | None = None,
    *,
    label: str = "open full view",
    raw_url: str = "",
) -> str:
    """Full-screen disclosure control for long generated text."""
    global _OVERLAY_SEQ
    _OVERLAY_SEQ += 1
    tid = f"overlay-template-{_OVERLAY_SEQ}"
    raw_attr = f' data-overlay-raw-url="{esc(raw_url)}"' if raw_url else ""
    button = (
        f'<button type="button" class="overlay-open" '
        f'data-overlay-template="{esc(tid)}" data-overlay-title="{esc(title)}"{raw_attr}>'
        f'{esc(label)}</button>'
    )
    if raw_url:
        return button
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(content, ensure_ascii=False, indent=2)
    return f'{button}<template id="{esc(tid)}"><pre>{esc(text)}</pre></template>'


def _find_section(detail: dict, key: str) -> dict:
    for sec in detail.get("sections") or []:
        if sec.get("key") == key:
            return sec
    return {}


def _har_raw_dump(detail: dict) -> dict[str, object]:
    raw_dump: dict[str, object] = {}
    for sec in detail.get("sections") or []:
        key = sec.get("key")
        if key:
            raw_dump[str(key)] = sec.get("raw_redacted")
    return raw_dump


def _render_agentic_user_prompt(slug: str, url: str) -> str:
    prompt_path = ROOT / "prompts" / "register_agent_user.txt"
    tpl = _read_text_excerpt(prompt_path, max_chars=1400)
    return (tpl.replace("{{ slug }}", slug)
               .replace("{{slug}}", slug)
               .replace("{{ url }}", url)
               .replace("{{url}}", url))


def _published_config_summary(slug: str) -> tuple[dict, str]:
    cfg_path = ROOT / "configs" / f"{slug}.json"
    cfg = load_json(cfg_path)
    if not cfg:
        return {}, "(not published yet)"
    interesting = {
        "site": cfg.get("site") or cfg.get("url"),
        "strategy": cfg.get("strategy"),
        "recognizer": cfg.get("recognizer"),
        "list": cfg.get("list"),
        "article": cfg.get("article"),
    }
    return cfg, _json_excerpt({k: v for k, v in interesting.items() if v}, max_chars=1800)


def _artifact_explainer(name: str) -> tuple[str, str]:
    mapping = {
        "traffic.har": (
            "Network requests captured by Playwright.",
            "Shows JSON APIs, feed URLs, redirects, status codes, and body endpoints that static HTML may hide.",
        ),
        "list.html": (
            "Rendered or fetched list-page HTML.",
            "Gives row selectors, article links, titles, dates, and static-vs-browser evidence.",
        ),
        "list_candidates.json": (
            "Probe's extracted list candidates.",
            "Tells the model which row selectors, sample URLs, feeds, pagination hints, and API candidates are grounded in probe output.",
        ),
        "diagnosis.json": (
            "Probe verdict and fetch attempts.",
            "Explains whether static HTTP was enough, browser rendering was needed, or the URL looked blocked/dead.",
        ),
        "feed_candidates.json": (
            "RSS/Atom candidates found from HTML and traffic.",
            "Lets generation choose a feed config instead of brittle HTML selectors when a feed is available.",
        ),
        "environment.json": (
            "Runtime environment metadata.",
            "Useful for debugging probe differences between dev box and N100.",
        ),
        "robots.json": (
            "robots.txt and crawl-delay result.",
            "Informs politeness and whether the crawler should avoid or slow down requests.",
        ),
        "sitemap.json": (
            "Sitemap URLs discovered during probe.",
            "Can reveal article/list URLs when the page itself is sparse.",
        ),
        "article_candidates.json": (
            "Article body extraction candidates.",
            "Shows candidate selectors or API paths for fetching article body text.",
        ),
        "article_click.json": (
            "Browser click simulation result.",
            "Captures resolved URLs when clicking list rows differs from static hrefs.",
        ),
    }
    return mapping.get(name, ("Probe artifact.", "Extra evidence available to the digest or later debugging."))


def build_agentic_packet(detail: dict, *, run_dir: Path | None = None) -> dict:
    """Build the Figure 5 view-model from the selected probe artifact.

    The packet mirrors `generate.codex_agentic._setup_workdir()` without
    creating a real tmpdir. It is regenerated whenever the probe manifest or
    prompt/source files change.
    """
    slug = str(detail.get("slug") or "")
    probe_url = str(detail.get("probe_url") or "")
    summary = detail.get("summary") or {}
    digest_sec = _find_section(detail, "digest")
    digest_raw = digest_sec.get("raw_redacted")
    # model_facing = digest AFTER the agent-feed compressor (the exact bytes
    # codex reads). Fall back to the clean redacted view if the compressor was
    # unavailable at build time.
    digest_model_facing = digest_sec.get("model_facing")
    if digest_raw is None:
        digest_raw = {
            "list_candidates": {
                row.get("key"): row.get("preview")
                for row in ((detail.get("artifact_list_candidates") or {}).get("rows") or [])
            },
            "summary": summary,
        }
    if digest_model_facing is None:
        digest_model_facing = digest_raw
    config_json, config_preview = _published_config_summary(slug)
    config_strategy = str(detail.get("config_strategy") or config_json.get("strategy") or "unknown")
    # Reproduce the real example picks. _pick_examples is deterministic and
    # pure (scores existing configs/ by recognizer/host/strategy, excludes this
    # slug) — same routine register-time uses. Lazy + guarded so the stdlib-only
    # site path still imports when generate.codex_agentic is unavailable.
    picked_manifest: list[dict] = []
    picked_configs: dict[str, object] = {}
    try:
        from generate.codex_agentic import (  # noqa: PLC0415
            _pick_examples as _ca_pick,
            _score_example as _ca_score,
            _example_reason as _ca_reason,
        )
        score_digest = {
            "url": probe_url,
            "recognizer_hint": {"name": config_json.get("recognizer") or ""},
            "strategy_hint": {"strategy": config_strategy},
        }
        for ex_path in _ca_pick(score_digest, ROOT, slug, n=2):
            try:
                ex_cfg = json.loads(ex_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(ex_cfg, dict):
                continue
            picked_manifest.append({
                "slug": ex_path.stem,
                "score": _ca_score(ex_cfg, score_digest),
                "reason": _ca_reason(ex_cfg, score_digest),
            })
            picked_configs[ex_path.name] = ex_cfg
    except Exception:
        picked_manifest = []
        picked_configs = {}
    signal_counts = {
        "har_entries": summary.get("entry_count", 0),
        "json_entries": summary.get("json_count", 0),
        "xhr_fetch": summary.get("xhr_count", 0),
        "traffic_api_candidates": (_find_section(detail, "traffic_api_candidates").get("total_rows") or 0),
        "article_body_api_candidates": (_find_section(detail, "traffic_article_body_candidates").get("total_rows") or 0),
        "rss_candidates": (_find_section(detail, "rss_feed_urls").get("total_rows") or 0),
        "pagination_hints": (_find_section(detail, "pagination_hints").get("total_rows") or 0),
    }
    artifacts: list[dict[str, object]] = []
    if run_dir is not None:
        for name in _HAR_DETAIL_MANIFEST_FILES:
            p = run_dir / name
            if not p.exists():
                continue
            try:
                st = p.stat()
                size = st.st_size
            except OSError:
                size = 0
            artifacts.append({
                "path": f"output/probe/{slug}/{name}" if slug else f"output/probe/<slug>/{name}",
                "name": name,
                "size": size,
                "role": _artifact_explainer(name)[0],
                "why": _artifact_explainer(name)[1],
                "raw_url": f"probe-raw/{slug}/artifacts/{_asset_name(name)}",
                "preview": _read_text_excerpt(p, max_chars=900) if p.suffix in {".json", ".txt"} else f"{size} bytes",
            })

    agentic_agents = _read_text_full(ROOT / "prompts" / "register_agent_AGENTS.md")
    config_writer_rules = _read_text_full(ROOT / "prompts" / "config_writer.system.txt")
    user_prompt = _render_agentic_user_prompt(slug, probe_url)
    digest_packet = {"slug": slug, "url": probe_url, "signal_counts": signal_counts, "digest": digest_model_facing}
    validator_digest_packet = {
        "same_keys_as": "digest.json",
        "html": "uncompressed in the real tmpdir",
        "signal_counts": signal_counts,
    }
    failure_packet = {
        "source": "api_loop_once",
        "attempt": 1,
        "candidate_config": "previous failed config, if any",
        "validation_feedback": "short validator failure text",
        "error": "generation exception text, if any",
    }
    examples_packet = {
        "selection_rule": "top 2 scored configs excluding the current slug",
        "current_strategy": config_strategy,
        "manifest": picked_manifest or [
            {"note": "no config scored > 0 — no recognizer/host/strategy match in configs/"}
        ],
    }
    validator_packet = {
        "launcher": "run_validator.bat on Windows, run_validator.sh elsewhere",
        "python_path": sys.executable,
        "input": "./candidate.json",
        "timing_log": "validate_timing/agentic_attempt__*.json",
    }
    output_packet = {
        "last_json": {
            "ok": True,
            "candidate_path": "./candidate.json",
            "config": {},
            "attempts": [{"i": 1, "validate_ok": True, "error": ""}],
            "stop_reason": "validate_pass",
        },
        "published_config_preview": {
            k: v for k, v in {
                "site": config_json.get("site") or config_json.get("url"),
                "strategy": config_json.get("strategy"),
                "recognizer": config_json.get("recognizer"),
            }.items() if v
        } or config_preview,
    }
    files = [
        {
            "phase": "Prompt",
            "group": "direct",
            "path": "AGENTS.md",
            "source": "prompts/register_agent_AGENTS.md",
            "role": "Read first, every run. System-like local instructions: scope, reading order, self-veto, output contract.",
            "contains": ["read order", "tmpdir-only scope", "self-veto rules", "final JSON contract"],
            "raw": agentic_agents,
            "raw_url": f"probe-raw/{slug}/agentic/AGENTS.md",
            "preview": _clip_text(agentic_agents, max_chars=1800),
        },
        {
            "phase": "Prompt",
            "group": "direct",
            "path": "stdin prompt",
            "source": "prompts/register_agent_user.txt",
            "role": "The actual task text passed to `codex exec` on stdin. Always fed.",
            "contains": ["target slug", "target URL", "short command recipe", "success/failure output shape"],
            "raw": user_prompt,
            "raw_url": f"probe-raw/{slug}/agentic/stdin_prompt.txt",
            "preview": user_prompt,
        },
        {
            "phase": "Evidence",
            "group": "direct",
            "path": "digest.json",
            "source": "engine.digest.build_digest(...) → generate.codex_agentic._compress_digest_html (the exact bytes codex reads)",
            "role": "Read first, every run. Primary model evidence. list_html.html / article_sample.html are prompt-compressed (repeat-sibling collapse + long-text/attr caps) then capped at 60K chars each — identical to the agent's digest.json. Open the raw view to see the real compressed HTML.",
            "contains": ["probe URL", "strategy hints", "list candidates", "article sample (compressed HTML ≤60K)", "traffic/feed/pagination signals"],
            "raw": _json_full(digest_packet),
            "raw_url": f"probe-raw/{slug}/agentic/digest.json",
            "preview": _json_excerpt(digest_packet, max_chars=6000),
        },
        {
            "phase": "Examples",
            "group": "direct",
            "path": "examples/manifest.json",
            "source": "generate.codex_agentic._pick_examples(...)",
            "role": "Read first to choose which examples to open: the 2 closest configs and why each was picked (recognizer/host/strategy score).",
            "contains": ["example slugs", "similarity score", "why each example was picked"],
            "raw": _json_full(examples_packet),
            "raw_url": f"probe-raw/{slug}/agentic/examples_manifest.json",
            "preview": _json_excerpt(examples_packet),
        },
        {
            "phase": "Examples",
            "group": "on_demand",
            "path": "examples/*.json (×2)",
            "source": "2 copied prior configs (closest matches)",
            "role": "Read on demand: the agent opens 1–2 of these (per manifest scores) when authoring the config — not guaranteed to read both.",
            "contains": [f"{name} (full config JSON)" for name in picked_configs]
            or ["no example scored > 0 for this site"],
            "raw": _json_full(picked_configs or {
                "note": "no config scored > 0 — no recognizer/host/strategy match in configs/"
            }),
            "raw_url": f"probe-raw/{slug}/agentic/examples_configs.json",
            "preview": _json_excerpt(picked_configs, max_chars=6000) if picked_configs
            else "no matching example configs (none scored > 0)",
        },
        {
            "phase": "Rules",
            "group": "on_demand",
            "path": "config_writer_rules.txt",
            "source": "prompts/config_writer.system.txt",
            "role": "Read on demand: full config-authoring rules (~25KB). The agent is told to skim it only when uncertain about a field.",
            "contains": ["allowed config schema vocabulary", "strategy-specific rules", "selector/API guidance", "retry constraints"],
            "raw": config_writer_rules,
            "raw_url": f"probe-raw/{slug}/agentic/config_writer_rules.txt",
            "preview": _clip_text(config_writer_rules, max_chars=6000),
        },
        {
            "phase": "Evidence",
            "group": "on_demand",
            "path": "failure_packet.json",
            "source": "scripts/register.py::_build_failure_packet(...)",
            "role": "Conditional: present (and read) only when auto mode first tried api_loop_once and escalated to agentic.",
            "contains": ["previous candidate_config", "validation_feedback", "api_loop_once error", "attempt number"],
            "raw": _json_full(failure_packet),
            "raw_url": f"probe-raw/{slug}/agentic/failure_packet.json",
            "preview": _json_excerpt(failure_packet),
        },
        {
            "phase": "Evidence",
            "group": "tooling",
            "path": "validator_digest.json",
            "source": "same digest before HTML compression",
            "role": "Validator-only — the agent never reads this. Holds full uncompressed HTML so probe-grounding checks use real bytes, not compressed prompt snippets.",
            "contains": ["same keys as digest.json", "uncompressed HTML", "full grounding evidence for validator"],
            "raw": _json_full(validator_digest_packet),
            "raw_url": f"probe-raw/{slug}/agentic/validator_digest.json",
            "preview": _json_excerpt(validator_digest_packet),
        },
        {
            "phase": "Validator",
            "group": "tooling",
            "path": "validate_config.py + run_validator.*",
            "source": "scripts/validate_config.py copied with a platform launcher",
            "role": "Executed, not read as content. The agent runs this against ./candidate.json; the parent validates again after the agent exits.",
            "contains": ["launcher command", "python interpreter path", "validator timing log path", "candidate input path"],
            "raw": _json_full(validator_packet),
            "raw_url": f"probe-raw/{slug}/agentic/validator_handoff.json",
            "preview": _json_excerpt(validator_packet),
        },
        {
            "phase": "Output",
            "group": "tooling",
            "path": "candidate.json + last.json",
            "source": "agent-written tmpdir files",
            "role": "Agent output, not input. candidate.json holds the attempted config; last.json is the tiny final JSON message with ok/attempts/stop_reason.",
            "contains": ["candidate config file", "ok flag", "attempt results", "stop_reason", "published config path"],
            "raw": _json_full(output_packet),
            "raw_url": f"probe-raw/{slug}/agentic/candidate_and_last.json",
            "preview": _json_excerpt(output_packet),
        },
    ]
    raw_text = "\n\n".join(
        [
            "COMMAND",
            f"codex exec -C <tmpdir> --json --output-last-message <tmpdir>/last.json",
            "",
            *[
                f"===== {f['path']} =====\nsource: {f['source']}\n\n{f.get('raw') or f['preview']}"
                for f in files
            ],
        ]
    )
    return {
        "flow": _AGENTIC_PACKET_FLOW,
        "artifacts": artifacts[:8],
        "files": files,
        "raw_text": raw_text,
        "raw_url": f"probe-raw/{slug}/agentic/full_packet.txt",
        "result": {
            "strategy": config_strategy,
            "config_path": f"configs/{slug}.json" if slug else "configs/<slug>.json",
            "raw": _json_full(config_json) if config_json else config_preview,
            "raw_url": f"probe-raw/{slug}/agentic/published_config.json",
            "preview": config_preview,
        },
    }


def read_har_details(*, force_recompute: bool = False) -> dict:
    """Build or read the registered Figure 4 panel payload."""
    def _write_cache(payload: dict) -> None:
        try:
            _HAR_DETAIL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _HAR_DETAIL_CACHE_PATH.with_suffix(_HAR_DETAIL_CACHE_PATH.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, _HAR_DETAIL_CACHE_PATH)
        except OSError:
            pass

    selection_manifest = _har_selection_manifest()
    cached = load_json(_HAR_DETAIL_CACHE_PATH)
    if not force_recompute and isinstance(cached, dict):
        if cached.get("selection_manifest") == selection_manifest:
            return cached
        panels = cached.get("panels") or []
        # Upgrade the pre-v2 cache without reparsing every HAR. This keeps the
        # first deploy after this change from paying the full HAR analysis cost.
        if panels and not cached.get("selection_manifest"):
            cached_slugs = [
                str((p.get("manifest") or {}).get("slug") or "")
                for p in panels if isinstance(p, dict)
            ]
            try:
                current_by_slug = {
                    slug: _manifest_for(ROOT / "output" / "probe" / slug, slug)
                    for slug in cached_slugs if slug
                }
            except (OSError, TypeError):
                current_by_slug = {}
            cached_by_slug = {
                str((p.get("manifest") or {}).get("slug") or ""): p.get("manifest")
                for p in panels if isinstance(p, dict)
            }
            selection_slugs = [str(x) for x in (selection_manifest.get("slugs") or [])]
            if (
                current_by_slug
                and sorted(cached_slugs) == sorted(selection_slugs)
                and cached_by_slug == current_by_slug
            ):
                cached["cache_version"] = _HAR_DETAIL_CACHE_VERSION
                cached["selection_manifest"] = selection_manifest
                _write_cache(cached)
                return cached

    picks = pick_har_showcases(top_n=None)
    if not picks:
        return {
            "cache_version": _HAR_DETAIL_CACHE_VERSION,
            "selection_manifest": selection_manifest,
            "computed_at": datetime.now(KST).isoformat(),
            "panels": [],
        }
    manifests = [_manifest_for(har_path.parent, slug) for slug, har_path in picks]
    if (
        not force_recompute
        and isinstance(cached, dict)
        and cached.get("cache_version") == _HAR_DETAIL_CACHE_VERSION
        and [p.get("manifest") for p in (cached.get("panels") or [])] == manifests
    ):
        cached["cache_version"] = _HAR_DETAIL_CACHE_VERSION
        cached["selection_manifest"] = selection_manifest
        _write_cache(cached)
        return cached
    panels = []
    for i, ((slug, har_path), manifest) in enumerate(zip(picks, manifests)):
        detail = build_har_detail(slug, har_path)
        detail["agentic_packet"] = build_agentic_packet(detail, run_dir=har_path.parent)
        panels.append({
            "panel_id": f"har-panel-{i}",
            "agentic_panel_id": f"agentic-panel-{i}",
            "host_label": detail.get("host_label") or "host masked",
            "manifest": manifest,
            "detail": detail,
        })
    payload = {
        "cache_version": _HAR_DETAIL_CACHE_VERSION,
        "selection_manifest": selection_manifest,
        "computed_at": datetime.now(KST).isoformat(),
        "panels": panels,
    }
    _write_cache(payload)
    return payload


def write_probe_raw_assets(site_dir: Path, har_detail: dict | None) -> None:
    panels = (har_detail or {}).get("panels") or []
    raw_root = site_dir / "probe-raw"
    manifest = {
        "cache_version": _HAR_DETAIL_CACHE_VERSION,
        # Include the renderer signature so raw assets regenerate when the
        # script that builds their content changes — not only when the probe
        # artifacts change. Mirrors write_probe_panel_assets.
        "script": _stat_item("__render__/scripts/generate_site.py", ROOT / "scripts" / "generate_site.py"),
        "panels": len(panels),
        "items": [
            {"slug": (panel.get("manifest") or {}).get("slug"), "panel": panel.get("manifest") or {}}
            for panel in panels
        ],
    }
    manifest_path = raw_root / "manifest.json"
    try:
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    except (OSError, json.JSONDecodeError):
        old_manifest = None
    if old_manifest == manifest:
        return

    operations: list[tuple[str, str, Path | None, str | None]] = []

    def _write_text_if_changed(dst: Path, text: str) -> None:
        data = text.encode("utf-8")
        try:
            if dst.exists():
                st = dst.stat()
                if st.st_size == len(data) and hashlib.sha256(dst.read_bytes()).digest() == hashlib.sha256(data).digest():
                    return
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
        except OSError:
            pass

    def _copy_if_changed(src: Path, dst: Path, url: str) -> None:
        try:
            if not src.exists():
                return
            st = src.stat()
            if dst.exists():
                dst_st = dst.stat()
                if dst_st.st_size == st.st_size and dst_st.st_mtime_ns == st.st_mtime_ns:
                    return
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError:
            pass

    def _track_copy(url: str, src: Path, fallback_text: str = "") -> None:
        if not url:
            return
        try:
            if src.exists():
                operations.append(("copy", url, src, None))
                return
        except OSError:
            pass
        _track_text(url, fallback_text)

    def _track_text(url: str, text: str) -> None:
        if not url:
            return
        operations.append(("text", url, None, text))

    for panel in panels:
        detail = panel.get("detail") or {}
        slug = str(detail.get("slug") or "")
        if not slug:
            continue
        packet = detail.get("agentic_packet") or {}
        _track_text(
            f"probe-raw/{slug}/har_signals.json",
            json.dumps(_har_raw_dump(detail), ensure_ascii=False, indent=2),
        )
        for item in packet.get("artifacts") or []:
            raw_url = str(item.get("raw_url") or "")
            rel_path = str(item.get("path") or "")
            if not raw_url or not rel_path:
                continue
            src = ROOT / rel_path
            _track_copy(raw_url, src, str(item.get("preview") or ""))
        for f in packet.get("files") or []:
            raw_url = str(f.get("raw_url") or "")
            _track_text(raw_url, str(f.get("raw") or ""))
        _track_text(str(packet.get("raw_url") or ""), str(packet.get("raw_text") or ""))
        result = packet.get("result") or {}
        _track_text(
            str(result.get("raw_url") or ""),
            str(result.get("raw") or result.get("preview") or ""),
        )

    try:
        raw_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for kind, url, src, text in operations:
        dst = site_dir / url
        if kind == "copy" and src is not None:
            _copy_if_changed(src, dst, url)
        elif kind == "text":
            _write_text_if_changed(dst, text or "")
    _write_text_if_changed(manifest_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))


def write_probe_panel_assets(site_dir: Path, har_detail: dict | None) -> None:
    panels = (har_detail or {}).get("panels") or []
    panel_root = site_dir / "probe-panels"
    script_path = ROOT / "scripts" / "generate_site.py"
    script_sig = _stat_item("__render__/scripts/generate_site.py", script_path)
    manifest_items = [
        {
            "url": f"probe-panels/probe-agent-panel-{i}.html",
            "panel": panel.get("manifest") or {},
            "script": script_sig,
        }
        for i, panel in enumerate(panels)
    ]
    manifest = {"panels": len(panels), "items": manifest_items}
    manifest_path = panel_root / "manifest.json"
    try:
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    except (OSError, json.JSONDecodeError):
        old_manifest = None
    if old_manifest == manifest:
        return
    try:
        panel_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for i, panel in enumerate(panels):
        html_fragment = _render_probe_agentic_panel(panel, panel_index=i, hidden=False)
        dst = panel_root / f"probe-agent-panel-{i}.html"
        data = html_fragment.encode("utf-8")
        try:
            if dst.exists():
                st = dst.stat()
                if st.st_size == len(data) and hashlib.sha256(dst.read_bytes()).digest() == hashlib.sha256(data).digest():
                    continue
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
        except OSError:
            pass
    try:
        tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(tmp, manifest_path)
    except OSError:
        pass


def _placeholder_har_panel() -> dict:
    return {
        "panel_id": "har-panel-0",
        "host_label": "No probe artifact",
        "detail": {
            "host_label": "No probe artifact",
            "path_label": "",
            "probe_url": "",
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
    multi = len(panels) > 1
    options_parts: list[str] = []
    for i, panel in enumerate(panels):
        detail = panel.get("detail") or {}
        host_label = panel.get("host_label") or "site"
        path_label = detail.get("path_label") or ""
        verdict = detail.get("verdict") or ""
        bits = [host_label]
        if path_label:
            bits[-1] = f"{host_label}{path_label}"
        if multi:
            bits.append(f"#{i + 1}")
        if verdict:
            bits.append(verdict if len(verdict) <= 28 else verdict[:27] + "…")
        options_parts.append(
            f'<option value="{esc(panel["panel_id"])}">{esc(" · ".join(bits))}</option>'
        )
    options = "".join(options_parts)
    panel_html = "".join(
        _render_har_detail_panel(panel, hidden=i != 0)
        for i, panel in enumerate(panels)
    )
    return (
        '<label class="har-picker">Probe site '
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

    probe_url = detail.get("probe_url") or ""
    host_label = detail.get("host_label") or "host masked"
    path_label = detail.get("path_label") or ""
    site_display = f"{host_label}{path_label}" if path_label else host_label
    if probe_url:
        site_dd = (
            f'<a href="{esc(probe_url)}" target="_blank" rel="noopener noreferrer">'
            f'<code>{esc(site_display)}</code></a>'
        )
    else:
        site_dd = f'<code>{esc(site_display)}</code>'
    meta_dl = (
        '<div class="har-meta-grid">'
        f'<div class="har-meta-item"><span>site</span><strong>{site_dd}</strong></div>'
        f'<div class="har-meta-item"><span>HAR mtime</span><strong><code>{esc(detail["har_mtime"] or "—")}</code></strong></div>'
        f'<div class="har-meta-item"><span>verdict</span><strong>{esc(detail["verdict"] or "—")}</strong></div>'
        f'<div class="har-meta-item"><span>config strategy</span><strong><code>{esc(detail["config_strategy"] or "—")}</code></strong></div>'
        "</div>"
        '<details class="har-meta-extra">'
        '<summary>more</summary>'
        '<div class="har-meta-grid compact">'
        f'<div class="har-meta-item"><span>probe host</span><strong><code>{esc(detail["probe_host"] or "—")}</code></strong></div>'
        f'<div class="har-meta-item"><span>first article host</span><strong><code>{esc(detail["article_host"] or "—")}</code></strong></div>'
        "</div></details>"
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
        section_key = sec["key"]
        raw_dump[section_key] = sec.get("raw_redacted")
        for idx, row in enumerate(sec.get("rows") or []):
            item = dict(row)
            if section_key != "digest":
                item["key"] = f"{section_key}[{idx}]"
            item.setdefault("kind", item.get("badge") or sec.get("title") or section_key)
            item.setdefault("count", item.get("total_rows") or item.get("count") or 1)
            signal_rows.append(item)
        if sec.get("more"):
            signal_rows.append({
                "key": section_key,
                "kind": sec["title"],
                "count": sec["more"],
                "badge": "MORE",
                "badge_class": "sig-empty",
                "host": "—",
                "meta": sec["title"],
                "evidence": f"+{sec['more']} more rows not shown",
            })
    present = {r.get("type") for r in signal_rows}
    for signal_type, badge in (
        ("api", "List JSON API"), ("body", "Article body JSON"),
        ("rss", "RSS / Atom"), ("pag", "Pagination"), ("audio", "Audio share"),
    ):
        if signal_type not in present:
            signal_rows.append({
                "key": signal_type,
                "kind": badge,
                "count": 0,
                "type": signal_type,
                "badge": badge,
                "badge_class": f"sig-{signal_type} sig-empty",
                "host": "—",
                "meta": "Not detected for this probe.",
                "evidence": "—",
            })
    if "digest" not in present:
        signal_rows.append({
            "key": "digest",
            "kind": "Register digest",
            "count": 0,
            "type": "digest",
            "badge": "Register digest",
            "badge_class": "sig-digest sig-empty",
            "host": "—",
            "meta": "Not detected for this probe.",
            "evidence": "—",
        })
    artifact = detail.get("artifact_list_candidates") or {}
    artifact_rows = artifact.get("rows") or []
    if artifact_rows:
        for row in artifact_rows:
            signal_rows.append({
                "key": row.get("key", ""),
                "kind": row.get("kind", "stored"),
                "count": row.get("count") or "—",
                "type": "stored",
                "badge": "Stored probe summary",
                "badge_class": "sig-stored",
                "host": "—",
                "meta": f"{row.get('key', '')} · {row.get('kind', '')}"
                        + (f" (n={row['count']})" if row.get('count') else ""),
                "evidence": _short_text(row.get("preview"), 160),
            })
    else:
        signal_rows.append({
            "key": "list_candidates.json",
            "kind": "Stored probe summary",
            "count": 0,
            "type": "stored",
            "badge": "Stored probe summary",
            "badge_class": "sig-stored sig-empty",
            "host": "—",
            "meta": "list_candidates.json not stored for this probe.",
            "evidence": "—",
        })
    body = (
        '<div class="packet-scroll har-signal-scroll">'
        '<table class="har-signal-table"><thead>'
        '<tr><th>key</th><th>type</th><th>count</th><th>preview</th></tr>'
        '</thead><tbody>'
    )
    for item in signal_rows:
        empty_cls = " sig-empty" if "sig-empty" in str(item.get("badge_class")) else ""
        meta = str(item.get("meta") or "")
        evidence = str(item.get("evidence") or "")
        key = str(item.get("key") or item.get("host") or item.get("badge") or "—")
        kind = str(item.get("kind") or item.get("badge") or item.get("type") or "—")
        count = str(item.get("count") if item.get("count") not in (None, "") else "—")
        preview = " · ".join(x for x in (meta, evidence) if x and x != "—") or "—"
        tip_html = (
            f'<div class="packet-pop-row"><b>key</b><code>{esc(key)}</code></div>'
            f'<div class="packet-pop-row"><b>type</b>{esc(kind)}</div>'
            f'<div class="packet-pop-row"><b>count</b>{esc(count)}</div>'
            f'<div class="packet-pop-row"><b>host</b><code>{esc(item.get("host") or "—")}</code></div>'
            f'<div class="packet-pop-row"><b>meta</b>{esc(meta or "—")}</div>'
            f'<div class="packet-pop-row"><b>evidence</b>{esc(evidence or "—")}</div>'
        )
        body += (
            f'<tr class="har-signal-row{empty_cls}" tabindex="0" data-tip-html="{esc(tip_html)}">'
            '<td class="har-signal-key">'
            f'<code>{esc(key)}</code>'
            '</td>'
            f'<td><span class="sig-badge {esc(item["badge_class"])}">{esc(kind)}</span></td>'
            f'<td>{esc(count)}</td>'
            f'<td><small>{esc(_short_text(preview, 180))}</small></td>'
            '</tr>'
        )
    body += "</tbody></table></div>"
    raw_pre = json.dumps(raw_dump, ensure_ascii=False, indent=2) if raw_dump else "(empty)"
    slug = str(detail.get("slug") or "")
    raw_url = f"probe-raw/{slug}/har_signals.json" if slug else ""
    raw_block = (
        '<div class="overlay-action-row">'
        f'{overlay_button("HAR signals raw JSON", raw_pre, label="open raw signals", raw_url=raw_url)}'
        "</div>"
    )
    hidden_attr = " hidden" if hidden else ""
    return (
        f'<div class="har-detail-panel" id="{esc(panel["panel_id"])}"{hidden_attr}>'
        f"{kpis}{meta_dl}{ct_block}{body}{raw_block}</div>"
    )


def render_probe_agentic_html(payload: dict | None) -> str:
    panels = (payload or {}).get("panels") or []
    if not panels:
        panels = [_placeholder_har_panel()]
    multi = len(panels) > 1
    options_parts: list[str] = []
    for i, panel in enumerate(panels):
        detail = panel.get("detail") or {}
        host_label = panel.get("host_label") or "site"
        path_label = detail.get("path_label") or ""
        probe_url = detail.get("probe_url") or ""
        verdict = detail.get("verdict") or ""
        bits = [f"{host_label}{path_label}" if path_label else host_label]
        if multi:
            bits.append(f"#{i + 1}")
        if verdict:
            bits.append(verdict if len(verdict) <= 28 else verdict[:27] + "…")
        panel_id = f"probe-agent-panel-{i}"
        search_text = " ".join(
            str(x) for x in (probe_url, host_label, path_label, detail.get("slug") or "", verdict)
            if x
        )
        options_parts.append(
            f'<option value="{esc(panel_id)}" data-url="{esc(probe_url)}" '
            f'data-panel-url="probe-panels/{esc(panel_id)}.html" '
            f'data-search="{esc(search_text.lower())}">{esc(" · ".join(bits))}</option>'
        )
    panel_html = _render_probe_agentic_panel(panels[0], panel_index=0, hidden=False)
    count_label = f"{len(panels)} registered probe examples"
    return (
        '<div class="har-picker probe-agent-picker">'
        '<label>Search URL '
        '<input id="probeAgentSearch" type="search" placeholder="type URL, host, or slug" autocomplete="off"></label>'
        '<label>URL example '
        f'<select id="probeAgentPicker">{"".join(options_parts)}</select></label>'
        f'<a id="probeAgentOpenUrl" class="probe-agent-url" href="#" target="_blank" rel="noopener noreferrer">open URL</a>'
        f'<span id="probeAgentCount" class="probe-agent-count">{esc(count_label)}</span>'
        '</div>'
        f'<div id="probeAgentPanelHost">{panel_html}</div>'
    )


def render_agentic_packet_html(payload: dict | None) -> str:
    return render_probe_agentic_html(payload)


def _render_probe_agentic_panel(panel: dict, *, panel_index: int, hidden: bool) -> str:
    hidden_attr = " hidden" if hidden else ""
    return (
        f'<div class="probe-agent-panel" id="probe-agent-panel-{esc(panel_index)}"{hidden_attr}>'
        '<div class="probe-agent-grid">'
        '<section class="probe-agent-column">'
        '<h4>Probe and HAR signals</h4>'
        f'{_render_har_detail_panel(panel, hidden=False)}'
        '</section>'
        '<section class="probe-agent-column">'
        '<h4>Agentic config packet</h4>'
        f'{_render_agentic_packet_panel(panel, hidden=False)}'
        '</section>'
        '</div>'
        '</div>'
    )


def _render_agentic_packet_panel(panel: dict, *, hidden: bool) -> str:
    detail = panel.get("detail") or {}
    packet = detail.get("agentic_packet") or {
        "flow": _AGENTIC_PACKET_FLOW,
        "artifacts": [],
        "files": [],
        "result": {"strategy": "—", "config_path": "configs/<slug>.json", "preview": "(no selected probe)"},
    }
    hidden_attr = " hidden" if hidden else ""
    panel_id = panel.get("agentic_panel_id") or str(panel.get("panel_id") or "agentic-panel-0").replace("har-", "agentic-")
    flow_html = "".join(
        f'<li tabindex="0" data-tip-html="{esc(body)}">'
        f'<span class="packet-step-num">{esc(n)}</span>'
        f'<strong>{esc(title)}</strong>'
        '</li>'
        for n, title, body in (packet.get("flow") or [])
    )
    def _group_head(label: str) -> str:
        return f'<tr class="packet-group-head"><td colspan="4">{esc(label)}</td></tr>'

    input_rows = ""
    artifacts = packet.get("artifacts") or []
    if artifacts:
        input_rows += _group_head("프로브 산출물 — digest 로 접힘 (모델 직접 입력 아님)")
    for item in artifacts:
        preview = str(item.get("preview") or "")
        raw_url = str(item.get("raw_url") or "")
        key = str(item.get("name") or item.get("path") or "")
        tip_html = (
            f'<div class="packet-pop-row"><b>path</b><code>{esc(item.get("path") or "")}</code></div>'
            f'<div class="packet-pop-row"><b>contains</b>{esc(item.get("role") or "")}</div>'
            f'<div class="packet-pop-row"><b>used for</b>{esc(item.get("why") or "")}</div>'
        )
        input_rows += (
            f'<tr class="packet-input-row" tabindex="0" data-tip-html="{esc(tip_html)}">'
            '<td class="packet-key-cell">'
            f'{overlay_button(str(item.get("path") or "probe artifact"), label=key, raw_url=raw_url)}'
            '</td>'
            '<td><span class="badge">probe</span></td>'
            f'<td>{esc(str(item.get("size")) + " bytes" if item.get("size") else "—")}</td>'
            f'<td><small>{esc(_short_text(preview, 180))}</small></td>'
            "</tr>"
        )

    # Staged tmpdir files grouped by how the agent uses them (AGENTS.md WORKFLOW):
    # direct = read first every run, on_demand = read only when needed/present,
    # tooling = executed or written, never read by the model as content.
    group_labels = [
        ("direct", "① 직접 입력 — 항상 읽음 (every run)"),
        ("on_demand", "② 필요할 때 조회 — 조건부 (on-demand)"),
        ("tooling", "③ 도구·산출 — 모델이 콘텐츠로 안 읽음"),
    ]
    files = packet.get("files") or []
    by_group: dict[str, list] = {}
    for f in files:
        by_group.setdefault(str(f.get("group") or "direct"), []).append(f)
    ordered = [g for g, _ in group_labels] + [g for g in by_group if g not in dict(group_labels)]
    label_map = dict(group_labels)
    for g in ordered:
        group_files = by_group.get(g)
        if not group_files:
            continue
        input_rows += _group_head(label_map.get(g, g))
        for f in group_files:
            contains_text = ", ".join(str(x) for x in (f.get("contains") or []))
            raw_url = str(f.get("raw_url") or "")
            preview = str(f.get("preview") or "")
            tip_html = (
                f'<div class="packet-pop-row"><b>source</b><code>{esc(f.get("source") or "")}</code></div>'
                f'<div class="packet-pop-row"><b>contains</b>{esc(f.get("role") or "")}</div>'
                f'<div class="packet-pop-row"><b>subfields</b>{esc(contains_text or "—")}</div>'
            )
            input_rows += (
                f'<tr class="packet-input-row" tabindex="0" data-tip-html="{esc(tip_html)}">'
                '<td class="packet-key-cell">'
                f'{overlay_button(str(f.get("path") or "staged file"), label=str(f.get("path") or ""), raw_url=raw_url)}'
                '</td>'
                f'<td><span class="packet-phase">{esc(f.get("phase") or "")}</span></td>'
                f'<td>{esc(str(len((f.get("raw") or "").encode("utf-8"))) + " bytes")}</td>'
                f'<td><small>{esc(_short_text(preview, 180))}</small></td>'
                "</tr>"
            )
    if not input_rows:
        input_rows = '<tr><td colspan="4">No probe artifact or agentic packet available for this probe.</td></tr>'

    result = packet.get("result") or {}
    result_preview = str(result.get("preview") or "")
    raw_text = str(packet.get("raw_text") or "")
    raw_overlay_url = str(packet.get("raw_url") or "")
    result_overlay_url = str(result.get("raw_url") or "")
    return (
        f'<div class="agentic-packet-panel" id="{esc(panel_id)}"{hidden_attr}>'
        '<ol class="packet-flow">'
        f'{flow_html}'
        '</ol>'
        '<section class="packet-subsection">'
        '<h4>Model input packet</h4>'
        '<p class="packet-help">에이전트 tmpdir 에 실제로 깔리는 파일. <b>①직접 입력</b>=매 run 먼저 읽음, <b>②필요할 때 조회</b>=조건부, <b>③도구·산출</b>=모델이 콘텐츠로 안 읽음. digest.json 의 HTML 은 모델이 받는 그대로 (compress + 60K). 행 hover=필드 의미, key 클릭=raw 전체.</p>'
        '<div class="packet-scroll packet-input-scroll">'
        '<table class="packet-field-table packet-input-table"><thead><tr><th>key</th><th>type</th><th>size</th><th>preview</th></tr></thead>'
        f'<tbody>{input_rows}</tbody></table></div>'
        '</section>'
        '<section class="packet-subsection packet-raw">'
        '<h4>Raw text view</h4>'
        '<p>One full-screen bundle: command shape, stdin prompt, JSON evidence, rules, validator handoff, and expected output contract.</p>'
        f'{overlay_button("Full staged agentic packet", label="open raw packet", raw_url=raw_overlay_url)}'
        '</section>'
        '<section class="packet-subsection packet-result">'
        '<h4>Result path</h4>'
        f'<p>The agent writes <code>candidate.json</code>; the parent re-validates it and publishes '
        f'<code>{esc(result.get("config_path") or "configs/<slug>.json")}</code>. '
        f'Current published strategy: <code>{esc(result.get("strategy") or "—")}</code>.</p>'
        f'{overlay_button("Published config summary", label="open config summary", raw_url=result_overlay_url)}'
        '</section>'
        '</div>'
    )


def metric(label: str, value: object, note: str = "") -> str:
    note_html = f"<span>{esc(note)}</span>" if note else ""
    return f'<div class="metric"><strong>{esc(value)}</strong><em>{esc(label)}</em>{note_html}</div>'


# Public-facing "trust but verify" guardrail explainer — mirrors
# docs/최종발표/2-3_자동생성_해부.md §2.8. The config generator is an AI agent that
# may never touch the repo: it writes a candidate in a tmpdir, the parent
# re-validates, then publishes. Source line anchors are best-effort (same caveat
# as GITHUB_BASE); update when codex_agentic.py / validate.py / register.py move.
GUARDRAIL_FOLDS = [
    ("Isolation",
     "The agent runs in a repo-external temp folder, staged with only the inputs it "
     "needs, and can write only <code>./candidate.json</code>. Publishing is the "
     "parent's job &mdash; so any write into the repo is itself a violation signal."),
    ("Tamper detection (hash)",
     "The parent fingerprints every protected file (SHA256 + size + mtime) before and "
     "after the run. Any change outside the temp folder is caught &mdash; a hash diff "
     "catches even a silent edit, and it holds on any OS."),
    ("Independent re-validation",
     "The parent ignores the agent's own <code>ok=true</code> and re-runs the validator "
     "itself: fresh fetch, hard checks, selector grounding. The agent is never the final "
     "authority on its own output."),
]

GUARDRAIL_LAYERS = [
    {
        "tag": "L0", "name": "tmpdir sandbox",
        "what": "Create a repo-external temp folder, stage only the needed inputs, and "
                "let the agent write only <code>./candidate.json</code>.",
        "file": "generate/codex_agentic.py", "line": 590, "fn": "_setup_workdir",
        "why": "Publishing belongs to the parent, so a write into the repo is read as a "
               "breach, not a result.",
    },
    {
        "tag": "L2", "name": "SHA256 audit",
        "what": "Diff SHA256 + size + mtime fingerprints of protected files taken before "
                "and after the codex run.",
        "file": "generate/codex_agentic.py", "line": 237,
        "fn": "_audit_snapshot_paths · _audit_diff",
        "why": "The real enforcement. The OS-level sandbox is bypassed (the in-loop "
               "validator needs real network), so this OS-independent hash diff is the "
               "actual trust boundary &mdash; and it catches even a silent edit.",
    },
    {
        "tag": "L3", "name": "AUDIT_FAIL = security incident",
        "what": "An out-of-tree write returns <code>rc=-4</code>, writes a "
                "<code>.BUG.json</code>, and DMs the owner.",
        "file": "generate/codex_agentic.py", "line": 197,
        "fn": "AuditFailError · register.py _save_bug",
        "why": "A breached trust boundary is a security incident &mdash; escalated to a "
               "human, not retried as if the site merely failed.",
    },
    {
        "tag": "L4", "name": "parent re-validation",
        "what": "Ignore the agent's <code>ok=true</code> and re-run "
                "<code>validate_built_config</code> from scratch: fresh fetch, hard "
                "checks, selector grounding.",
        "file": "generate/validate.py", "line": 380, "fn": "validate_built_config",
        "why": "The trust anchor. The agent's self-check may have run on compressed HTML "
               "or a truncated response.",
    },
    {
        "tag": "L5", "name": "per-slug lock",
        "what": "Serialize the whole generate + audit window with a flock keyed on the "
                "slug.",
        "file": "generate/codex_agentic.py", "line": 457, "fn": "_per_slug_lock",
        "why": "The before/after snapshot only means something if nothing else touches "
               "the files mid-run.",
    },
    {
        "tag": "L6", "name": "atomic publish",
        "what": "Only after re-validation passes: write a tmpfile in the same directory, "
                "then <code>Path.replace</code> (atomic rename).",
        "file": "scripts/register.py", "line": 3927, "fn": "tempfile + Path.replace",
        "why": "A polling worker can never observe a half-written config.",
    },
]


def render_guardrail_html() -> str:
    folds = "".join(
        f'<div class="guard-fold"><h3>{title}</h3><p>{body}</p></div>'
        for title, body in GUARDRAIL_FOLDS
    )
    layers = []
    for layer in GUARDRAIL_LAYERS:
        href = f"{GITHUB_BASE}/{layer['file']}#L{layer['line']}"
        ref = f"{layer['file']}:{layer['line']}"
        layers.append(
            '<li class="guard-layer">'
            f'<span class="guard-tag">{layer["tag"]}</span>'
            '<div class="guard-main">'
            f'<p class="guard-name">{layer["name"]}</p>'
            f'<p class="guard-what">{layer["what"]}</p>'
            f'<p class="guard-ref"><a href="{href}" target="_blank" '
            f'rel="noopener noreferrer">{ref}</a> '
            f'<span class="guard-fn">{layer["fn"]}</span></p>'
            f'<p class="guard-why">{layer["why"]}</p>'
            "</div></li>"
        )
    layers_html = "".join(layers)
    return f"""  <section class="guard-section" aria-labelledby="guardrail">
    <h2 id="guardrail">Agent guardrail &mdash; trust, but verify</h2>
    <p class="lead">The config generator is an AI agent: non-deterministic, and it makes
      live network calls. We let it write production scraping config, yet it never touches
      the real repo. It works inside a throwaway temp folder and writes only a
      <em>candidate</em> file; the parent process then re-validates that candidate
      independently before publishing. Three properties make that safe.</p>
    <div class="guard-core">{folds}</div>
    <ol class="guard-layers">{layers_html}</ol>
    <p class="meta guard-model">Model <code>codex:gpt-5.4-mini</code> (reasoning effort
      <code>low</code>), run in <code>auto</code> mode &mdash; a cheap 1-shot first,
      escalated to the multi-turn agent only when it fails. The numbering keeps the
      internal L0&ndash;L6 labels; L1 is the OS-level sandbox, folded into L2 above
      because it is bypassed in practice.</p>
  </section>
"""


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

    watch_icicle_svg = svg_watch_icicle(WATCH_CALL_TREE)
    har_funnel_svg = svg_har_funnel()
    har_stage_panels_html = render_stage_panels()
    probe_agentic_html = render_probe_agentic_html(har_detail)
    guardrail_html = render_guardrail_html()

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
      max-width: 1140px;
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
    /* Figure 3 — /watch call icicle */
    .watch-icicle-wrap {{ overflow-x: auto; margin: 0 0 12px; }}
    #watchIcicle {{ display: block; min-width: 720px; max-width: 100%; height: auto; }}
    .icicle-node {{ cursor: pointer; }}
    .icicle-box {{ transition: filter 120ms, stroke-width 120ms; }}
    .icicle-node:hover .icicle-box {{ filter: brightness(1.08); stroke-width: 2.4; }}
    .icicle-node.branch {{ opacity: 0.92; }}
    .icicle-file  {{ fill: #fff; font: 600 10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; pointer-events: none; }}
    .icicle-fn    {{ fill: #f4ece0; font: 400 9px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; pointer-events: none; }}
    .icicle-label {{ fill: #fff; font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; pointer-events: none; }}
    .icicle-tag   {{ fill: var(--accent-2); font: italic 9px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; pointer-events: none; }}
    .icicle-exit  {{ fill: var(--accent); font: 600 10px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; pointer-events: none; }}
    .icicle-legend {{ fill: var(--muted); font: 600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    /* GitHub deep-link wrappers — kill underline; icicle hover already signals interactivity. */
    #watchIcicle a {{ text-decoration: none; outline: none; }}
    #watchIcicle a:focus-visible .icicle-box {{ stroke: var(--accent); stroke-width: 2.6; }}
    /* figcaption lane swatches */
    .lane-swatch {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: middle; margin: -2px 2px 0; }}
    .lane-swatch.lane-bot {{ background: #3d737f; }}
    .lane-swatch.lane-worker {{ background: #6f7f52; }}
    .lane-swatch.lane-subprocess {{ background: #8a6f4d; }}
    /* Figure 3b — legacy probe + register decide funnel (TEMP, paired with icicle) */
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
    .stage-flow {{ border-left: 1px solid var(--line); padding: 0 0 0 18px; margin: 0; list-style: none; }}
    .step-row {{ display: flex; gap: 12px; margin: 0 0 14px; }}
    .step-num {{ width: 24px; height: 24px; margin-left: -31px; border-radius: 50%; background: var(--panel); border: 1px solid var(--accent); text-align: center; line-height: 22px; font: 700 0.9rem Georgia, "Times New Roman", serif; color: var(--accent); flex: 0 0 24px; }}
    .step-body {{ min-width: 0; flex: 1; }}
    .step-file {{ display: inline; font: 600 0.82rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--ink); word-break: break-all; overflow-wrap: anywhere; }}
    .step-sep {{ color: var(--muted); margin: 0 6px; }}
    .step-fn {{ display: inline; font: 0.78rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--accent); word-break: break-all; overflow-wrap: anywhere; }}
    .step-role {{ margin: 4px 0 0; font-size: 0.8rem; color: var(--muted); line-height: 1.4; }}
    /* Scoped section-gap tokens (codex v4 review §8 — global selector over-fires). */
    main > section + section {{ margin-top: var(--section-gap, 36px); }}
    #figures figure + figure {{ margin-top: var(--subsection-gap, 22px); }}
    #probeAgenticFigure {{ margin-top: var(--section-gap, 36px); }}
    #probeAgenticFigure .har-section + .har-section {{ margin-top: var(--subsection-gap, 22px); }}
    /* Figure 4 — live HAR detail */
    #probeAgenticFigure {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 18px 22px 14px;
      margin-left: 0;
      margin-right: 0;
    }}
    #probeAgenticFigure > h3 {{
      margin: 0 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.2rem;
    }}
    .figure-lead {{
      color: var(--muted);
      font-size: 0.94rem;
      line-height: 1.55;
      margin: 0 0 14px;
    }}
    #probeAgenticFigure figcaption {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.55;
    }}
    .har-kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
      gap: 10px;
      margin: 0 0 16px;
    }}
    .har-kpis .kpi {{
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
    .har-meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 10px;
      margin: 0 0 18px;
      font-size: 0.9rem;
    }}
    .har-meta-grid.compact {{ margin-top: 10px; }}
    .har-meta-item {{
      border: 1px solid var(--line);
      border-radius: 5px;
      background: var(--paper);
      padding: 8px 10px;
      min-width: 0;
    }}
    .har-meta-item span {{
      display: block;
      color: var(--muted);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      margin-bottom: 4px;
    }}
    .har-meta-item strong {{
      display: block;
      font-weight: 500;
      line-height: 1.4;
      overflow-wrap: anywhere;
    }}
    .har-picker {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .har-picker label {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .har-picker select,
    .har-picker input {{
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--ink);
      padding: 5px 8px;
      border-radius: 4px;
    }}
    .probe-agent-picker input {{ width: min(360px, 80vw); }}
    .probe-agent-picker select {{ width: min(520px, 88vw); }}
    .probe-agent-url {{
      color: var(--accent);
      border: 1px solid var(--line);
      background: var(--paper);
      border-radius: 4px;
      padding: 4px 9px;
      text-decoration: none;
      font-weight: 600;
    }}
    .probe-agent-url[aria-disabled="true"] {{
      color: var(--muted);
      pointer-events: none;
    }}
    .probe-agent-count {{ font-size: 0.82rem; }}
    .har-detail-panel {{ margin-top: 4px; }}
    .probe-agent-grid {{
      display: block;
    }}
    .probe-agent-column {{
      min-width: 0;
    }}
    .probe-agent-column + .probe-agent-column {{
      margin-top: 26px;
      padding-top: 20px;
      border-top: 1px solid var(--line);
    }}
    .probe-agent-column > h4 {{
      margin: 0 0 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1rem;
    }}
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
    .har-signal-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      table-layout: fixed;
    }}
    .har-signal-table th,
    .har-signal-table td {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      vertical-align: middle;
      padding: 5px 8px;
      border-bottom: 1px solid var(--line);
    }}
    .har-signal-table th {{
      text-align: left;
      color: var(--muted);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .har-signal-table th:nth-child(1) {{ width: 22%; }}
    .har-signal-table th:nth-child(2) {{ width: 28%; }}
    .har-signal-table th:nth-child(3) {{ width: 12%; }}
    .har-signal-table th:nth-child(4) {{ width: 38%; }}
    .har-signal-key {{
      position: relative;
      overflow: visible !important;
    }}
    .har-signal-table code {{
      font-size: 0.78rem;
      overflow-wrap: anywhere;
    }}
    .har-signal-table small {{
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
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
    .sig-stored {{ border-color: #5b6e80; }}
    .sig-empty {{ color: var(--muted); opacity: 0.92; background: var(--paper); }}
    tr.sig-empty td {{ color: var(--muted); }}
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
    .packet-flow {{
      display: block;
      list-style: none;
      padding: 0;
      margin: 4px 0 18px;
      border: 1px solid var(--line);
      border-radius: 5px;
      background: var(--panel);
    }}
    .packet-flow li {{
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 10px;
      border-bottom: 1px solid var(--line);
      min-height: 30px;
      min-width: 0;
    }}
    .packet-flow li:last-child {{ border-bottom: 0; }}
    .packet-flow li:hover {{ background: var(--paper); }}
    .packet-step-num {{
      flex: 0 0 auto;
      color: var(--accent);
      font: 700 0.8rem Georgia, "Times New Roman", serif;
    }}
    .packet-flow strong {{
      min-width: 0;
      color: var(--ink);
      font-size: 0.92rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .packet-flow li:focus {{ outline: 1px solid var(--accent); outline-offset: -1px; }}
    .packet-subsection {{
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 14px;
    }}
    .packet-subsection h4 {{
      margin: 0 0 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1rem;
    }}
    .packet-field-table,
    .packet-artifacts {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
      table-layout: fixed;
    }}
    .packet-field-table th,
    .packet-artifacts th {{
      text-align: left;
      color: var(--muted);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
    }}
    .packet-field-table td,
    .packet-artifacts td {{ padding: 6px 8px; vertical-align: top; border-bottom: 1px solid var(--line); }}
    .packet-field-table code {{
      overflow-wrap: anywhere;
      word-break: normal;
    }}
    .packet-scroll {{
      border: 1px solid var(--line);
      border-radius: 5px;
      overflow: auto;
      background: var(--panel);
    }}
    .har-signal-scroll {{ max-height: 390px; }}
    .packet-input-scroll {{ max-height: 430px; }}
    .packet-scroll table {{
      border: 0;
    }}
    .packet-scroll th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--panel);
    }}
    tr[data-tip-html]:focus {{ outline: 1px solid var(--accent); outline-offset: -1px; }}
    .packet-input-table th,
    .packet-input-table td {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      vertical-align: middle;
      padding-top: 5px;
      padding-bottom: 5px;
    }}
    .packet-input-table th:nth-child(1) {{ width: 34%; }}
    .packet-input-table th:nth-child(2) {{ width: 12%; }}
    .packet-input-table th:nth-child(3) {{ width: 10%; }}
    .packet-input-table th:nth-child(4) {{ width: 44%; }}
    .packet-key-cell {{
      position: relative;
      overflow: visible !important;
    }}
    .packet-key-cell .overlay-open {{
      display: block;
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--accent);
      padding: 0;
      text-align: left;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-weight: 500;
    }}
    .packet-key-cell .overlay-open:hover {{ background: transparent; text-decoration: underline; }}
    .packet-hover-tip {{
      position: fixed;
      z-index: 900;
      pointer-events: none;
      min-width: 420px;
      max-width: 760px;
      padding: 8px 10px;
      background: var(--ink);
      color: var(--panel);
      border-radius: 5px;
      box-shadow: 0 10px 28px rgba(0,0,0,0.22);
      font-size: 0.82rem;
      line-height: 1.45;
      word-break: break-word;
    }}
    .packet-hover-tip[hidden] {{ display: none; }}
    .packet-hover-tip code {{ color: var(--panel); }}
    .packet-hover-tip b {{ color: #d7e2e4; }}
    .packet-hover-tip .packet-pop-row {{ margin: 2px 0; }}
    .packet-hover-tip .packet-pop-row b {{
      display: inline-block;
      min-width: 68px;
      margin-right: 6px;
    }}
    .packet-input-table small {{
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .packet-file-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .packet-file {{
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 10px;
      background: var(--paper);
      min-width: 0;
    }}
    .packet-file header {{
      display: flex;
      align-items: baseline;
      gap: 8px;
      flex-wrap: wrap;
      margin: 0 0 6px;
    }}
    .packet-file code {{
      word-break: break-all;
      overflow-wrap: anywhere;
      font-size: 0.78rem;
    }}
    .packet-phase {{
      display: inline-block;
      border: 1px solid var(--accent-2);
      border-radius: 10px;
      padding: 1px 7px;
      color: var(--accent-2);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .packet-group-head td {{
      background: rgba(127, 127, 127, 0.10);
      font-weight: 700;
      font-size: 0.76rem;
      letter-spacing: 0.01em;
      color: var(--accent-2);
      padding-top: 9px;
      padding-bottom: 6px;
      border-top: 2px solid var(--accent-2);
    }}
    .packet-file p {{
      color: var(--ink);
      font-size: 0.84rem;
      line-height: 1.45;
      margin: 0 0 6px;
    }}
    .packet-file small {{
      display: block;
      color: var(--muted);
      font-size: 0.76rem;
      margin: 0 0 8px;
    }}
    .packet-file details summary,
    .packet-artifacts details summary,
    .packet-result details summary,
    .packet-raw details summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .packet-file pre,
    .packet-artifacts pre,
    .packet-result pre,
    .packet-raw pre {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 8px 10px;
      margin: 6px 0 0;
      max-height: 300px;
      overflow: auto;
      font-size: 0.76rem;
      line-height: 1.45;
    }}
    .packet-result p,
    .packet-raw p,
    .packet-help {{
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }}
    .overlay-open {{
      width: auto;
      margin: 0;
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--accent);
      border-radius: 4px;
      padding: 3px 8px;
      font: 600 0.78rem -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      cursor: pointer;
    }}
    .overlay-open:hover {{ background: #eaf1f2; }}
    .content-overlay[hidden] {{ display: none; }}
    .content-overlay {{
      position: fixed;
      inset: 0;
      z-index: 1000;
      background: rgba(31, 37, 40, 0.58);
      padding: 24px;
    }}
    .content-overlay-inner {{
      height: calc(100vh - 48px);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 80px rgba(0,0,0,0.24);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .content-overlay-head {{
      display: flex;
      gap: 12px;
      align-items: center;
      border-bottom: 1px solid var(--line);
      padding: 14px 18px;
    }}
    .content-overlay-head h3 {{
      margin: 0;
      flex: 1;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.1rem;
    }}
    .content-overlay-close {{
      border: 1px solid var(--line);
      background: var(--paper);
      color: var(--ink);
      border-radius: 4px;
      padding: 4px 10px;
      cursor: pointer;
    }}
    .content-overlay-body {{
      padding: 16px 18px;
      overflow: auto;
      flex: 1;
    }}
    .content-overlay-body pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font: 0.82rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
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
    /* Agent guardrail explainer — see render_guardrail_html() */
    .guard-section .lead {{ margin-bottom: 4px; }}
    .guard-core {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin: 22px 0 26px;
    }}
    .guard-fold {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-top: 3px solid var(--accent);
      padding: 14px 15px 13px;
    }}
    .guard-fold h3 {{
      margin: 0 0 7px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 1.02rem;
    }}
    .guard-fold p {{ margin: 0; color: var(--muted); font-size: 0.88rem; line-height: 1.5; }}
    .guard-layers {{ list-style: none; padding: 0; margin: 0; }}
    .guard-layer {{
      display: flex;
      gap: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px 16px;
      margin: 0 0 10px;
    }}
    .guard-tag {{
      flex: 0 0 auto;
      align-self: flex-start;
      padding: 2px 9px;
      background: var(--paper);
      border-radius: 10px;
      color: var(--accent);
      font: 700 0.78rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      letter-spacing: 0.04em;
    }}
    .guard-main {{ min-width: 0; flex: 1; }}
    .guard-name {{ margin: 0; font-weight: 700; color: var(--ink); }}
    .guard-what {{ margin: 3px 0 0; font-size: 0.92rem; line-height: 1.5; }}
    .guard-ref {{ margin: 6px 0 0; font-size: 0.8rem; }}
    .guard-ref a {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--accent);
      text-decoration: none;
      word-break: break-all;
    }}
    .guard-ref a:hover {{ text-decoration: underline; }}
    .guard-fn {{
      color: var(--muted);
      font: 0.78rem ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      word-break: break-all;
    }}
    .guard-why {{ margin: 6px 0 0; color: var(--muted); font-size: 0.82rem; line-height: 1.45; }}
    .guard-model {{ margin-top: 18px; }}
    .guard-section code {{
      font: 0.86em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: var(--paper);
      border: 1px solid var(--line);
      padding: 0 4px;
      border-radius: 3px;
    }}
    @media (max-width: 720px) {{
      main {{ padding-top: 34px; }}
      h1 {{ font-size: 2.1rem; }}
      .metrics {{ grid-template-columns: 1fr 1fr; }}
      .guard-core {{ grid-template-columns: 1fr; }}
      .packet-flow {{ grid-template-columns: 1fr; }}
      .packet-file-grid {{ grid-template-columns: 1fr; }}
      table {{ display: block; overflow-x: auto; }}
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
    <h2 id="har">What runs when you /watch a new site (HAR)</h2>
    <p class="lead">A first-time <code>/watch &lt;url&gt;</code> cascades top &rarr; bottom through
      bot &rarr; worker &rarr; <em>register</em> subprocess. Each box is a real call —
      <strong>hover</strong> to read the role, <strong>click</strong> to open the source on GitHub.
      Dashed boxes are conditional branches (skip / fast-path / early return).
      Figure&nbsp;4 below drills into the <code>generate</code> step with a live probe artifact.</p>
    <figure id="harPipeline" class="watch-icicle-wrap">
      {watch_icicle_svg}
      <figcaption>Figure 3. <code>/watch</code> call icicle &mdash; lane color =
        which process the call runs in (<span class="lane-swatch lane-bot"></span>&nbsp;bot asyncio,
        <span class="lane-swatch lane-worker"></span>&nbsp;worker asyncio,
        <span class="lane-swatch lane-subprocess"></span>&nbsp;register subprocess).
        Box width = how many sub-steps live inside &mdash; <strong>not</strong> wall-clock time.
        Lane transitions mark async hand-off (bot &rarr; worker) and OS subprocess spawn (worker &rarr; register).
        On mobile, swipe horizontally if boxes get tight.</figcaption>
    </figure>
    <figure id="harPipelineLegacy">
      {har_funnel_svg}
      <figcaption>Figure 3b (temporary). Probe + register-decide pipeline &mdash;
        the 5-stage funnel that the icicle has not yet absorbed. Click any stage
        to expand the file-flow detail below. This figure will be folded into
        the icicle once it expresses the per-stage probe/register order inline.</figcaption>
    </figure>
    <div class="stage-panels" id="harStagePanels">
      {har_stage_panels_html}
    </div>
    <figure id="probeAgenticFigure">
      <h3>Figure 4. From probe artifacts to the agentic config packet</h3>
      <p class="figure-lead">Pick a URL example to read the full path in one place:
        probe/HAR signals first, then the staged config-generation packet below.
        Use <strong>view</strong> buttons for a full-screen explanation of each field plus
        the raw text that would be shown or derived for the model.</p>
      {probe_agentic_html}
      <figcaption>Auto-selected each cycle (score-based; sticky to the previous slug when it
        still qualifies) from <code>output/probe/&lt;slug&gt;/</code>. Generated from the selected
        probe run plus current prompt/source files. If probe output, config writer rules,
        agent prompt, validator wrapper, or <code>generate/codex_agentic.py</code> changes,
        the site manifest changes and this section is rebuilt on the next static-site
        generation cycle.</figcaption>
    </figure>
    <div id="contentOverlay" class="content-overlay" hidden role="dialog" aria-modal="true" aria-labelledby="contentOverlayTitle">
      <div class="content-overlay-inner">
        <header class="content-overlay-head">
          <h3 id="contentOverlayTitle"></h3>
          <button type="button" class="content-overlay-close" data-overlay-close="1">Close</button>
        </header>
        <div id="contentOverlayBody" class="content-overlay-body"></div>
      </div>
    </div>
    <div id="packetHoverTip" class="packet-hover-tip" hidden></div>
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
        var probeAgentPicker = document.getElementById('probeAgentPicker');
        var probeAgentSearch = document.getElementById('probeAgentSearch');
        var probeAgentOpenUrl = document.getElementById('probeAgentOpenUrl');
        var probeAgentCount = document.getElementById('probeAgentCount');
        var probeAgentPanelHost = document.getElementById('probeAgentPanelHost');
        var activeProbeAgentPanelId = probeAgentPanelHost && probeAgentPanelHost.firstElementChild
          ? probeAgentPanelHost.firstElementChild.id : '';
        var loadedProbeAgentPanels = {{}};
        if (probeAgentPanelHost && activeProbeAgentPanelId) {{
          loadedProbeAgentPanels[activeProbeAgentPanelId] = probeAgentPanelHost.innerHTML;
        }}
        var probeAgentOptions = probeAgentPicker ? Array.prototype.map.call(probeAgentPicker.options, function (opt) {{
          return {{
            option: opt,
            value: opt.value,
            text: opt.textContent || '',
            url: opt.getAttribute('data-url') || '',
            panelUrl: opt.getAttribute('data-panel-url') || '',
            search: opt.getAttribute('data-search') || ''
          }};
        }}) : [];
        function updateProbeAgentUrl() {{
          if (!probeAgentPicker || !probeAgentOpenUrl) return;
          var opt = probeAgentPicker.selectedOptions && probeAgentPicker.selectedOptions[0];
          var url = opt ? (opt.getAttribute('data-url') || '') : '';
          if (url) {{
            probeAgentOpenUrl.href = url;
            probeAgentOpenUrl.textContent = 'open URL';
            probeAgentOpenUrl.setAttribute('aria-disabled', 'false');
          }} else {{
            probeAgentOpenUrl.href = '#';
            probeAgentOpenUrl.textContent = 'no URL';
            probeAgentOpenUrl.setAttribute('aria-disabled', 'true');
          }}
        }}
        function setProbeAgentPanel(targetId) {{
          if (!probeAgentPanelHost) return;
          if (activeProbeAgentPanelId === targetId) {{
            updateProbeAgentUrl();
            return;
          }}
          activeProbeAgentPanelId = targetId;
          updateProbeAgentUrl();
          if (!targetId) {{
            probeAgentPanelHost.innerHTML = '<p class="meta">No matching example.</p>';
            return;
          }}
          if (loadedProbeAgentPanels[targetId]) {{
            probeAgentPanelHost.innerHTML = loadedProbeAgentPanels[targetId];
            return;
          }}
          var match = probeAgentOptions.find(function (item) {{ return item.value === targetId; }});
          if (!match || !match.panelUrl) return;
          probeAgentPanelHost.innerHTML = '<p class="meta">Loading example...</p>';
          loadText(match.panelUrl).then(function (html) {{
            loadedProbeAgentPanels[targetId] = html;
            if (activeProbeAgentPanelId === targetId) probeAgentPanelHost.innerHTML = html;
          }}).catch(function (err) {{
            if (activeProbeAgentPanelId === targetId) {{
              probeAgentPanelHost.innerHTML = '<p class="meta">Failed to load example: ' + err.message + '</p>';
            }}
          }});
        }}
        function renderProbeAgentOptions(query) {{
          if (!probeAgentPicker) return;
          var q = (query || '').trim().toLowerCase();
          var current = probeAgentPicker.value;
          var matches = [];
          probeAgentOptions.forEach(function (item) {{
            var ok = !q || item.search.indexOf(q) !== -1 || item.text.toLowerCase().indexOf(q) !== -1;
            item.option.hidden = !ok;
            item.option.disabled = !ok;
            if (ok) matches.push(item);
          }});
          if (probeAgentCount) {{
            probeAgentCount.textContent = matches.length + ' / ' + probeAgentOptions.length + ' registered probe examples';
          }}
          if (!matches.length) {{
            setProbeAgentPanel('');
            updateProbeAgentUrl();
            return;
          }}
          var next = matches.some(function (item) {{ return item.value === current; }}) ? current : matches[0].value;
          probeAgentPicker.value = next;
          setProbeAgentPanel(next);
        }}
        if (probeAgentPicker && probeAgentOptions.length) {{
          probeAgentPicker.addEventListener('change', function () {{
            setProbeAgentPanel(probeAgentPicker.value);
          }});
          if (probeAgentSearch) {{
            probeAgentSearch.addEventListener('input', function () {{
              renderProbeAgentOptions(probeAgentSearch.value);
            }});
          }}
          updateProbeAgentUrl();
        }}
        var overlay = document.getElementById('contentOverlay');
        var overlayTitle = document.getElementById('contentOverlayTitle');
        var overlayBody = document.getElementById('contentOverlayBody');
        var packetTip = document.getElementById('packetHoverTip');
        function positionPacketTip(e) {{
          if (!packetTip || packetTip.hidden) return;
          var x = e.clientX + 14;
          var y = e.clientY + 14;
          var rect = packetTip.getBoundingClientRect();
          if (x + rect.width > window.innerWidth - 12) x = Math.max(12, e.clientX - rect.width - 14);
          if (y + rect.height > window.innerHeight - 12) y = Math.max(12, e.clientY - rect.height - 14);
          packetTip.style.left = x + 'px';
          packetTip.style.top = y + 'px';
        }}
        function showPacketTip(el, e) {{
          if (!packetTip || !el) return;
          var html = el.getAttribute('data-tip-html') || '';
          if (!html) return;
          packetTip.innerHTML = html;
          packetTip.hidden = false;
          positionPacketTip(e);
        }}
        function hidePacketTip() {{
          if (packetTip) packetTip.hidden = true;
        }}
        function loadText(url) {{
          if (window.fetch) {{
            // no-cache: always revalidate with the server (conditional GET,
            // 304 when unchanged). Raw assets are served without Cache-Control,
            // so a plain fetch would heuristic-cache stale content after regen.
            return fetch(url, {{ cache: 'no-cache' }}).then(function (res) {{
              if (!res.ok) throw new Error('HTTP ' + res.status);
              return res.text();
            }});
          }}
          return new Promise(function (resolve, reject) {{
            var xhr = new XMLHttpRequest();
            xhr.open('GET', url);
            xhr.setRequestHeader('Cache-Control', 'no-cache');
            xhr.onload = function () {{
              if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText || '');
              else reject(new Error('HTTP ' + xhr.status));
            }};
            xhr.onerror = function () {{ reject(new Error('network error')); }};
            xhr.send();
          }});
        }}
        document.addEventListener('mouseover', function (e) {{
          var el = e.target.closest ? e.target.closest('[data-tip-html]') : null;
          if (el) showPacketTip(el, e);
        }});
        document.addEventListener('mousemove', function (e) {{
          positionPacketTip(e);
        }});
        document.addEventListener('mouseout', function (e) {{
          var el = e.target.closest ? e.target.closest('[data-tip-html]') : null;
          if (el && (!e.relatedTarget || !el.contains(e.relatedTarget))) hidePacketTip();
        }});
        document.addEventListener('focusin', function (e) {{
          var el = e.target.closest ? e.target.closest('[data-tip-html]') : null;
          if (!el || !packetTip) return;
          packetTip.innerHTML = el.getAttribute('data-tip-html') || '';
          packetTip.hidden = false;
          var r = el.getBoundingClientRect();
          positionPacketTip({{ clientX: r.left, clientY: r.bottom }});
        }});
        document.addEventListener('focusout', hidePacketTip);
        function closeOverlay() {{
          if (!overlay) return;
          overlay.hidden = true;
          if (overlayBody) overlayBody.innerHTML = '';
        }}
        document.addEventListener('click', function (e) {{
          var openBtn = e.target.closest ? e.target.closest('.overlay-open') : null;
          if (openBtn) {{
            var tid = openBtn.getAttribute('data-overlay-template') || '';
            var rawUrl = openBtn.getAttribute('data-overlay-raw-url') || '';
            var tpl = document.getElementById(tid);
            if (!overlay || !overlayBody || !overlayTitle) return;
            overlayTitle.textContent = openBtn.getAttribute('data-overlay-title') || 'Details';
            overlay.hidden = false;
            if (rawUrl) {{
              overlayBody.innerHTML = '<pre>loading raw text...</pre>';
              loadText(rawUrl).then(function (text) {{
                var pre = document.createElement('pre');
                pre.textContent = text;
                overlayBody.innerHTML = '';
                overlayBody.appendChild(pre);
              }}).catch(function (err) {{
                var pre = document.createElement('pre');
                pre.textContent = 'failed to load raw text: ' + err.message;
                overlayBody.innerHTML = '';
                overlayBody.appendChild(pre);
              }});
              return;
            }}
            if (!tpl) return;
            overlayBody.innerHTML = tpl.innerHTML;
            return;
          }}
          if (e.target && e.target.getAttribute && e.target.getAttribute('data-overlay-close') === '1') {{
            closeOverlay();
          }}
          if (e.target === overlay) {{
            closeOverlay();
          }}
        }});
        document.addEventListener('keydown', function (e) {{
          if (e.key === 'Escape') closeOverlay();
        }});
      }})();
    </script>
  </section>

{guardrail_html}
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_probe_raw_assets(out_path.parent, har_detail)
    write_probe_panel_assets(out_path.parent, har_detail)
    generated_at = datetime.now(KST)
    page = render_html(
        configs,
        poll,
        jobs,
        generated_at,
        case_records=case_records,
        har_detail=har_detail,
    )

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
