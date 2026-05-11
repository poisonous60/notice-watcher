"""폴링으로 모인 새 글(output/collected/<ts>/<slug>.new.json) → Gemini 요약 → 필터 → Discord 발송.

발송 경로 (slug 별로):
  1. SQLite 구독(bot/db.py: subscriptions) 이 있으면 → 봇 토큰으로 REST 직접(DM/채널).
       구독별 filter_prompt(자연어) → Gemini {include,reason} 로 골라냄(없으면 전부 통과).
       구독별 schedule: 'realtime' → 지금 발송 / 'HH:MM' → pending 큐에 쌓아뒀다가 그 시각(KST) 폴링 때 다이제스트로.
  2. (Phase 1 / 봇 없는 경우) output/notify_targets.json = {"<slug>":"<webhook>"} 또는 NOTIFY_TARGETS_JSON 이 있으면 → webhook 발송 (해당 slug 에 SQLite 구독이 없을 때만; delivered.json 으로 중복 방지).

중복 방지: SQLite deliveries(slug,post_id,target_id) / webhook 은 delivered.json.
봇 프로세스(bot/main.py)가 떠 있을 필요 없음 — 여기서 토큰으로 REST 직접 친다.

사용:
    python scripts/notify.py                 # 최신 collected 처리 + 다이제스트 시각 도래분 발송
    python scripts/notify.py --dry-run       # 발송/DB 변경 없이 메시지만 출력
    python scripts/notify.py --collected-dir output/collected/20260511_210242
    python scripts/notify.py --no-digest     # 다이제스트 flush 생략 (이번 collected 분만)
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

from generate import GeminiClient, GeminiError  # noqa: E402
from bot import db  # noqa: E402
from bot.config import bot_token  # noqa: E402
from bot.discord_rest import deliver, post_webhook, CannotDeliver, DiscordRestError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLLECTED_DIR = ROOT / "output" / "collected"
DEFAULT_TARGETS = ROOT / "output" / "notify_targets.json"
DEFAULT_DELIVERED = ROOT / "output" / "delivered.json"
DELIVERED_CAP = 5000
KST = timezone(timedelta(hours=9))


# --------------------------------------------------------------------------- #
# collected 디렉터리 / 새 글
# --------------------------------------------------------------------------- #
def latest_collected_dir() -> Optional[Path]:
    if not COLLECTED_DIR.exists():
        return None
    dirs = sorted(d for d in COLLECTED_DIR.iterdir() if d.is_dir())
    for d in reversed(dirs):
        if any(d.glob("*.new.json")):
            return d
    return dirs[-1] if dirs else None


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
    if len(items) > DELIVERED_CAP:
        items = items[-DELIVERED_CAP:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([list(t) for t in items], ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 본문 → 텍스트 / 요약 / 필터 / 포맷
# --------------------------------------------------------------------------- #
def body_text_from_html(html: Optional[str], limit: int = 6000) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text("\n", strip=True)[:limit]


SUMMARY_SYSTEM = (
    "너는 게시판 글 요약기다. 주어진 글의 제목과 본문을 한국어로 3~4줄 이내로 요약한다.\n"
    "핵심 정보(일정/기간/대상/조건/제출방법/주요 변경점) 위주로. 인사말·사이트 안내·서식은 무시.\n"
    "마크다운·머리글머리표 없이 평문 문장으로만. 본문이 거의 없으면 제목을 한 줄로 풀어 쓴다."
)
FILTER_SYSTEM = (
    "너는 알림 필터다. 사용자가 준 '받고 싶은 글의 조건'과 게시판 글 정보를 보고,\n"
    "이 글을 사용자에게 알릴지 판단한다. 출력은 JSON 하나만: {\"include\": true|false, \"reason\": \"한 줄 이유\"}.\n"
    "조건에 명백히 해당하면 include=true, 명백히 아니면 false. 애매하면 include=true(놓치는 것보다 낫다)."
)


def summarize_post(client: GeminiClient, post: dict) -> str:
    title = (post.get("title") or "").strip()
    body = body_text_from_html(post.get("content_html"))
    if len(body) < 30:
        return body or title or "(내용 없음)"
    user_text = f"제목: {title}\n\n--- 본문 ---\n{body}\n--- 끝 ---"
    try:
        s = client.generate_text(system_instruction=SUMMARY_SYSTEM, user_text=user_text,
                                 temperature=0.3, json_mode=False).strip()
        return s or (body[:400] + ("…" if len(body) > 400 else ""))
    except GeminiError as e:
        print(f"  [warn] Gemini 요약 실패({post.get('post_id')}), 본문 발췌로 폴백: {e}", file=sys.stderr)
        return body[:400] + ("…" if len(body) > 400 else "")


def filter_pass(client: GeminiClient, filter_prompt: str, post: dict, summary: str) -> bool:
    title = (post.get("title") or "").strip()
    cat = post.get("category") or ""
    user_text = (f"[받고 싶은 글의 조건]\n{filter_prompt}\n\n"
                 f"[글]\n제목: {title}\n분류: {cat}\n요약: {summary}")
    try:
        res = client.generate_json(system_instruction=FILTER_SYSTEM, user_text=user_text, temperature=0.0)
        return bool(res.get("include", True)) if isinstance(res, dict) else True
    except (GeminiError, Exception) as e:  # noqa: BLE001
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
# 다이제스트 flush (지금 KST 시(時) 가 도래한 것들)
# --------------------------------------------------------------------------- #
def flush_digests(conn, tok: Optional[str], *, dry_run: bool) -> int:
    cur_hour = datetime.now(KST).hour
    sent = 0
    for target_id in db.pending_target_ids(conn):
        rows = db.pending_for_target(conn, target_id)
        due: list = []
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
            sch = sub["schedule"] or "realtime"
            if sch == "realtime":
                due.append(r)  # 비정상이지만(원래 pending 안 들어옴) 들어왔으면 지금 보냄
                continue
            try:
                if int(sch.split(":")[0]) == cur_hour:
                    due.append(r)
            except (ValueError, IndexError):
                conn.execute("DELETE FROM pending WHERE id=?", (r["id"],))
                conn.commit()
        if not due:
            continue
        chunks = digest_chunks(due)
        if dry_run or not tok:
            for ch in chunks:
                print(f"\n--- [DIGEST → {target_kind}:{target_id}] ---\n{ch}\n")
            if not tok and not dry_run:
                print(f"  [warn] BOT_TOKEN 없음 — 다이제스트 발송 불가 (pending 유지): target={target_id}", file=sys.stderr)
            continue  # dry-run/토큰없음: pending 그대로 둠
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
            sent += len(due)
            print(f"  🗞️ 다이제스트 발송: target={target_id}  {len(due)}건")
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
    p.add_argument("--dry-run", action="store_true", help="발송/DB 변경 없이 메시지만 출력")
    args = p.parse_args(argv)

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

    _client: list[Optional[GeminiClient]] = [None]

    def gem() -> GeminiClient:
        if _client[0] is None:
            _client[0] = GeminiClient(model=args.model)
        return _client[0]

    realtime_sent = 0
    try:
        for slug, posts in new_posts.items():
            subs = db.subscriptions_for_slug(conn, slug)
            webhook = targets.get(slug)
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
                            summary = summarize_post(gem(), post)
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
                            summary = summarize_post(gem(), post)
                        if not filter_pass(gem(), fp, post, summary):
                            continue
                    if summary is None:
                        summary = summarize_post(gem(), post)
                    content = format_message(post, summary)
                    sched = r["schedule"] or "realtime"
                    if sched == "realtime":
                        if dry_run:
                            print(f"\n--- [{target_kind}:{target_id} {slug}] {pid} ---\n{content}\n")
                            continue
                        if not tok:
                            print(f"    ✗ {pid}: BOT_TOKEN 없음 — 발송 불가", file=sys.stderr)
                            continue
                        try:
                            deliver(tok, target_kind=target_kind, target_id=target_id, content=content)
                            db.mark_delivered(conn, slug, pid, target_id)
                            realtime_sent += 1
                            print(f"    ✅ {target_kind}:{target_id} {pid}  {(post.get('title') or '')[:40]}")
                            time.sleep(0.6)
                        except CannotDeliver as e:
                            print(f"    ✗ {pid} {target_kind}:{target_id} 발송 불가: {e}", file=sys.stderr)
                        except DiscordRestError as e:
                            print(f"    ✗ {pid} {target_kind}:{target_id} 발송 실패: {e}", file=sys.stderr)
                    else:  # 'HH:MM' — 다이제스트 큐
                        if dry_run:
                            print(f"  (digest queue) {target_kind}:{target_id}  {slug}/{pid}  sched={sched}")
                        else:
                            db.add_pending(conn, slug=slug, post_id=pid, target_id=target_id,
                                           summary=summary, title=post.get("title"),
                                           url=post.get("url"), published_at=post.get("published_at"))
        # --- 다이제스트 flush ---
        digest_sent = 0
        if not args.no_digest:
            digest_sent = flush_digests(conn, tok, dry_run=dry_run)
    finally:
        save_delivered(delivered_path, delivered_file)
        conn.close()
    print(f"[notify] 완료 — realtime {realtime_sent}건"
          + (f", digest {digest_sent}건" if not args.no_digest else "")
          + f" (dry_run={dry_run})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
