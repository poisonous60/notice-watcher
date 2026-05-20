"""recognizer 승급 후보 cluster 리포트 (read-only).

자동생성된 개별 config 중 "같은 사이트 / 같은 platform 인데 param 만 다른" 묶음을 찾아
recognizer(플랫폼 config) 로 승급하면 토큰 0 으로 처리될 후보를 출력한다.

설계 근거: docs/자가개선 인프라 계획 + codex 리뷰 (2026-05-20).
  - read-only. 판단/생성 안 함 (그건 recognizer-extension 스킬 — agent 가 함).
  - 이미 recognize(url) 되는 건 제외 (이미 봉합 = 승급 불필요).
  - 신호 2종:
      A. same-host cluster — 같은 host, path 만 다른 ≥2개 (네 "검색어/board 만 다름" 케이스).
      B. cross-host CMS cluster — host 다르지만 path-template 같은 ≥2 host (그누보드 등).
  - host 를 시그니처에 유지 → bbc/cnn 같은 무관 사이트 over-merge 방지.

소스: configs/*.json (url = _source_url, 없으면 output/poll_state/<slug>.json 의 url).
  dev box 엔 register_batch_runs.sqlite3 / 채워진 jobs 없음 (N100 운영 데이터) — configs/ 가 진본.
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

from engine.recognizers import recognize

CONFIGS = "configs"
POLL_STATE = "output/poll_state"

_HEX = re.compile(r"^[0-9a-f]{8,}$", re.I)


def _abstract_segment(s: str) -> tuple[str, bool]:
    """path segment → (정규화, is_literal). 숫자/해시/혼합ID 는 변수 <X>, 단어는 literal."""
    if s.isdigit():
        return "<N>", False
    if _HEX.match(s):
        return "<HEX>", False
    if re.search(r"\d", s) and re.search(r"[a-zA-Z]", s):
        # board7, list_1018 처럼 숫자 섞인 ID 류 → 변수 취급
        return "<ID>", False
    return s, True


def path_template(url: str) -> tuple[str, str, int]:
    """url → (path_template, query_key_shape, literal_seg_count).
    query 는 value 버리고 key 집합만 (value 통째 VAR 는 과합침 — codex)."""
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


def load_members() -> list[dict]:
    """configs/*.json → [{slug,url,host,strategy,adapter,recognized}]."""
    # slug → url fallback (poll_state)
    ps_url: dict[str, str] = {}
    for p in glob.glob(f"{POLL_STATE}/*.json"):
        if p.endswith(".FAILED.json"):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
            if d.get("slug") and d.get("url"):
                ps_url[d["slug"]] = d["url"]
        except Exception:
            continue

    members = []
    for p in sorted(glob.glob(f"{CONFIGS}/*.json")):
        try:
            c = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        slug = Path(p).stem
        # url provenance: _source_url(진본) > poll_state > headers.Referer(추정 — 옛 config 복구용)
        url = c.get("_source_url") or ps_url.get(slug)
        src = "src_url" if c.get("_source_url") else ("poll_state" if url else None)
        if not url:
            url = (c.get("headers") or {}).get("Referer")
            src = "referer?" if url else None
        if not url:
            continue
        members.append({
            "slug": slug,
            "url": url,
            "host": urlsplit(url).netloc,
            "strategy": c.get("strategy"),
            "adapter": c.get("adapter"),
            "recognized": recognize(url) is not None,
            "src": src,
        })
    return members


def main() -> None:
    members = load_members()
    total = len(members)
    rec = [m for m in members if m["recognized"]]
    cand = [m for m in members if not m["recognized"]]
    print(f"config {total}개 | url 있음 → recognized {len(rec)} (이미 봉합) / unrecognized {len(cand)} (승급 후보 풀)\n")

    # --- A: same-host cluster (같은 사이트, param/board 만 다름) ---
    byhost: dict[str, list[dict]] = defaultdict(list)
    for m in cand:
        byhost[m["host"]].append(m)
    a_clusters = {h: ms for h, ms in byhost.items()
                  if len({m["url"] for m in ms}) >= 2}
    print("=" * 70)
    print(f"[A] SAME-HOST cluster — 같은 사이트 param/board 만 다름 ({len(a_clusters)}곳)")
    print("=" * 70)
    for h, ms in sorted(a_clusters.items(), key=lambda x: -len(x[1])):
        strands = {m["strategy"] for m in ms}
        shape = "✅ strategy 동일" if len(strands) == 1 else f"⚠️ strategy 혼재 {strands}"
        print(f"\n  {h}  [{len(ms)}개 config | {shape}]")
        for m in sorted(ms, key=lambda x: x["url"]):
            pt, qs, _ = path_template(m["url"])
            ad = f" adapter={m['adapter']}" if m["adapter"] else ""
            print(f"      {pt}{qs}   (strat={m['strategy']}{ad})")
            print(f"        ← [{m['src']}] {m['url'][:90]}")
        try:
            from dashboard.prompts import recognizer_extension_cluster
            prompt = recognizer_extension_cluster(
                host_or_template=h,
                members=[(m["slug"], m["url"]) for m in sorted(ms, key=lambda x: x["url"])])
            print("\n      ┌─ 복사용 프롬프트 (recognizer-extension 스킬) " + "─" * 18)
            for ln in prompt.splitlines():
                print(f"      │ {ln}")
            print("      └" + "─" * 60)
        except Exception:
            pass

    # --- B: cross-host CMS cluster (host 다르지만 path-template 동일) ---
    bytmpl: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in cand:
        pt, qs, lit = path_template(m["url"])
        if lit < 1:
            continue  # literal segment 0 → 과합침 위험 (codex), 제외
        bytmpl[(pt, qs)].append(m)
    b_clusters = {k: ms for k, ms in bytmpl.items()
                  if len({m["host"] for m in ms}) >= 2}
    print("\n" + "=" * 70)
    print(f"[B] CROSS-HOST CMS cluster — 다른 사이트, 같은 게시판 솔루션 ({len(b_clusters)}곳)")
    print("=" * 70)
    if not b_clusters:
        print("  없음")
    for (pt, qs), ms in sorted(b_clusters.items(), key=lambda x: -len({m['host'] for m in x[1]})):
        hosts = {m["host"] for m in ms}
        print(f"\n  {pt}{qs}  [{len(hosts)} hosts]")
        for m in sorted(ms, key=lambda x: x["host"]):
            print(f"      {m['host']:30s} strat={m['strategy']}  ← {m['url'][:70]}")

    print("\n" + "-" * 70)
    print("승급: recognizer-extension 스킬 (agent 가 멤버 config 비교 → recognizer 작성·검증).")
    print("이미 recognize() 되는 host 는 후보에서 제외됨 (승급 불필요).")


if __name__ == "__main__":
    main()
