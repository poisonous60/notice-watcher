"""recognizer 승급 후보 cluster 계산 (read-only, 순수 함수).

CLI(`scripts/cluster_report.py`) 와 dashboard(`/clusters`) 가 공유. print/IO 없음 — dict 반환.

cluster 신호 2종:
  A. SAME-HOST  — 같은 host, path/param 만 다른 ≥2개 (검색어/board 만 다른 케이스).
  B. CROSS-HOST — host 다르지만 path-template 같은 ≥2 host (CMS — 그누보드 등).
이미 recognize(url) 되는 건 제외 (봉합 = 승급 불필요).
host 를 시그니처에 유지 → 무관 사이트(bbc/cnn) over-merge 방지.
query 는 value 버리고 key 집합만 (value 통째 VAR 는 과합침).

url provenance: config 의 _source_url > poll_state/<slug>.json url > headers.Referer(옛 config 복구용 추정).
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

from engine.recognizers import recognize

_HEX = re.compile(r"^[0-9a-f]{8,}$", re.I)


def _abstract_segment(s: str) -> tuple[str, bool]:
    """path segment → (정규화, is_literal). 숫자/해시/혼합ID 는 변수, 단어는 literal."""
    if s.isdigit():
        return "<N>", False
    if _HEX.match(s):
        return "<HEX>", False
    if re.search(r"\d", s) and re.search(r"[a-zA-Z]", s):
        return "<ID>", False
    return s, True


def path_template(url: str) -> tuple[str, str, int]:
    """url → (path_template, query_key_shape, literal_seg_count)."""
    sp = urlsplit(url)
    segs = [s for s in sp.path.split("/") if s]
    out, lit = [], 0
    for s in segs:
        norm, is_lit = _abstract_segment(s)
        out.append(norm)
        lit += int(is_lit)
    pt = "/" + "/".join(out) if out else "/"
    qkeys = sorted({k for k, _ in parse_qsl(sp.query, keep_blank_values=True)})
    qshape = ("?" + "&".join(qkeys)) if qkeys else ""
    return pt, qshape, lit


def load_members(configs_dir: Path, poll_state_dir: Path) -> list[dict]:
    """configs_dir/*.json → [{slug,url,host,strategy,adapter,recognized,src}]."""
    ps_url: dict[str, str] = {}
    for p in glob.glob(str(poll_state_dir / "*.json")):
        if p.endswith(".FAILED.json"):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
            if d.get("slug") and d.get("url"):
                ps_url[d["slug"]] = d["url"]
        except Exception:
            continue

    members = []
    for p in sorted(glob.glob(str(configs_dir / "*.json"))):
        try:
            c = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        slug = Path(p).stem
        url = c.get("_source_url") or ps_url.get(slug)
        src = "src_url" if c.get("_source_url") else ("poll_state" if url else None)
        if not url:
            # Referer fallback (옛 config 복구) — 단 config 의 site 와 같은 host 일 때만.
            # api/login/cdn 등 등록 url 아닌 Referer 가 phantom cluster 만드는 것 방지 (codex).
            ref = (c.get("headers") or {}).get("Referer")
            if ref and c.get("site") and urlsplit(ref).netloc == c["site"]:
                url, src = ref, "referer?"
        if not url:
            continue
        members.append({
            "slug": slug, "url": url, "host": urlsplit(url).netloc,
            "strategy": c.get("strategy"), "adapter": c.get("adapter"),
            "recognized": recognize(url) is not None, "src": src,
        })
    return members


def compute_clusters(configs_dir: Path, poll_state_dir: Path) -> dict:
    """승급 후보 cluster 계산 → {totals, same_host:[...], cross_host:[...]}.

    각 cluster: {key, members:[member...], strategy_uniform:bool, member_pairs:[(slug,url)]}.
    member_pairs 는 prompt 빌더용. prompt 텍스트는 호출측이 dashboard.prompts 로 생성.
    """
    members = load_members(configs_dir, poll_state_dir)
    cand = [m for m in members if not m["recognized"]]

    # A: same-host
    byhost: dict[str, list[dict]] = defaultdict(list)
    for m in cand:
        byhost[m["host"]].append(m)
    same_host = []
    for h, ms in byhost.items():
        if len({m["url"] for m in ms}) < 2:
            continue
        ms_sorted = sorted(ms, key=lambda x: x["url"])
        same_host.append({
            "key": h,
            "members": [{**m, "path": path_template(m["url"])[0] + path_template(m["url"])[1]}
                        for m in ms_sorted],
            "strategy_uniform": len({m["strategy"] for m in ms}) == 1,
            "member_pairs": [(m["slug"], m["url"]) for m in ms_sorted],
        })
    same_host.sort(key=lambda c: -len(c["members"]))

    # B: cross-host CMS
    bytmpl: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in cand:
        pt, qs, lit = path_template(m["url"])
        if lit < 1:
            continue  # literal 0 → over-merge 위험
        bytmpl[(pt, qs)].append(m)
    cross_host = []
    for (pt, qs), ms in bytmpl.items():
        if len({m["host"] for m in ms}) < 2:
            continue
        ms_sorted = sorted(ms, key=lambda x: x["host"])
        cross_host.append({
            "key": f"{pt}{qs}",
            "members": ms_sorted,
            "strategy_uniform": len({m["strategy"] for m in ms}) == 1,
            "member_pairs": [(m["slug"], m["url"]) for m in ms_sorted],
        })
    cross_host.sort(key=lambda c: -len({m["host"] for m in c["members"]}))

    return {
        "total": len(members),
        "recognized": sum(1 for m in members if m["recognized"]),
        "candidates": len(cand),
        "same_host": same_host,
        "cross_host": cross_host,
    }
