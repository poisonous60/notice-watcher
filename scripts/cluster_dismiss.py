"""recognizer 승급 후보 cluster '안 됨' 닫기 CLI (dev box only).

`/clusters` 대시보드 버튼과 같은 저장소(`dashboard/cluster_dismissed.json`, git 추적) 공유.
닫은 cluster 는 dashboard `/clusters` 와 `scripts/cluster_report.py` 양쪽에서 후보에서 빠진다.

  python scripts/cluster_dismiss.py list
  python scripts/cluster_dismiss.py add cross_host /blog --reason "이종 cross-host, 같은 CMS 아님"
  python scripts/cluster_dismiss.py add same_host bbs.example.com --reason "..."
  python scripts/cluster_dismiss.py remove cross_host /blog

주의(Git Bash/MSYS): 선행 `/` 인자(cross_host key)가 Windows 경로로 변환됨.
`MSYS_NO_PATHCONV=1 python scripts/cluster_dismiss.py add cross_host /blog ...`
또는 PowerShell/대시보드 버튼 사용. PowerShell·cmd 는 영향 없음.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path[:1]:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from dashboard import cluster_dismiss

    ap = argparse.ArgumentParser(description="cluster 승급 불가 닫기/되살리기 (dev box)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="닫은 cluster 목록")
    p_add = sub.add_parser("add", help="cluster 닫기")
    p_add.add_argument("kind", choices=cluster_dismiss.KINDS)
    p_add.add_argument("key", help="cluster key (same_host=host, cross_host=path-template)")
    p_add.add_argument("--reason", default="", help="안 됨 사유 메모")
    p_rm = sub.add_parser("remove", help="cluster 되살리기")
    p_rm.add_argument("kind", choices=cluster_dismiss.KINDS)
    p_rm.add_argument("key")

    a = ap.parse_args()
    if a.cmd == "list":
        entries = cluster_dismiss.load_entries()
        if not entries:
            print("닫은 cluster 없음.")
            return
        for e in entries:
            print(f"  [{e['kind']}] {e['key']}   {e['reason'] or '—'}  ({e['at']})")
        print(f"\n총 {len(entries)}건.")
    elif a.cmd == "add":
        cluster_dismiss.add(a.kind, a.key, a.reason)
        print(f"닫음: [{a.kind}] {a.key}" + (f"  ({a.reason})" if a.reason else ""))
    elif a.cmd == "remove":
        cluster_dismiss.remove(a.kind, a.key)
        print(f"되살림: [{a.kind}] {a.key}")


if __name__ == "__main__":
    main()
