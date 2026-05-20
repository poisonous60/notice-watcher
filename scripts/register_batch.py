"""사이트 카탈로그 일괄 enqueue driver (rev6).

rev6 변경: catalog yaml 의 위치 `configs/candidates/` → `output/candidates/`. git-ignored 데이터.
dev box 의 dashboard 가 직접 편집, N100 동기는 `scripts/remote.py batch-register` 의 atomic scp.

`output/candidates/<name>.yaml` (schema 2: name + url) multi-file 을 읽어 각 entry url
마다 N100 의 bot.sqlite3 jobs 테이블에 `kind='register', via='batch'` 잡을 enqueue.
실행은 N100 만 — bot worker 가 `/preview` 와 동일한 path 로 처리.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` rev5 §6.

scope axis (둘 중 하나 이상 필수):
    --catalog <name>     catalog 파일명 stem (e.g. 2026-05-20). 반복 가능.
    --url URL            직접 URL allowlist. 반복 가능. catalog 무관.

filter axis (택1):
    (default)            untried 만 — jobs row 없는 URL 만 enqueue.
    --failed             rc ∈ {1, 5, -1, -2, -3, -99} 마커 가진 URL retry (마커 자동 clear).
    --rc=<list>          comma-list (e.g. --rc=1,-99). 그 rc 가진 URL retry (마커 자동 clear).
    --force              jobs row / marker 다 무시. filter override.

기타:
    --limit N            enqueue 상한 (0=무한)
    --dry-run            enqueue 안 함, 분포만 출력

rc:
    0  정상 종료
    2  catalog 로드/검증 실패 (cross-catalog dedup 포함)
    3  catalog 파일 없음
    4  인자 오류
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import db  # noqa: E402
from probe.paths import url_to_slug  # noqa: E402

CATALOG_DIR = ROOT / "output" / "candidates"  # rev6: git-ignored 데이터. dev box dashboard 직접 편집.
                                                # N100 은 `scripts/remote.py batch-register` 의 atomic scp 로 동기 (CLAUDE.md §5 예외).
STATE_DIR = ROOT / "output" / "poll_state"
MARKER_SUFFIXES = (".REJECTED.json", ".FAILED.json", ".BUG.json")

CATALOG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# `--failed` preset — retry-worthy rcs (gen_fail + bug variants + capability_blocked).
# rc=5 (capability_blocked, 2026-05-21) = anti-bot/captcha 차단 = 능력 부족 → stealth 어댑터로 재도전 가능.
FAILED_PRESET_RCS = (1, 5, -1, -2, -3, -99)


def _load_one_catalog(path: Path) -> list[dict]:
    """단일 yaml 의 entries 검증 + 반환. schema 위반 시 ValueError."""
    if not path.exists():
        raise FileNotFoundError(f"catalog 경로 없음: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"catalog YAML 파싱 실패 ({path.name}): {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: 루트가 mapping 아님")
    if doc.get("schema") != 2:
        raise ValueError(f"{path.name}: schema={doc.get('schema')!r} — rev5 는 schema=2 만 지원")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{path.name}: `entries` 가 list 아님")
    seen_urls: set[str] = set()
    out: list[dict] = []
    for i, e in enumerate(entries):
        ctx = f"{path.name} entries[{i}]"
        if not isinstance(e, dict):
            raise ValueError(f"{ctx}: mapping 아님")
        name = e.get("name")
        url = e.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{ctx}: name 비어있음")
        if len(name) > 200:
            raise ValueError(f"{ctx}: name 200자 초과")
        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"{ctx}: url 이 http(s) 아님: {url!r}")
        if len(url) > 1000:
            raise ValueError(f"{ctx}: url 1000자 초과")
        if url in seen_urls:
            raise ValueError(f"{ctx}: url 중복 (within file) {url!r}")
        seen_urls.add(url)
        out.append({"name": name.strip(), "url": url, "_catalog": path.stem})
    return out


def _resolve_catalog_path(name_or_path: str) -> Path:
    """name 또는 path → 실제 yaml 경로. name 이면 `<CATALOG_DIR>/<name>.yaml`."""
    # path-like (`/` 또는 `.yaml` 포함) → 그대로 Path. 아니면 catalog dir 안.
    if "/" in name_or_path or "\\" in name_or_path or name_or_path.endswith(".yaml"):
        return Path(name_or_path)
    if not CATALOG_NAME_RE.match(name_or_path):
        raise ValueError(f"catalog 이름 규칙 위반 (regex {CATALOG_NAME_RE.pattern}): {name_or_path!r}")
    return CATALOG_DIR / f"{name_or_path}.yaml"


def load_catalogs(catalog_names: list[str]) -> list[dict]:
    """여러 catalog 합집합 + cross-catalog dedup. 위반 시 ValueError.

    각 entry 에 `_catalog` 박혀 출처 추적 가능 (디버그용).
    """
    out: list[dict] = []
    cross_seen: dict[str, str] = {}  # url -> first-seen catalog name
    for name in catalog_names:
        p = _resolve_catalog_path(name)
        entries = _load_one_catalog(p)
        for e in entries:
            u = e["url"]
            if u in cross_seen:
                raise ValueError(
                    f"cross-catalog url 중복: {u!r}\n"
                    f"  먼저: {cross_seen[u]!r}\n"
                    f"  다시: {e['_catalog']!r}"
                )
            cross_seen[u] = e["_catalog"]
            out.append(e)
    return out


def _synth_url_entries(urls: list[str]) -> list[dict]:
    """`--url` 인자를 entry shape 으로 변환 — name = host."""
    out: list[dict] = []
    for u in urls:
        if not (u.startswith("http://") or u.startswith("https://")):
            raise ValueError(f"--url 이 http(s) 아님: {u!r}")
        if len(u) > 1000:
            raise ValueError(f"--url 1000자 초과: {u!r}")
        host = (urlparse(u).hostname or u)[:200]
        out.append({"name": host, "url": u, "_catalog": "<--url>"})
    return out


def _delete_markers(slug: str) -> list[str]:
    """slug 의 marker 파일 삭제. 삭제된 suffix 리스트 반환."""
    removed: list[str] = []
    for suf in MARKER_SUFFIXES:
        p = STATE_DIR / f"{slug}{suf}"
        if p.exists():
            try:
                p.unlink()
                removed.append(suf)
            except OSError as e:
                print(f"[batch] ⚠ {p.name} 삭제 실패: {e}", file=sys.stderr)
    return removed


def _latest_job_for_url(conn, url: str) -> Optional[dict]:
    """그 URL 의 가장 최근 register jobs row. 없으면 None."""
    row = conn.execute(
        "SELECT id, status, result_rc FROM jobs "
        "WHERE url=? AND kind='register' "
        "ORDER BY id DESC LIMIT 1",
        (url,),
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "status": row["status"], "result_rc": row["result_rc"]}


def _parse_rc_list(s: str) -> set[int]:
    out: set[int] = set()
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.add(int(tok))
        except ValueError as e:
            raise ValueError(f"--rc list 의 정수 아님: {tok!r}") from e
    if not out:
        raise ValueError("--rc 가 비어있음")
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="catalog 일괄 enqueue (N100 만)")
    p.add_argument("--catalog", action="append", default=[],
                   help="catalog 이름 (파일명 stem). 반복 가능. e.g. --catalog=2026-05-20")
    p.add_argument("--url", action="append", default=[],
                   help="직접 URL allowlist. 반복 가능. catalog 무관.")
    p.add_argument("--failed", action="store_true",
                   help=f"rc∈{FAILED_PRESET_RCS} 인 URL retry (마커 자동 clear)")
    p.add_argument("--rc", default="",
                   help="rc filter (comma-list). e.g. --rc=1,-99. 해당 rc URL retry (마커 자동 clear)")
    p.add_argument("--force", action="store_true",
                   help="jobs row / marker 다 무시. filter override.")
    p.add_argument("--limit", type=int, default=0, help="enqueue 상한 (0=무한)")
    p.add_argument("--dry-run", action="store_true", help="enqueue 안 함, 분포만 출력")
    args = p.parse_args(argv)

    if not args.catalog and not args.url:
        print("[batch] --catalog 또는 --url 중 하나 이상 필요", file=sys.stderr)
        return 4
    if args.failed and args.rc:
        print("[batch] --failed 와 --rc 동시 사용 불가", file=sys.stderr)
        return 4

    # rc filter set
    rc_filter: Optional[set[int]] = None
    if args.failed:
        rc_filter = set(FAILED_PRESET_RCS)
    elif args.rc:
        try:
            rc_filter = _parse_rc_list(args.rc)
        except ValueError as e:
            print(f"[batch] {e}", file=sys.stderr)
            return 4

    # Scope: catalog files + direct urls. cross-catalog dedup.
    try:
        entries = load_catalogs(args.catalog) if args.catalog else []
        if args.url:
            url_entries = _synth_url_entries(args.url)
            catalog_urls = {e["url"] for e in entries}
            entries.extend(e for e in url_entries if e["url"] not in catalog_urls)
    except FileNotFoundError as e:
        print(f"[batch] {e}", file=sys.stderr)
        return 3
    except (ValueError, OSError) as e:
        print(f"[batch] catalog 검증 실패: {e}", file=sys.stderr)
        return 2

    if not entries:
        print("[batch] entry 없음 — catalog 비어있거나 --url 0개", file=sys.stderr)
        return 4

    conn = db.connect()
    try:
        enqueued = 0
        skipped = 0
        markers_cleared = 0
        considered = 0
        for e in entries:
            if args.limit and considered >= args.limit:
                break
            considered += 1
            name = e["name"]
            url = e["url"]
            slug = url_to_slug(url)
            latest = _latest_job_for_url(conn, url)

            # Filter decision tree.
            if args.force:
                # 강제 — 모두 통과. 마커 삭제.
                pass
            elif rc_filter is not None:
                # 재시도 filter — latest job 이 그 rc set 에 들어야 함.
                if latest is None or latest["result_rc"] not in rc_filter:
                    skipped += 1
                    continue
            else:
                # default untried — jobs row 없는 것만.
                if latest is not None:
                    skipped += 1
                    print(f"  [skip ] {name[:40]:<40} {url[:80]}")
                    continue

            # 마커 삭제 — force 또는 rc-filter retry.
            if args.force or rc_filter is not None:
                removed = _delete_markers(slug)
                if removed:
                    markers_cleared += 1
                    print(f"  [clear] {name[:40]:<40} markers={','.join(removed)}")

            if args.dry_run:
                print(f"  [DRY  ] {name[:40]:<40} {url[:80]}")
                continue

            job_id, inserted = db.enqueue_job(
                conn, kind="register", url=url, slug=slug,
                via="batch", requested_by=None,
                ack_channel_id=None, ack_message_id=None,
                sub_payload=None, dedupe=True,
            )
            if inserted:
                enqueued += 1
                print(f"  [enq  ] #{job_id:<6} {name[:40]:<40} {url[:80]}")
            else:
                skipped += 1
                print(f"  [dup  ] #{job_id:<6} {name[:40]:<40} (pending/running 이미 존재)")
    finally:
        conn.close()

    mode = ("force" if args.force
            else "failed" if args.failed
            else "rc" if args.rc
            else "untried")
    catalogs_label = ",".join(args.catalog) if args.catalog else "-"
    urls_label = f"+{len(args.url)} urls" if args.url else ""
    print(f"\n[batch] catalogs=[{catalogs_label}] {urls_label} entries={len(entries)} "
          f"considered={considered} enqueued={enqueued} skipped={skipped} "
          f"markers_cleared={markers_cleared} mode={mode} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
