"""recognizer 승급 후보 cluster 리포트 (read-only CLI).

자동생성된 개별 config 중 "같은 사이트/platform 인데 param 만 다른" 묶음을 찾아
recognizer(플랫폼 config) 로 승급하면 토큰 0 으로 처리될 후보를 출력한다.

핵심 로직은 `dashboard/clustering.py` (dashboard `/clusters` 페이지와 공유). 이 CLI 는 dev box
의 configs/ + output/poll_state/ 를 소스로 그 함수를 호출해 텍스트로 출력. dashboard 는 N100
snapshot(configs.snapshot/, output/snapshot/poll_state/)을 소스로 같은 함수 호출.

설계 근거: docs/자가개선 인프라 계획 + codex 리뷰 (2026-05-20).
승급 자체는 recognizer-extension 스킬 (agent 가 멤버 config 비교 → recognizer 작성·검증).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# scripts/dashboard.py 가 `dashboard` 패키지를 shadow — ROOT 를 sys.path 앞에 박아 패키지 우선.
if str(ROOT) not in sys.path[:1]:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from dashboard.clustering import compute_clusters
    from dashboard.prompts import recognizer_extension_cluster

    res = compute_clusters(ROOT / "configs", ROOT / "output" / "poll_state")
    print(f"config {res['total']}개 | url 있음 → recognized {res['recognized']} (이미 봉합) / "
          f"unrecognized {res['candidates']} (승급 후보 풀)\n")

    print("=" * 70)
    print(f"[A] SAME-HOST cluster — 같은 사이트 param/board 만 다름 ({len(res['same_host'])}곳)")
    print("=" * 70)
    for c in res["same_host"]:
        shape = "✅ strategy 동일" if c["strategy_uniform"] else "⚠️ strategy 혼재"
        print(f"\n  {c['key']}  [{len(c['members'])}개 config | {shape}]")
        for m in c["members"]:
            ad = f" adapter={m['adapter']}" if m["adapter"] else ""
            print(f"      {m['path']}   (strat={m['strategy']}{ad})")
            print(f"        ← [{m['src']}] {m['url'][:90]}")
        prompt = recognizer_extension_cluster(host_or_template=c["key"], members=c["member_pairs"])
        print("\n      ┌─ 복사용 프롬프트 (recognizer-extension 스킬) " + "─" * 18)
        for ln in prompt.splitlines():
            print(f"      │ {ln}")
        print("      └" + "─" * 60)

    print("\n" + "=" * 70)
    print(f"[B] CROSS-HOST CMS cluster — 다른 사이트, 같은 게시판 솔루션 ({len(res['cross_host'])}곳)")
    print("=" * 70)
    if not res["cross_host"]:
        print("  없음")
    for c in res["cross_host"]:
        hosts = {m["host"] for m in c["members"]}
        print(f"\n  {c['key']}  [{len(hosts)} hosts]")
        for m in c["members"]:
            print(f"      {m['host']:30s} strat={m['strategy']}  ← {m['url'][:70]}")

    print("\n" + "-" * 70)
    print("승급: recognizer-extension 스킬 (agent 가 멤버 config 비교 → recognizer 작성·검증).")
    print("이미 recognize() 되는 host 는 후보에서 제외됨. dashboard `/clusters` 에서도 같은 결과.")


if __name__ == "__main__":
    main()
