"""발송창 flush (ADR 0006) — 봇 1분 tick 이 due 수신처가 있을 때 이 스크립트를 subprocess 로 띄운다.

ADR 0017 — runs 추적:
  notify_runs 1 row / 호출 1회. notify_target_runs 1 row / target 1회. dashboard `/runs` 에서
  현재 in-flight + 최근 발송 결과 surface. process 죽으면 reaper 가 'crashed' 박음.



흐름:
  1. 지금 KST HH:MM 도래 + 오늘 미발송 수신처(user_settings/channel_settings) 를 db.due_targets 로 뽑음.
  2. 수신처별로 빚진 글 계산 — posts ⨝ (그 수신처 구독 slug) − deliveries(수신처).
     created_at 하한으로 신규 구독자 백로그 폭탄 차단 (codex CRITICAL).
  3. 후보 글 요약 — posts.summary 캐시 있으면 재사용, 없으면 1회 계산 후 캐시 (lazy).
  4. 필터 — 같은 slug 의 여러 구독자 필터를 OR (한 명이라도 통과시키면 발송). 채널 OR 보존.
  5. digest 묶음 1개로 발송 (REST). 성공 시 deliveries + last_delivered_date 박음 (하루 1회 멱등).
  6. slug 별 새 글 0 + notify_empty 구독 있으면 "새 공지 없음" 알림.
  7. posts TTL GC (prune_posts).

봇 event loop 비블록 위해 *subprocess* 로 분리 (LLM·blocking Discord·sleep 포함). [codex HIGH]

테스트 모드 (B — 2026-05-25 incident 후속):
  env `NOTIFY_TEST_TARGETS` 가 설정되면 = 발송 allow-list. 형식 = 쉼표 구분 `kind:id` (예
  `dm:123,channel:456`). 특수 값 `owner` = `dm:<OWNER_USER_ID>` 로 확장. allow-list 에 *없는*
  수신처는 *dry-print* 만 (실제 발송 X · last_delivered_date 도 안 박음 → 다음 tick 에 다시 due
  → env 풀면 자연 회복). bot.sqlite3 변경 0 — 위험한 코드 push 직후 owner 만 수신 검증할 때 사용.

사용:
    python scripts/deliver_due.py
    python scripts/deliver_due.py --dry-run
    python scripts/deliver_due.py --force-target dm:123456   # 시각·멱등 무시하고 그 수신처 즉시 flush (디버그)
    NOTIFY_TEST_TARGETS=owner python scripts/deliver_due.py  # owner DM 만 실제 발송, 나머지는 dry-print
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import db  # noqa: E402
from bot.config import bot_token, owner_user_id  # noqa: E402
from bot.runtime_config import settings  # noqa: E402
from bot.discord_rest import deliver, CannotDeliver, DiscordRestError  # noqa: E402
from bot.site_ops import is_broken, broken_info  # noqa: E402
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


def _empty_notice_content(*, today_kst: str, slugs: list[str]) -> str:
    if len(slugs) == 1:
        return f"📭 `{slugs[0]}` — 오늘({today_kst}) 새로 올라온 공지가 없어요."
    lines = [f"📭 오늘({today_kst}) 새로 올라온 공지가 없는 구독이에요."]
    lines.extend(f"- `{slug}`" for slug in slugs)
    return "\n".join(lines)


def _status_notice_content(*, today_kst: str,
                            empty_slugs: list[str],
                            broken_items: list[dict]) -> Optional[str]:
    """digest 뒤 *target 당 trailing status notice 1개* — empty + broken 합쳐서.

    broken_items = [{"slug": str, "cb": int}, ...] (cb 가 큰 순서 권장).
    둘 다 비어 있으면 None 반환 (호출자가 발송 skip).
    HIGH E 가드 — 같은 target 에 trailing message 가 2개 이상 가지 않도록 한 함수에서 조립.
    """
    if not empty_slugs and not broken_items:
        return None
    parts: list[str] = []
    if broken_items:
        if len(broken_items) == 1:
            it = broken_items[0]
            parts.append(
                f"❗ `{it['slug']}` 사이트가 며칠째 깨져 있어요 (연속 실패 {it['cb']}회). "
                f"봇이 자동 복구 시도 중이에요 — 풀리면 다시 알림 가요."
            )
        else:
            parts.append("❗ 깨져 있는 구독이 있어요 (봇이 자동 복구 시도 중):")
            for it in broken_items:
                parts.append(f"- `{it['slug']}` (연속 실패 {it['cb']}회)")
    if empty_slugs:
        if len(empty_slugs) == 1:
            parts.append(f"📭 `{empty_slugs[0]}` — 오늘({today_kst}) 새로 올라온 공지가 없어요.")
        else:
            parts.append(f"📭 오늘({today_kst}) 새로 올라온 공지가 없는 구독이에요.")
            for s in empty_slugs:
                parts.append(f"- `{s}`")
    return "\n".join(parts)


def flush_target(conn, tok: Optional[str], target: dict, *, today_kst: str, dry_run: bool,
                  run_id: Optional[int] = None, test_skip: bool = False) -> tuple[int, str]:
    """한 수신처 발송창 flush. 반환 = (n_posts, status).

    ADR 0017 — run_id 가 주어지면 finish 시 `notify_target_run_finish` 호출 (best-effort).
    status enum: 'ok'/'empty'/'no_subs'/'failed'/'exception'/'skipped_test_target'.
    test_skip=True (codex MED 1) — NOTIFY_TEST_TARGETS allow-list 밖 → status='skipped_test_target'.
    main 의 aggregator 가 status 보고 정확히 분류 (codex MED 2 — n_targets_failed 과 n_empty_notices
    구분, 옛 코드는 n=0 만으로 empty 처리해 failed/no_subs 도 empty 카운터에 더했음).
    """
    target_kind = target["target_kind"]
    target_id = target["target_id"]
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    final_status = "exception"
    n_owed = 0
    n_chunks = 0
    err_msg: Optional[str] = None
    try:
        n_owed, inner_status, n_chunks = _flush_target_inner(
            conn, tok, target, today_kst=today_kst, dry_run=dry_run)
        # test_skip 이면 inner 결과 무관 = 'skipped_test_target' (dashboard 가 dry-run 분리)
        final_status = "skipped_test_target" if test_skip else inner_status
        return n_owed, final_status
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e!r}"
        raise
    finally:
        if run_id is not None:
            try:
                db.notify_target_run_finish(
                    conn, run_id=run_id, target_kind=target_kind, target_id=target_id,
                    started_at=started_at, ended_at=datetime.now(timezone.utc).isoformat(),
                    status=final_status, n_posts=n_owed, n_chunks=n_chunks,
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    error_msg=err_msg,
                )
            except Exception:
                pass


def _flush_target_inner(conn, tok: Optional[str], target: dict, *, today_kst: str,
                         dry_run: bool) -> tuple[int, str, int]:
    """flush_target 본체 — (n_owed, status, n_chunks) 반환. status enum 정의 ADR 0017 §2a."""
    target_kind = target["target_kind"]
    target_id = target["target_id"]
    subs = db.subscriptions_for_target(conn, target_id)
    if not subs:
        # 설정 행은 있으나 구독 0 — 발송창만 닫고 종료 (오늘 다시 안 깨어나게).
        if not dry_run:
            db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        return 0, "no_subs", 0

    subs_by_slug: dict[str, list] = defaultdict(list)
    for s in subs:
        subs_by_slug[s["slug"]].append(s)

    sum_client = client_for("notify_summarize")
    flt_client = client_for("notify_filter")

    owed: list = []  # 발송 확정 글 (sqlite3.Row)
    empty_slugs: list[str] = []
    broken_items: list[dict] = []  # [{"slug": str, "cb": int}] — owed=0 + notify_empty=1 + BROKEN sidecar 존재
    for slug, slug_subs in subs_by_slug.items():
        # 그 slug 구독 중 가장 이른 created_at 하한 — 그 전 글은 어느 구독도 안 받음 (백로그 차단).
        since = min(s["created_at"] for s in slug_subs)
        posts = db.posts_for_slug_since(conn, slug, since)
        n_slug_owed = 0
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
                n_slug_owed += 1
        # owed=0 + notify_empty=1 인 slug 만 status notice 후보. owed>0 면 digest 가 곧 정상 알림이므로 status 제외.
        if n_slug_owed == 0 and any(int(s["notify_empty"]) for s in slug_subs):
            if is_broken(slug):
                info = broken_info(slug) or {}
                broken_items.append({
                    "slug": slug,
                    "cb": int(info.get("consecutive_breakage", 0) or 0),
                })
            else:
                empty_slugs.append(slug)

    when = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    # cb 큰 순서 (운영자가 더 심각한 slug 먼저 보게).
    broken_items.sort(key=lambda it: -int(it.get("cb", 0)))

    # HIGH D 가드 — status 보내기 직전 다시 `is_broken` 체크. owed=0 path 와 digest+trailing path
    # 둘 다에서 한 번 더 필터링 (그 사이 reprobe 성공 → BROKEN unlink 됐을 수 있음).
    def _recheck_broken(items: list[dict]) -> list[dict]:
        return [it for it in items if is_broken(it["slug"])]

    if not owed:
        broken_items = _recheck_broken(broken_items)
        status_notice = _status_notice_content(today_kst=today_kst,
                                                empty_slugs=empty_slugs,
                                                broken_items=broken_items)
        if status_notice:
            if dry_run:
                print(f"\n--- [{target_kind}:{target_id} STATUS] ---\n{status_notice}\n")
            elif tok:
                try:
                    deliver(tok, target_kind=target_kind, target_id=target_id, content=status_notice)
                except (CannotDeliver, DiscordRestError) as e:
                    print(f"  ✗ {target_kind}:{target_id} status 발송 실패: {e}", file=sys.stderr)
        if not dry_run:
            db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        # status enum 호환 — owed=0 이면 기존 'empty' 코드 그대로 (notify_runs aggregator 호환).
        return 0, "empty", 0

    chunks = digest_chunks(owed)
    if dry_run:
        for ch in chunks:
            print(f"\n--- [{target_kind}:{target_id} DIGEST] ---\n{ch}\n")
        broken_items = _recheck_broken(broken_items)
        status_notice = _status_notice_content(today_kst=today_kst,
                                                empty_slugs=empty_slugs,
                                                broken_items=broken_items)
        if status_notice:
            print(f"\n--- [{target_kind}:{target_id} STATUS] ---\n{status_notice}\n")
        return len(owed), "ok", len(chunks)

    if not tok:
        print(f"  ✗ {target_kind}:{target_id}: BOT_TOKEN 없음 — 발송 불가", file=sys.stderr)
        return 0, "failed", len(chunks)

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
        # HIGH E 가드 — chunk 발송 *직전* 이 아니라 *직후* (digest 완전 land 한 다음) status 보냄.
        # chunk 실패 시 status 도 안 보냄 (window 도 안 닫음).
        broken_items = _recheck_broken(broken_items)
        status_notice = _status_notice_content(today_kst=today_kst,
                                                empty_slugs=empty_slugs,
                                                broken_items=broken_items)
        if status_notice:
            try:
                deliver(tok, target_kind=target_kind, target_id=target_id, content=status_notice)
            except (CannotDeliver, DiscordRestError) as e:
                print(f"  ✗ {target_kind}:{target_id} status 발송 실패: {e}", file=sys.stderr)
        for post in owed:
            db.mark_delivered(conn, post["slug"], str(post["post_id"]), target_id)
        db.mark_setting_delivered(conn, target_kind=target_kind, target_id=target_id, today_kst=today_kst)
        print(f"  ✅ {target_kind}:{target_id} digest {len(owed)}건 ({when})")
        return len(owed), "ok", len(chunks)
    return 0, "failed", len(chunks)


class TestTargetsConfigError(SystemExit):
    """NOTIFY_TEST_TARGETS env 가 설정됐는데 유효 target 0개 — fail closed (codex HIGH)."""


def _parse_test_targets() -> tuple[bool, set[str]]:
    """env NOTIFY_TEST_TARGETS 파싱. (test_mode_requested, allow_list) 반환.

    형식: 쉼표 구분 `kind:id`. 특수 `owner` → `dm:<OWNER_USER_ID>`.
    test_mode_requested=False = env 미설정 (정상 발송).
    test_mode_requested=True + allow_list 비어있음 = 잘못된 설정 → fail closed (raise SystemExit).
    test_mode_requested=True + allow_list 채워있음 = allow-list 밖 target 은 dry-print only.
    """
    raw = os.environ.get("NOTIFY_TEST_TARGETS", "").strip()
    if not raw:
        return False, set()
    out: set[str] = set()
    bad: list[str] = []
    for tok in (t.strip() for t in raw.split(",")):
        if not tok:
            continue
        if tok.lower() == "owner":
            owner = owner_user_id()
            if owner:
                out.add(f"dm:{owner}")
            else:
                bad.append("owner (OWNER_USER_ID 미설정)")
            continue
        if ":" not in tok:
            bad.append(f"'{tok}' (형식 이상)")
            continue
        out.add(tok)
    if not out:
        # codex HIGH — env 명시했는데 유효 target 0 → fail closed (절대 실발송 X).
        raise TestTargetsConfigError(
            f"[deliver_due] ✗ NOTIFY_TEST_TARGETS='{raw}' 파싱 결과 유효 target 0개"
            f" (bad={bad}). fail closed — 실발송 방지 위해 exit 2."
        )
    return True, out


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

    try:
        test_mode_requested, test_allowed = _parse_test_targets()
    except TestTargetsConfigError as e:
        print(str(e), file=sys.stderr)
        return 2
    if test_mode_requested:
        print(f"[deliver_due] 🧪 NOTIFY_TEST_TARGETS — 실발송 allow-list={sorted(test_allowed)}, "
              f"나머지는 dry-print only", file=sys.stderr)

    with start_trace("deliver_due", attrs={"now_hhmm": now_hhmm, "today": today,
                                           "test_mode": bool(test_allowed)}):
        if args.force_target:
            kind, _, tid = args.force_target.partition(":")
            targets = [{"target_kind": kind, "target_id": tid, "deliver_at": now_hhmm}]
        else:
            targets = db.due_targets(conn, now_hhmm=now_hhmm, today_kst=today)
        if not targets:
            return 0
        print(f"[deliver_due] {now_hhmm} KST — due 수신처 {len(targets)}건")
        # ADR 0017 — notify_runs row 박음 (best-effort).
        try:
            args_json = json.dumps(argv, ensure_ascii=False)
        except Exception:
            args_json = None
        run_id = db.notify_run_start(
            conn, pid=os.getpid(), args_json=args_json,
            now_hhmm=now_hhmm, today_kst=today, n_due_targets=len(targets),
        )
        t_run = time.perf_counter()
        agg = {"n_targets_ok": 0, "n_targets_failed": 0,
               "n_posts_delivered": 0, "n_empty_notices": 0}
        total = 0
        for target in targets:
            key = f"{target['target_kind']}:{target['target_id']}"
            # test 모드: allow-list 밖이면 dry_run 강제 (last_delivered_date 안 박힘 → 다음 tick 재진입).
            # codex MED — dry-run path 의 결과를 *실발송* 카운터에 안 더한다 (대시보드 오해 방지).
            effective_dry = args.dry_run
            is_test_skip = bool(test_mode_requested and key not in test_allowed)
            if is_test_skip:
                effective_dry = True
                print(f"  🧪 {key} — NOTIFY_TEST_TARGETS 밖, dry-print only (실발송·멱등 박음 X)")
            try:
                n, status = flush_target(conn, tok, target, today_kst=today, dry_run=effective_dry,
                                          run_id=run_id, test_skip=is_test_skip)
                if is_test_skip:
                    # 카운터 분리 — 실발송 0 으로 침. notify_target_runs.status 는 'skipped_test_target'.
                    continue
                total += n
                # codex MED 2 — status 보고 정확히 분류. 옛 코드는 n=0 만으로 empty 처리해서 failed/no_subs
                # 까지 empty 카운터에 더했음 → n_targets_failed undercount.
                if status == "ok":
                    agg["n_targets_ok"] += 1
                    agg["n_posts_delivered"] += n
                elif status in ("failed", "exception"):
                    agg["n_targets_failed"] += 1
                else:
                    # 'empty' / 'no_subs' → 의도된 0 발송. dashboard 가 status 로 정확히 분류.
                    agg["n_empty_notices"] += 1
            except Exception as e:  # noqa: BLE001
                agg["n_targets_failed"] += 1
                print(f"  ⚠ flush 예외 {target}: {e!r}", file=sys.stderr)
        # TTL GC — due 가 있던 run 에서만 (매분 GC 회피).
        if not args.dry_run:
            n_pruned = db.prune_posts(conn, keep_days=args.keep_days)
            if n_pruned:
                print(f"[deliver_due] posts GC {n_pruned}건 삭제")
        print(f"[deliver_due] 총 {total}건 발송")
        # ADR 0017 — run finish + runs TTL GC (큰 부하 X — 매 cron 1회 idempotent).
        dur_ms = int((time.perf_counter() - t_run) * 1000)
        db.notify_run_finish(conn, run_id,
                              n_targets_ok=agg["n_targets_ok"],
                              n_targets_failed=agg["n_targets_failed"],
                              n_posts_delivered=agg["n_posts_delivered"],
                              n_empty_notices=agg["n_empty_notices"],
                              duration_ms=dur_ms)
        if not args.dry_run:
            try:
                db.prune_runs(conn)
            except Exception:
                pass
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
