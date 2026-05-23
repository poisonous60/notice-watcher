"""기존 subscriptions row 의 display_title NULL/빈 값 backfill — URL 다시 fetch + HTML <title> 추출.

v2 (commit 2c559e5) 이전에 등록된 sub 은 register.py 가 title 안 박았어서 NULL.
이 script 한 번 돌려 모든 NULL sub 의 display_title 채움. 이후 /list UI 가 예쁜 title 표시.

같은 URL 여러 sub 가 가질 수 있어 *URL 단위 cache* — fetch 1회 / URL.

사용: python scripts/backfill_display_title.py [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import html as html_mod
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # type: ignore

from bot import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("backfill")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


async def fetch_title(url: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(url, headers={"User-Agent": _UA,
                                           "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"},
                              timeout=15.0, follow_redirects=True)
    except (httpx.HTTPError, OSError) as e:
        log.warning("fetch fail %s: %r", url, e)
        return None
    if r.status_code >= 400:
        log.warning("http %d %s", r.status_code, url)
        return None
    m = _TITLE_RE.search(r.text)
    if not m:
        return None
    title = html_mod.unescape(m.group(1)).strip()
    title = re.sub(r"\s+", " ", title)
    return (title[:200] or None) if title else None


async def main_async(dry_run: bool) -> int:
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, url, display_title FROM subscriptions "
        "WHERE display_title IS NULL OR display_title=''"
    ).fetchall()
    if not rows:
        log.info("backfill 대상 0건 — 모두 채워져 있음")
        return 0
    log.info("backfill 대상 %d건", len(rows))

    url_cache: dict[str, str | None] = {}
    async with httpx.AsyncClient() as client:
        for r in rows:
            url = r["url"]
            if url in url_cache:
                title = url_cache[url]
            else:
                title = await fetch_title(url, client)
                url_cache[url] = title
                log.info("fetched: %s → %s", url, title or "(없음)")
            if not title:
                continue
            if dry_run:
                log.info("[dry-run] would UPDATE id=%d title=%s", r["id"], title)
            else:
                conn.execute("UPDATE subscriptions SET display_title=? WHERE id=?",
                             (title, r["id"]))
        if not dry_run:
            conn.commit()
            log.info("commit 완료")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="UPDATE 안 함, fetch + log 만")
    args = ap.parse_args()
    return asyncio.run(main_async(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
