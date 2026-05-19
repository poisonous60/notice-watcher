"""사이트 카탈로그 일괄 enqueue driver (rev4).

`configs/candidates/catalog.yaml` (schema 2: name + url) 를 읽어 각 entry url 마다
N100 의 bot.sqlite3 jobs 테이블에 `kind='register', via='batch'` 잡을 enqueue.
실행은 N100 만 — bot worker 가 `/preview` 와 동일한 path 로 처리.

설계: `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §5.

사용 (N100 에서):
    python scripts/register_batch.py                # untried-only enqueue (default)
    python scripts/register_batch.py --limit=10     # 처음 10개만 enqueue
    python scripts/register_batch.py --dry-run      # enqueue 안 함, 분포만
    python scripts/register_batch.py --url URL …    # 명시한 URL 만 retry (마커 삭제 + enqueue).
                                                    # 호출자가 'root-cause 고쳐졌다' 단정한 사이트만.
    python scripts/register_batch.py --force        # catalog 의 모든 entry enqueue + 마커 삭제
                                                    # (재현 테스트·전체 평가용. unfixed 사이트 retry 비용 주의)

rc:
    0  정상 종료
    2  catalog 로드/검증 실패
    3  catalog 파일 없음
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("PyYAML 필요: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import db  # noqa: E402
from probe.paths import url_to_slug  # noqa: E402

CATALOG_DEFAULT = ROOT / "configs" / "candidates" / "catalog.yaml"
STATE_DIR = ROOT / "output" / "poll_state"
MARKER_SUFFIXES = (".REJECTED.json", ".FAILED.json", ".BUG.json")


def load_catalog(path: Path) -> list[dict]:
    """yaml 읽어 entries (name+url) 리스트 반환. schema 위반 시 ValueError.

    schema 2 강제: 각 entry 는 name + url 만. url 중복 거부.
    """
    if not path.exists():
        raise FileNotFoundError(f"catalog 경로 없음: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"catalog YAML 파싱 실패: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError("catalog 루트가 mapping 아님")
    schema = doc.get("schema")
    if schema != 2:
        raise ValueError(f"catalog schema={schema!r} — rev4 는 schema=2 만 지원 (name+url)")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise ValueError("`entries` 가 list 가 아님")
    seen_urls: set[str] = set()
    out: list[dict] = []
    for i, e in enumerate(entries):
        ctx = f"entries[{i}]"
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
            raise ValueError(f"{ctx}: url 중복 {url!r}")
        seen_urls.add(url)
        out.append({"name": name.strip(), "url": url})
    return out


def _delete_markers(slug: str) -> list[str]:
    """`--force` 일 때 같은 slug 의 marker 파일 삭제. 삭제된 suffix 리스트 반환."""
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


def _url_has_job(conn, url: str) -> bool:
    """jobs 테이블에 같은 url 의 row (any status) 가 있는지."""
    row = conn.execute("SELECT 1 FROM jobs WHERE url=? LIMIT 1", (url,)).fetchone()
    return row is not None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="catalog 일괄 enqueue (N100 만)")
    p.add_argument("--catalog", default=str(CATALOG_DEFAULT),
                   help=f"catalog.yaml 경로 (기본 {CATALOG_DEFAULT.relative_to(ROOT)})")
    p.add_argument("--limit", type=int, default=0, help="enqueue 상한 (0=무한)")
    p.add_argument("--dry-run", action="store_true", help="enqueue 안 함, 분포만 출력")
    p.add_argument("--url", action="append", default=[],
                   help="명시한 URL 만 retry (반복 가능). catalog 안 URL 만 허용. "
                        "마커 삭제 + enqueue. 호출자가 root-cause 고쳤다고 단정한 사이트용. "
                        "default mode 의 skip-if-jobs-exist 우회.")
    p.add_argument("--force", action="store_true",
                   help="catalog 의 모든 entry enqueue + 같은 slug 의 .REJECTED/.FAILED/.BUG.json 마커 삭제. "
                        "재현 테스트용. unfixed 사이트도 다시 LLM 호출 → 토큰 낭비 주의.")
    args = p.parse_args(argv)
    if args.url and args.force:
        print("[batch] --url 과 --force 동시 사용 불가 (의도 충돌)", file=sys.stderr)
        return 2

    catalog_path = Path(args.catalog)
    try:
        entries = load_catalog(catalog_path)
    except FileNotFoundError as e:
        print(f"[batch] {e}", file=sys.stderr)
        return 3
    except (ValueError, OSError) as e:
        print(f"[batch] catalog 검증 실패: {e}", file=sys.stderr)
        return 2

    # --url allowlist 검증 — catalog 안 URL 만 허용 (typo 가 silent no-op 안 되게).
    allow_urls: Optional[set[str]] = None
    if args.url:
        catalog_urls = {e["url"] for e in entries}
        bad = [u for u in args.url if u not in catalog_urls]
        if bad:
            print(f"[batch] --url 인자 catalog 에 없음: {bad}", file=sys.stderr)
            return 2
        allow_urls = set(args.url)

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

            # --url allowlist: 그 외 URL 은 무조건 skip (조용히).
            if allow_urls is not None and url not in allow_urls:
                skipped += 1
                continue

            # default mode: jobs row 있으면 skip. --url / --force 는 skip 안 함.
            if not args.force and allow_urls is None and _url_has_job(conn, url):
                skipped += 1
                print(f"  [skip ] {name[:40]:<40} {url[:80]}")
                continue

            # 마커 삭제 — --force 또는 --url (둘 다 retry 의도).
            if args.force or allow_urls is not None:
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

    mode = "url-allowlist" if allow_urls else ("force" if args.force else "untried-only")
    print(f"\n[batch] catalog={catalog_path.relative_to(ROOT)} entries={len(entries)} "
          f"considered={considered} enqueued={enqueued} skipped={skipped} "
          f"markers_cleared={markers_cleared} mode={mode} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
