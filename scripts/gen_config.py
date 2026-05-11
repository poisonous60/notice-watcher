"""URL → (경량 probe) → digest → gemini → config 자동 생성. (M3 수동 실행용 CLI)

사용:
    GEMINI_API_KEY=...  python scripts/gen_config.py "https://cse.skku.edu/cse/notice.do?mode=list&srCategoryId1=1582"
    python scripts/gen_config.py "<URL>" --reuse-probe       # 이미 probe 산출물 있으면 재사용(probe 안 돌림)
    python scripts/gen_config.py "<URL>" --out configs/foo.json --sanity   # 저장 + fetch_list 1회 sanity 체크
    python scripts/gen_config.py --slug <probe-slug>          # 이미 probe 한 slug 로 바로 digest→gemini

필요: GEMINI_API_KEY (또는 GOOGLE_API_KEY). 모델은 GEMINI_MODEL 로 override (기본 gemini-2.5-flash).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probe.paths import output_dir, url_to_slug  # noqa: E402
from engine.digest import build_digest  # noqa: E402
from engine import make_adapter, validate_config  # noqa: E402
from generate import generate_config, default_model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _run_probe(url: str, *, lite: bool) -> None:
    mode = "경량(lite)" if lite else "full"
    print(f"[gen_config] {mode} probe 실행: {url}")
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), url, "--no-paid", "--no-crawl4ai"]
    if lite:
        cmd.append("--lite")
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"probe 실패 (rc={rc})")


async def _sanity_check(cfg: dict) -> None:
    print("[gen_config] sanity: fetch_list(page=1) ...")
    async with make_adapter(cfg) as a:
        posts = await a.fetch_list(page=1, page_size=15)
        print(f"  → {len(posts)}건. 앞 3건:")
        for p in posts[:3]:
            print(f"    {p.post_id}  {p.published_at}  {(p.title or '')[:60]}  url={p.url}")
        if posts:
            full = await a.fetch_article(posts[0])
            print(f"  fetch_article({posts[0].post_id}): body={len(full.content_html or '')} chars")


def main(argv) -> int:
    p = argparse.ArgumentParser(description="URL → digest → gemini → config")
    p.add_argument("url", nargs="?", help="목록 URL")
    p.add_argument("--slug", help="이미 probe 한 산출물 slug (url 대신)")
    p.add_argument("--reuse-probe", action="store_true", help="probe 산출물이 이미 있으면 probe 재실행 안 함")
    p.add_argument("--full-probe", action="store_true", help="처음부터 full probe (lite 대신)")
    p.add_argument("--escalate", action="store_true", help="lite probe 로 만든 config 가 실패하면 full probe 로 재시도")
    p.add_argument("--out", help="config 저장 경로 (없으면 stdout 만)")
    p.add_argument("--sanity", action="store_true", help="생성 후 fetch_list/fetch_article 1회 sanity 체크")
    p.add_argument("--model", help="Gemini 모델 (기본: GEMINI_MODEL env 또는 gemini-2.5-flash)")
    args = p.parse_args(argv)

    if not args.url and not args.slug:
        p.error("url 또는 --slug 필요")

    if args.slug:
        slug = args.slug
        url = None
    else:
        url = args.url
        slug = url_to_slug(url)
        out_dir = output_dir(slug)
        if not (args.reuse_probe and out_dir.exists() and (out_dir / "diagnosis.json").exists()):
            _run_probe(url, lite=not args.full_probe)

    print(f"[gen_config] digest 구성: slug={slug}")
    digest = build_digest(slug=slug, url=url)

    print(f"[gen_config] gemini 호출: model={args.model or default_model()}")
    try:
        cfg = generate_config(digest, model=args.model)
    except Exception as e:
        if not (args.escalate and url and not args.full_probe):
            raise
        print(f"[gen_config] lite 기반 생성 실패: {e}\n[gen_config] full probe 로 escalate ...")
        _run_probe(url, lite=False)
        digest = build_digest(slug=slug, url=url)
        cfg = generate_config(digest, model=args.model)
    print("[gen_config] 생성됨 + validate_config 통과:")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[gen_config] → {args.out}")

    if args.sanity:
        validate_config(cfg)
        asyncio.run(_sanity_check(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
