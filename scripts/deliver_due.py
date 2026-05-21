"""발송창 flush (ADR 0006) — 봇 1분 tick 이 due 수신처가 있을 때 이 스크립트를 subprocess 로 띄운다.

흐름:
  1. 지금 KST HH:MM 도래 + 오늘 미발송 수신처(user_settings/channel_settings) 를 db.due_targets 로 뽑음.
  2. 수신처별로 빚진 글 계산 — posts ⨝ (그 수신처 구독 slug) − deliveries(수신처).
     created_at 하한으로 신규 구독자 백로그 폭탄 차단 (codex CRITICAL).
  3. 후보 글 요약 — posts.summary 캐시 있으면 재사용, 없으면 1회 계산 후 캐시 (lazy).
  4. 필터 — 같은 slug 의 여러 구독자 필터를 OR (한 명이라도 통과시키면 발송). 채널 OR 보존.
  5. digest 묶음 1개로 발송 (REST). 성공 시 deliveries + last_delivered_date 박음 (하루 1회 멱등).
  6. 새 글 0 + notify_empty 구독 있으면 "새 공지 없음" 한 줄.
  7. posts TTL GC (prune_posts).

봇 event loop 비블록 위해 *subprocess* 로 분리 (LLM·blocking Discord·sleep 포함). [codex HIGH]

사용:
    python scripts/deliver_due.py
    python scripts/deliver_due.py --dry-run
    python scripts/deliver_due.py --force-target dm:123456   # 시각·멱등 무시하고 그 수신처 즉시 flush (디버그)
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import db  # noqa: E402
from bot.config import bot_token  # noqa: E402
from bot.runtime_config import settings  # noqa: E402
from bot.discord_rest import deliver, CannotDeliver, DiscordRestError  # noqa: E402
from engine.tracing import start_trace, current_trace  # noqa: E402
from generate import client_for  # noqa: E402

# notify.py 의 요약·필터·포맷 헬퍼 재사용 (단일 진실원천 — 발송 로직 중복 X).
from scripts.notify import summarize_post, filter_pass, digest_chunks  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KST = db.KST


def _ensure_summary(conn, slug: str, post: dict, sum_client) -> str:
    """posts.summary 캐시 있으면 재사용, 없으면 1회 계산 후 캐시 (lazy). post 는 sqlite3.Row 또는 dict."""
    cached = post["summary"] if "summary" in post.keys() else None
    if cached:
        return cached
    s = summarize_post(sum_client, dict(post), slug=slug)
    db.set_post_summary(conn, slug, post["post_id"], s)
    return s


def flush_target(conn, tok: Optional[str], target: dict, *, today_kst: str, dry_run: bool) -> int:
    """한 수신처 발송창 flush. 반환 = 발송한 글 수 (notify_empty 한 줄은 0 으로 침)."""
    target_kind = target["target_kind"]
    target_id = target["target_id"]
    subs = db.subscriptions_for_target(conn, target_id)
    if not subs:
        # 설정 행은 있으나 구독 0 — 발송창만 닫고 종료 (오늘 다시 안 깨어나게).
        if not dry_run:
            db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        return 0

    subs_by_slug: dict[str, list] = defaultdict(list)
    for s in subs:
        subs_by_slug[s["slug"]].append(s)
    any_notify_empty = any(int(s["notify_empty"]) for s in subs)

    sum_client = client_for("notify_summarize")
    flt_client = client_for("notify_filter")

    owed: list = []  # 발송 확정 글 (sqlite3.Row)
    for slug, slug_subs in subs_by_slug.items():
        # 그 slug 구독 중 가장 이른 created_at 하한 — 그 전 글은 어느 구독도 안 받음 (백로그 차단).
        since = min(s["created_at"] for s in slug_subs)
        posts = db.posts_for_slug_since(conn, slug, since)
        for post in posts:
            pid = str(post["post_id"])
            if db.was_delivered(conn, slug, pid, target_id):
                continue
            summary = _ensure_summary(conn, slug, post, sum_client)
            # OR 필터 — 한 구독자라도 통과(또는 필터 없음)면 발송. 채널 다중 구독자 OR 보존.
            passed = False
            for s in slug_subs:
                fp = s["filter_prompt"]
                if not fp:
                    passed = True
                    break
                if filter_pass(flt_client, fp, dict(post), summary, slug=slug):
                    passed = True
                    break
            if passed:
                # post 는 fetch 시점 Row 스냅샷 — summary 컬럼이 NULL 이라
                # 방금 계산/캐시한 summary 를 행에 붙여 digest 에 실리게 함.
                post_d = dict(post)
                post_d["summary"] = summary
                owed.append(post_d)

    when = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    if not owed:
        if any_notify_empty:
            content = f"📭 오늘({today_kst}) 새로 올라온 공지가 없어요."
            if dry_run:
                print(f"\n--- [{target_kind}:{target_id} EMPTY] ---\n{content}\n")
            elif tok:
                try:
                    deliver(tok, target_kind=target_kind, target_id=target_id, content=content)
                except (CannotDeliver, DiscordRestError) as e:
                    print(f"  ✗ {target_kind}:{target_id} empty 발송 실패: {e}", file=sys.stderr)
        if not dry_run:
            db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        return 0

    chunks = digest_chunks(owed)
    if dry_run:
        for ch in chunks:
            print(f"\n--- [{target_kind}:{target_id} DIGEST] ---\n{ch}\n")
        return len(owed)

    if not tok:
        print(f"  ✗ {target_kind}:{target_id}: BOT_TOKEN 없음 — 발송 불가", file=sys.stderr)
        return 0

    # 모든 chunk 발송 성공해야 deliveries + 발송창 닫음. 실패 시 last_delivered_date 안 박음 →
    # 다음 tick catch-up (이미 보낸 chunk 재전송 가능성 = at-least-once. 드문 실패라 수용).
    ok_all = True
    with current_trace().span("deliver_digest",
                              attrs={"target_kind": target_kind, "target_id": target_id,
                                     "n_posts": len(owed), "n_chunks": len(chunks)}):
        for ch in chunks:
            try:
                deliver(tok, target_kind=target_kind, target_id=target_id, content=ch)
                time.sleep(0.8)
            except (CannotDeliver, DiscordRestError) as e:
                ok_all = False
                print(f"  ✗ {target_kind}:{target_id} digest chunk 발송 실패: {e}", file=sys.stderr)
                break
    if ok_all:
        for post in owed:
            db.mark_delivered(conn, post["slug"], str(post["post_id"]), target_id)
        db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        print(f"  ✅ {target_kind}:{target_id} digest {len(owed)}건 ({when})")
    return len(owed) if ok_all else 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="발송창 flush (ADR 0006)")
    p.add_argument("--dry-run", action="store_true", help="발송 안 하고 출력만")
    p.add_argument("--force-target", default=None,
                   help="시각·멱등 무시하고 이 수신처 즉시 flush (형식 kind:id, 예 dm:123 / channel:456)")
    p.add_argument("--keep-days", type=int, default=settings.poll.posts_keep_days,
                   help="posts TTL GC 보존 일수")
    args = p.parse_args(argv)

    tok = bot_token()
    conn = db.connect()
    now_kst = datetime.now(KST)
    now_hhmm = now_kst.strftime("%H:%M")
    today = now_kst.strftime("%Y-%m-%d")

    with start_trace("deliver_due", attrs={"now_hhmm": now_hhmm, "today": today}):
        if args.force_target:
            kind, _, tid = args.force_target.partition(":")
            targets = [{"target_kind": kind, "target_id": tid, "deliver_at": now_hhmm}]
        else:
            targets = db.due_targets(conn, now_hhmm=now_hhmm, today_kst=today)
        if not targets:
            return 0
        print(f"[deliver_due] {now_hhmm} KST — due 수신처 {len(targets)}건")
        total = 0
        for target in targets:
            try:
                total += flush_target(conn, tok, target, today_kst=today, dry_run=args.dry_run)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠ flush 예외 {target}: {e!r}", file=sys.stderr)
        # TTL GC — due 가 있던 run 에서만 (매분 GC 회피).
        if not args.dry_run:
            n_pruned = db.prune_posts(conn, keep_days=args.keep_days)
            if n_pruned:
                print(f"[deliver_due] posts GC {n_pruned}건 삭제")
        print(f"[deliver_due] 총 {total}건 발송")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
