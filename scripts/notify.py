"""폴링으로 모인 새 글(output/collected/<ts>/<slug>.new.json) → Gemini 요약 → 필터 → Discord 발송.

호출 경로:
  - poll_and_notify.py (notice-poll.service) → notify.py --no-digest (collected 새 글 즉시 발송).
    collected 처리 후 그 dir 에 .notified 마커 생성 → 이후 호출은 그 dir 스킵 (Gemini 중복 호출 방지).
  - notice-notify.timer (15분 간격) → notify.py (재시도용 — 발송 실패로 pending 에 남은 행만 flush).

발송 경로 (slug 별로):
  1. SQLite 구독(bot/db.py: subscriptions) → 봇 토큰으로 REST 직접(DM/채널).
       구독별 filter_prompt(자연어) → Gemini {include,reason} 로 골라냄(없으면 전부 통과).
       모든 구독 schedule='realtime' — 폴링 직후 즉시 발송. 큐 적재 없음(_migrate 가 일괄 변환).
  2. (Phase 1 / 봇 없는 경우) output/notify_targets.json = {"<slug>":"<webhook>"} 또는 NOTIFY_TARGETS_JSON 이 있으면 → webhook 발송 (해당 slug 에 SQLite 구독이 없을 때만; delivered.json 으로 중복 방지).

중복 방지: SQLite deliveries(slug,post_id,target_id) / webhook 은 delivered.json / 다이제스트는 digest_sent(target_id,schedule,kst_date).
봇 프로세스(bot/main.py)가 떠 있을 필요 없음 — 여기서 토큰으로 REST 직접 친다.

사용:
    python scripts/notify.py                 # 최신 collected 처리 + (레거시) pending flush 둘 다 — notice-notify.timer 가 켬
    python scripts/notify.py --no-collected  # collected 처리 스킵, flush 만
    python scripts/notify.py --dry-run       # 발송/DB 변경 없이 메시지만 출력
    python scripts/notify.py --collected-dir output/collected/20260511_210242
    python scripts/notify.py --no-digest     # flush 생략 (poll_and_notify 가 폴링 직후 이 플래그로 호출)
    python scripts/notify.py --heartbeat     # notify_empty=1 인 구독에 새 글 없으면 '새 공지 없음' 발송 (poll_and_notify 가 폴링 직후 켬)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate import GeminiClient, GeminiError, LLMError, parse_json  # noqa: E402
from generate import get_default_recorder, compute_cost, client_for, set_process_override  # noqa: E402
from generate.prompts import load_prompt, render_prompt  # noqa: E402
from bot import db  # noqa: E402
from bot.config import bot_token  # noqa: E402
from bot.discord_rest import deliver, post_webhook, CannotDeliver, DiscordRestError  # noqa: E402
from bot.runtime_config import settings  # noqa: E402
from engine.tracing import start_trace, current_trace  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLLECTED_DIR = ROOT / "output" / "collected"
DEFAULT_TARGETS = ROOT / "output" / "notify_targets.json"
DEFAULT_DELIVERED = ROOT / "output" / "delivered.json"
KST = timezone(timedelta(hours=9))


# --------------------------------------------------------------------------- #
# collected 디렉터리 / 새 글
# --------------------------------------------------------------------------- #
def latest_collected_dir() -> Optional[Path]:
    """가장 최근 '완료된 미처리 폴링 run' 디렉터리. poll_result.json 을 앵커로 사용.
    `.notified` 마커 있는 디렉터리는 이미 처리됨 → 스킵 (notify-timer 매 15분 호출 시 중복 Gemini 방지)."""
    if not COLLECTED_DIR.exists():
        return None
    dirs = sorted(d for d in COLLECTED_DIR.iterdir() if d.is_dir())  # 이름 = 타임스탬프 → 정렬 = 시간순
    for d in reversed(dirs):
        if (d / ".notified").exists():
            continue
        if (d / "poll_result.json").exists() or any(d.glob("*.new.json")):
            return d
    return None


def load_new_posts(collected_dir: Optional[Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not collected_dir or not collected_dir.exists():
        return out
    for f in sorted(collected_dir.glob("*.new.json")):
        slug = f.name[: -len(".new.json")]
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {f.name} 읽기 실패: {e}", file=sys.stderr)
            continue
        if isinstance(data, list) and data:
            out[slug] = data
    return out


# --------------------------------------------------------------------------- #
# webhook fallback bookkeeping
# --------------------------------------------------------------------------- #
def load_targets(path: Path) -> dict[str, str]:
    targets: dict[str, str] = {}
    if path.exists():
        try:
            targets.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {path} 읽기 실패: {e}", file=sys.stderr)
    env_json = os.environ.get("NOTIFY_TARGETS_JSON", "").strip()
    if env_json:
        try:
            targets.update(json.loads(env_json))
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] NOTIFY_TARGETS_JSON 파싱 실패: {e}", file=sys.stderr)
    return {str(k): str(v) for k, v in targets.items() if v}


def load_delivered(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    try:
        return {(str(s), str(p)) for s, p in json.loads(path.read_text(encoding="utf-8"))}
    except Exception:  # noqa: BLE001
        return set()


def save_delivered(path: Path, delivered: set[tuple[str, str]]) -> None:
    items = sorted(delivered)
    cap = settings.notify.delivered_cap
    if len(items) > cap:
        items = items[-cap:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([list(t) for t in items], ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 본문 → 텍스트 / 요약 / 필터 / 포맷
# --------------------------------------------------------------------------- #
def body_text_from_html(html: Optional[str], limit: int = 6000) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n", strip=True)[:limit]


# 프롬프트 본문은 repo 루트 prompts/notify_*.txt 에 산다 (generate/prompts.py 가 로드/치환).
SUMMARY_SYSTEM = load_prompt("notify_summary.system")
FILTER_SYSTEM = load_prompt("notify_filter.system")


def summarize_post(client: GeminiClient, post: dict, *, slug: Optional[str] = None) -> str:
    title = (post.get("title") or "").strip()
    body = body_text_from_html(post.get("content_html"))
    if len(body) < 30:
        return body or title or "(내용 없음)"
    user_text = render_prompt("notify_summary.user", title=title, body=body)
    tr = current_trace()
    with tr.span("summarize_gemini",
                 attrs={"slug": slug, "post_id": str(post.get("post_id")),
                        "body_chars": len(body)}) as sp:
        try:
            resp = client.generate(system_instruction=SUMMARY_SYSTEM, user_text=user_text,
                                   temperature=0.3, json_mode=False,
                                   call_site="notify_summarize", slug=slug)
            sp.set_attr("model", getattr(resp, "model", None))
            s = resp.text.strip()
            return s or (body[:400] + ("…" if len(body) > 400 else ""))
        except LLMError as e:
            sp.set_attr("fallback", "body_excerpt")
            sp.set_attr("err_short", type(e).__name__)
            print(f"  [warn] Gemini 요약 실패({post.get('post_id')}), 본문 발췌로 폴백: {e}", file=sys.stderr)
            return body[:400] + ("…" if len(body) > 400 else "")


def filter_pass(client: GeminiClient, filter_prompt: str, post: dict, summary: str,
                *, slug: Optional[str] = None) -> bool:
    title = (post.get("title") or "").strip()
    cat = post.get("category") or ""
    user_text = render_prompt("notify_filter.user", filter_prompt=filter_prompt,
                              title=title, category=cat, summary=summary)
    tr = current_trace()
    with tr.span("filter_gemini",
                 attrs={"slug": slug, "post_id": str(post.get("post_id"))}) as sp:
        try:
            resp = client.generate(system_instruction=FILTER_SYSTEM, user_text=user_text,
                                   temperature=0.0, json_mode=True,
                                   call_site="notify_filter", slug=slug)
            sp.set_attr("model", getattr(resp, "model", None))
            res = parse_json(resp.text)
            passed = bool(res.get("include", True)) if isinstance(res, dict) else True
            sp.set_attr("passed", passed)
            return passed
        except (LLMError, Exception) as e:  # noqa: BLE001
            sp.set_attr("err_short", type(e).__name__)
            sp.set_attr("fallback", "pass_through")
            print(f"  [warn] 필터 판단 실패({post.get('post_id')}) → 통과시킴: {e}", file=sys.stderr)
            return True  # fail-open


def format_message(post: dict, summary: str) -> str:
    title = (post.get("title") or "(제목 없음)").strip()
    url = post.get("url") or ""
    date_short = (post.get("published_at") or "")[:10]
    cat = post.get("category")
    head = f"📢 [{cat}] **{title}**" if cat else f"📢 **{title}**"
    lines = [head]
    if date_short:
        lines.append(f"📅 {date_short}")
    if url:
        lines.append(f"🔗 <{url}>")
    if summary:
        lines.append(f"📝 {summary}")
    return "\n".join(lines)


def digest_chunks(rows: list, *, max_len: int = 1850) -> list[str]:
    """pending 행들(slug,post_id,title,url,published_at,summary) → 다이제스트 메시지(들)."""
    header = f"🗞️ **새 글 다이제스트** ({len(rows)}건)"
    blocks: list[str] = []
    for r in rows:
        t = (r["title"] or "(제목 없음)").strip()
        d = (r["published_at"] or "")[:10]
        u = r["url"] or ""
        s = (r["summary"] or "").strip()
        b = f"• **{t}**" + (f"  ({d})" if d else "") + (f"\n  <{u}>" if u else "") + (f"\n  {s}" if s else "")
        blocks.append(b)
    chunks: list[str] = []
    cur = header
    for b in blocks:
        if len(cur) + 2 + len(b) > max_len:
            chunks.append(cur)
            cur = b
        else:
            cur = cur + "\n\n" + b
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------- #
# 다이제스트 flush — 레거시(HH:MM) 경로용 잔재.
#
# 현 deployment: 모든 구독 schedule='realtime' → 신규 글은 collected 처리 단계에서 이미 발송됨 →
# pending 테이블엔 채워질 일이 없음. 이 함수는 옛 HH:MM 모드 시절의 pending 잔재가 DB 에 남았을
# 때 그것을 비우는 안전망 역할만 함. sub.schedule='realtime' 인 행은 `_hhmm_to_minutes` 가 None
# 반환 → `_immediate_` 묶음 → cap 없이 즉시 발송. HH:MM 행이 들어오면 그 시각 도래 후 비움
# (digest_sent cap 으로 일 1회 제한).
# --------------------------------------------------------------------------- #
def _hhmm_to_minutes(sch: str) -> Optional[int]:
    try:
        h, m = sch.split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (ValueError, IndexError):
        pass
    return None


def flush_digests(conn, tok: Optional[str], *, dry_run: bool,
                  only_target_kind: Optional[str] = None,
                  only_target_id: Optional[str] = None) -> int:
    now_kst = datetime.now(KST)
    cur_minutes = now_kst.hour * 60 + now_kst.minute
    kst_date = now_kst.strftime("%Y-%m-%d")
    sent = 0
    for target_id in db.pending_target_ids(conn):
        if only_target_id and target_id != only_target_id:
            continue
        rows = db.pending_for_target(conn, target_id)
        # target_id 의 schedule 별로 묶음. 한 사용자가 한 사이트당 한 구독이지만 여러 사이트(slug)별 schedule 가
        # 같다고 가정할 수 없음 — 그러나 (user, slug) 구독은 schedule 하나뿐이고, 같은 target_id 면 사용자도 같음.
        # 그래서 (target_id, schedule) 쌍별로 cap 추적.
        by_schedule: dict[str, list] = {}
        target_kind = "dm"
        for r in rows:
            sub = conn.execute(
                "SELECT schedule, target_kind FROM subscriptions WHERE slug=? AND target_id=? LIMIT 1",
                (r["slug"], target_id),
            ).fetchone()
            if sub is None:  # 구독 사라짐 → orphan 정리
                conn.execute("DELETE FROM pending WHERE id=?", (r["id"],))
                conn.commit()
                continue
            target_kind = sub["target_kind"]
            sch = sub["schedule"] or ""
            mins = _hhmm_to_minutes(sch)
            if mins is None:
                # 잘못된 schedule (옛 'realtime' 또는 형식 오류) → 즉시 비움 묶음에 넣음
                by_schedule.setdefault("_immediate_", []).append(r)
                continue
            if mins > cur_minutes:
                continue  # 아직 시각 도래 안 함 — 다음 timer 슬랏에서 재시도
            by_schedule.setdefault(sch, []).append(r)

        for sch, due in by_schedule.items():
            if sch != "_immediate_" and db.digest_was_sent(conn, target_id, sch, kst_date):
                continue  # 이미 오늘 그 schedule 로 다이제스트 보냄 — 그 후 들어온 pending 은 내일 발송
            chunks = digest_chunks(due)
            if dry_run or not tok:
                for ch in chunks:
                    print(f"\n--- [DIGEST → {target_kind}:{target_id} sched={sch}] ---\n{ch}\n")
                if not tok and not dry_run:
                    print(f"  [warn] BOT_TOKEN 없음 — 다이제스트 발송 불가 (pending 유지): target={target_id}", file=sys.stderr)
                continue
            ok = True
            for ch in chunks:
                try:
                    deliver(tok, target_kind=target_kind, target_id=target_id, content=ch)
                    time.sleep(0.5)
                except CannotDeliver as e:
                    print(f"  [warn] 다이제스트 발송 불가(target={target_id}): {e} → 다음에 재시도", file=sys.stderr)
                    ok = False
                    break
                except DiscordRestError as e:
                    print(f"  [warn] 다이제스트 발송 실패(target={target_id}): {e} → 다음에 재시도", file=sys.stderr)
                    ok = False
                    break
            if ok:
                db.mark_drained(conn, target_id, due)
                if sch != "_immediate_":
                    db.mark_digest_sent(conn, target_id, sch, kst_date)
                sent += len(due)
                print(f"  🗞️ 다이제스트 발송: target={target_id} sched={sch}  {len(due)}건")
    return sent


# --------------------------------------------------------------------------- #
# heartbeat — "새 공지 없음" 알림 (notify_empty=1 인 realtime 구독)
# --------------------------------------------------------------------------- #
def send_heartbeats(conn, tok: Optional[str], collected_dir: Optional[Path],
                    delivered_pairs: set[tuple[str, str]], *, dry_run: bool,
                    only_target_kind: Optional[str] = None,
                    only_target_id: Optional[str] = None) -> int:
    """이번 폴링에서 그 slug 로 새로 알릴 글이 없었으면 notify_empty 구독에게 '새 공지 없음' 한 줄.

    delivered_pairs = 이번 run 에 realtime 발송이 일어난 (slug, target_id) 집합.
    poll_result.json(=poll.py 가 collected_dir 에 쓴 것) 의 status=='ok' 인 slug 만 대상 — 깨졌으면 '없음'이라 안 함.
    """
    if not collected_dir:
        return 0
    pr_path = collected_dir / "poll_result.json"
    if not pr_path.exists():
        return 0
    try:
        pr = json.loads(pr_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] poll_result.json 읽기 실패: {e}", file=sys.stderr)
        return 0
    by_slug = {s["slug"]: s for s in pr.get("sites", []) if isinstance(s, dict) and s.get("slug")}
    when = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    sent = 0
    for r in db.realtime_notify_empty_subs(conn):
        if only_target_id and (r["target_id"] != only_target_id
                               or (only_target_kind and r["target_kind"] != only_target_kind)):
            continue
        slug = r["slug"]
        site = by_slug.get(slug)
        if not site or site.get("status") != "ok":
            continue  # 폴링 안 됐거나 깨짐 — '없음'이라고 말하면 오해를 줌
        if (slug, r["target_id"]) in delivered_pairs:
            continue  # 이번에 새 글을 이미 보냈음
        content = f"🔇 `{slug}` — 새 공지 없음 (확인: {when} KST)"
        if dry_run or not tok:
            print(f"\n--- [HEARTBEAT → {r['target_kind']}:{r['target_id']}] ---\n{content}\n")
            if not tok and not dry_run:
                print(f"  [warn] BOT_TOKEN 없음 — heartbeat 발송 불가: {slug}", file=sys.stderr)
            continue
        try:
            deliver(tok, target_kind=r["target_kind"], target_id=r["target_id"], content=content)
            sent += 1
            print(f"  🔇 heartbeat: {r['target_kind']}:{r['target_id']}  {slug}")
            time.sleep(0.5)
        except (CannotDeliver, DiscordRestError) as e:
            print(f"  [warn] heartbeat 발송 실패({slug} → {r['target_id']}): {e}", file=sys.stderr)
    return sent


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="collected 새 글 → 요약/필터 → Discord(구독 또는 webhook) 발송 + 다이제스트 flush")
    p.add_argument("--collected-dir", help="처리할 collected 디렉터리 (기본: 가장 최근)")
    p.add_argument("--targets", default=str(DEFAULT_TARGETS), help="(webhook fallback) slug→webhook URL JSON")
    p.add_argument("--delivered", default=str(DEFAULT_DELIVERED), help="(webhook fallback) 보낸 글 기록 JSON")
    p.add_argument("--model", help="Gemini 모델 (기본 GEMINI_MODEL env 또는 gemini-2.5-flash)")
    p.add_argument("--max-notify", type=int, default=12, help="한 slug 당 한 번에 처리할 최대 글 수 (초과분은 스킵)")
    p.add_argument("--no-digest", action="store_true", help="다이제스트 flush 생략")
    p.add_argument("--no-collected", action="store_true",
                   help="collected 새 글 처리 생략 — pending 에서 다이제스트 flush 만. notice-notify.timer 가 켜서 호출.")
    p.add_argument("--heartbeat", action="store_true",
                   help="notify_empty=1 인 realtime 구독에 새 글 없으면 '새 공지 없음' 발송 (poll_and_notify 가 폴링 직후 켬)")
    p.add_argument("--dry-run", action="store_true", help="발송/DB 변경 없이 메시지만 출력")
    # --only-target-* : dashboard /users 의 replay (M2/M3) 가 켬. 한 (target_kind, target_id) 외엔 구독 루프에서 skip.
    # 둘 다 지정해야 활성(편의상 한쪽만 들어오면 효과 없음). digest flush·heartbeat 도 같은 필터 적용.
    p.add_argument("--only-target-kind", choices=("dm", "channel"),
                   help="이 target_kind 의 구독자에게만 발송 (replay 디버그). --only-target-id 와 함께 사용.")
    p.add_argument("--only-target-id",
                   help="이 target_id 의 구독자에게만 발송 (replay 디버그). --only-target-kind 와 함께 사용.")
    args = p.parse_args(argv)

    if args.no_collected:
        collected = None
        new_posts = {}
    else:
        collected = Path(args.collected_dir) if args.collected_dir else latest_collected_dir()
        new_posts = load_new_posts(collected)
    conn = db.connect()
    tok = bot_token() or None
    dry_run = args.dry_run

    targets = load_targets(Path(args.targets))
    delivered_path = Path(args.delivered)
    delivered_file = load_delivered(delivered_path)

    print(f"[notify] dir={collected.name if collected else '-'}  new_slugs={list(new_posts)}  "
          f"sub_slugs={db.all_slugs(conn)}  webhook_slugs={list(targets)}  token={'yes' if tok else 'no'}  dry_run={dry_run}")

    # CLI `--model` 은 process-wide override — routing.json 무시하고 모든 call_site 에 적용.
    if args.model:
        set_process_override(f"gemini:{args.model}")

    realtime_sent = 0
    digest_sent = 0
    hb_sent = 0
    realtime_delivered: set[tuple[str, str]] = set()  # 이번 run 에 realtime 발송을 시도한 (slug, target_id) — 성공/실패 무관(새 글이 있었다는 뜻)
    # 새 글 0건 + digest/heartbeat 도 비활성이면 'idle' run — 빈 trace 가 /timings 를 도배하지 않게
    # kind 분리. dashboard 가 기본 hide.
    idle = not new_posts and (args.no_collected or args.no_digest) and not args.heartbeat
    trace_kind = "notify_idle" if idle else "notify"
    trace_attrs = {
        "n_slugs": len(new_posts), "no_digest": bool(args.no_digest),
        "no_collected": bool(args.no_collected), "heartbeat": bool(args.heartbeat),
        "dry_run": bool(dry_run),
        "only_target_kind": args.only_target_kind or "",
        "only_target_id": args.only_target_id or "",
    }
    trace_cm = start_trace(trace_kind, attrs=trace_attrs)
    trace_cm.__enter__()  # try 밖에서 — __enter__ 실패 시 __exit__ 호출 안 함.
    try:
        for slug, posts in new_posts.items():
            subs = db.subscriptions_for_slug(conn, slug)
            # --only-target-* (M2/M3 replay) 활성이면 그 (kind,id) 외 구독자 skip.
            # 둘 다 지정해야 활성 — 한쪽만 들어오면 효과 없음.
            if args.only_target_kind and args.only_target_id:
                subs = [r for r in subs
                        if r["target_kind"] == args.only_target_kind
                        and r["target_id"] == args.only_target_id]
            webhook = targets.get(slug)
            # only-target replay 중엔 webhook fallback 도 건너뜀 — replay 는 SQLite 구독자만 대상.
            if args.only_target_kind and args.only_target_id:
                webhook = None
            if not subs and not webhook:
                continue
            # 한 번에 너무 많으면 앞쪽(최신) max_notify 개만; 나머지는 처리됨 처리
            skipped: list[dict] = []
            if len(posts) > args.max_notify:
                skipped = posts[args.max_notify:]
                posts = posts[: args.max_notify]
            for op in skipped:
                opid = str(op.get("post_id"))
                delivered_file.add((slug, opid))
                if not dry_run:
                    for r in subs:
                        db.mark_delivered(conn, slug, opid, r["target_id"])
            print(f"  [{slug}] 처리 {len(posts)}건{f' (+{len(skipped)} 스킵)' if skipped else ''}  "
                  f"subs={len(subs)}{' +webhook' if webhook else ''}")

            for post in posts:
                pid = str(post.get("post_id"))
                summary: Optional[str] = None

                # --- webhook fallback (이 slug 에 SQLite 구독이 없을 때만) ---
                if webhook and not subs:
                    if (slug, pid) not in delivered_file:
                        if summary is None:
                            summary = summarize_post(client_for("notify_summarize"), post, slug=slug)
                        content = format_message(post, summary)
                        if dry_run:
                            print(f"\n--- [webhook {slug}] {pid} ---\n{content}\n")
                            delivered_file.add((slug, pid))
                        else:
                            try:
                                post_webhook(webhook, content)
                                delivered_file.add((slug, pid))
                                print(f"    ✅ webhook {pid}  {(post.get('title') or '')[:50]}")
                                time.sleep(1.0)
                            except Exception as e:  # noqa: BLE001
                                print(f"    ✗ webhook {pid} 실패: {e}", file=sys.stderr)

                # --- SQLite 구독자들 ---
                for r in subs:
                    target_id = r["target_id"]
                    target_kind = r["target_kind"]
                    if db.was_delivered(conn, slug, pid, target_id):
                        continue
                    fp = r["filter_prompt"]
                    if fp:
                        if summary is None:
                            summary = summarize_post(client_for("notify_summarize"), post, slug=slug)
                        if not filter_pass(client_for("notify_filter"), fp, post, summary, slug=slug):
                            continue
                    if summary is None:
                        summary = summarize_post(client_for("notify_summarize"), post, slug=slug)
                    content = format_message(post, summary)
                    if dry_run:
                        print(f"\n--- [{target_kind}:{target_id} {slug}] {pid} ---\n{content}\n")
                        realtime_delivered.add((slug, target_id))
                        continue
                    if not tok:
                        print(f"    ✗ {pid}: BOT_TOKEN 없음 — 발송 불가", file=sys.stderr)
                        continue
                    realtime_delivered.add((slug, target_id))  # 새 글이 있었음 → heartbeat('새 공지 없음') 안 보냄 (발송 성공/실패 무관)
                    with current_trace().span("discord_deliver",
                                              attrs={"slug": slug, "post_id": pid,
                                                     "target_kind": target_kind,
                                                     "target_id": target_id}) as dsp:
                        try:
                            deliver(tok, target_kind=target_kind, target_id=target_id, content=content)
                            db.mark_delivered(conn, slug, pid, target_id)
                            realtime_sent += 1
                            dsp.set_attr("ok", True)
                            print(f"    ✅ {target_kind}:{target_id} {pid}  {(post.get('title') or '')[:40]}")
                            time.sleep(0.6)
                        except CannotDeliver as e:
                            dsp.set_attr("ok", False)
                            dsp.set_attr("err_short", "CannotDeliver")
                            print(f"    ✗ {pid} {target_kind}:{target_id} 발송 불가: {e}", file=sys.stderr)
                        except DiscordRestError as e:
                            dsp.set_attr("ok", False)
                            dsp.set_attr("err_short", "DiscordRestError")
                            print(f"    ✗ {pid} {target_kind}:{target_id} 발송 실패: {e}", file=sys.stderr)
        # collected 처리 끝 — 마킹 (이후 notify-timer 호출에서 같은 dir 재처리 안 함; 새 글 0건이어도 마킹해야
        # heartbeat/Gemini 가 다음 timer 슬랏마다 같은 dir 로 반복 안 됨).
        if collected and not dry_run:
            try:
                (collected / ".notified").touch()
            except OSError as e:  # noqa: BLE001
                print(f"  [warn] .notified 마커 생성 실패({collected}): {e}", file=sys.stderr)
        # --- 다이제스트 flush --- (digest_sent/hb_sent 는 try 밖에서 0 초기화됨)
        if not args.no_digest:
            digest_sent = flush_digests(conn, tok, dry_run=dry_run,
                                        only_target_kind=args.only_target_kind,
                                        only_target_id=args.only_target_id)
        # --- heartbeat ('새 공지 없음') ---
        if args.heartbeat:
            hb_sent = send_heartbeats(conn, tok, collected, realtime_delivered, dry_run=dry_run,
                                      only_target_kind=args.only_target_kind,
                                      only_target_id=args.only_target_id)
    finally:
        save_delivered(delivered_path, delivered_file)
        conn.close()
        # 예외 정보 보존 — exc_info 가 (None,None,None) 이면 정상 종료.
        try:
            trace_cm.__exit__(*sys.exc_info())
        except Exception:  # noqa: BLE001
            pass
    print(f"[notify] 완료 — realtime {realtime_sent}건"
          + (f", digest {digest_sent}건" if not args.no_digest else "")
          + (f", heartbeat {hb_sent}건" if args.heartbeat else "")
          + f" (dry_run={dry_run})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
