"""Scoped announce 발송 — dashboard `/users` 페이지의 announce 액션이 켠다.

`/admin announce` (bot/admin.py) 가 broadcast 인 반면 이건 recipient 골라서 발송.
BOT_TOKEN REST 직접 사용 — 게이트웨이 봇 프로세스 안 떠 있어도 동작 (notify.py 와 동일 패턴).

입력:
    - `--stdin` : stdin 으로 JSON 페이로드 한 줄 (또는 multi-line) 읽기
    - `--base64 <str>` : base64 인코딩 JSON 페이로드 디코드 (SSH command line 안전 전송용)

페이로드 schema (JSON):
    {
        "title":    "...",
        "message":  "...",
        "sent_by":  "dashboard:<owner_label>",
        "recipients": [["dm","<user_id>"], ["channel","<channel_id>"], ...]
    }

동작:
    1. announce_prefs.opted_out=1 인 recipient 자동 제외 (카운트만 보고).
    2. announcements 테이블에 row 1개 INSERT (recipient_targets = 원본 JSON 보존).
    3. recipients 순회 — DM 은 open_dm_channel + post_message, channel 은 post_message 직접.
    4. 성공/실패 카운트 집계 → announcements UPDATE.
    5. stdout 에 한 줄 요약 + JSON summary (dashboard 가 파싱).

종료 코드:
    0 = 모든 시도 성공 또는 사용자가 보낸 게 0건
    1 = 일부/전부 발송 실패 (요약은 stdout 으로)
    2 = 페이로드 파싱/검증 실패
    3 = BOT_TOKEN 미설정 (발송 불가)
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import db  # noqa: E402
from bot.config import bot_token  # noqa: E402
from bot.discord_rest import (  # noqa: E402
    CannotDeliver, DiscordRestError, open_dm_channel, post_message,
)


_TITLE_MAX = 200
_MSG_MAX = 1900
_SENT_BY_MAX = 100
_RECIPIENTS_MAX = 2000  # 안전상 상한 — DM 폭주 가드
_ID_RE = __import__("re").compile(r"^[0-9]{1,32}$")


def _err(msg: str, code: int = 2) -> int:
    sys.stderr.write(f"[announce] {msg}\n")
    return code


def _load_payload(args) -> dict[str, Any] | None:
    raw: str
    if args.base64:
        try:
            raw = base64.b64decode(args.base64, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as e:
            _err(f"--base64 디코드 실패: {e}")
            return None
    elif args.stdin:
        raw = sys.stdin.read()
    else:
        _err("--stdin 또는 --base64 중 하나 필요")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _err(f"JSON 파싱 실패: {e}")
        return None
    if not isinstance(data, dict):
        _err("페이로드가 JSON object 아님")
        return None
    return data


def _validate(p: dict[str, Any]) -> str | None:
    """OK 면 None, 에러면 메시지."""
    title = p.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > _TITLE_MAX:
        return f"title 누락 또는 길이 위반 (1~{_TITLE_MAX}자)"
    msg = p.get("message")
    if not isinstance(msg, str) or not msg.strip() or len(msg) > _MSG_MAX:
        return f"message 누락 또는 길이 위반 (1~{_MSG_MAX}자)"
    sent_by = p.get("sent_by")
    if not isinstance(sent_by, str) or not sent_by.strip() or len(sent_by) > _SENT_BY_MAX:
        return f"sent_by 누락 또는 길이 위반 (1~{_SENT_BY_MAX}자)"
    rcs = p.get("recipients")
    if not isinstance(rcs, list) or not rcs:
        return "recipients 누락 또는 빈 리스트"
    if len(rcs) > _RECIPIENTS_MAX:
        return f"recipients 너무 많음 (>{_RECIPIENTS_MAX})"
    for i, item in enumerate(rcs):
        if not (isinstance(item, list) and len(item) == 2):
            return f"recipients[{i}] 가 [kind, id] 형식 아님"
        kind, rid = item
        if kind not in ("dm", "channel"):
            return f"recipients[{i}].kind 무효: {kind!r}"
        if not isinstance(rid, str) or not _ID_RE.match(rid):
            return f"recipients[{i}].id 무효: {rid!r} (Discord ID 형식 아님)"
    return None


def _filter_optout(conn, recipients: list[list[str]]) -> tuple[list[tuple[str, str]], int]:
    """opt-out 제외. 반환 = (살아남은 [(kind,id),...], 제외된 카운트)."""
    out: list[tuple[str, str]] = []
    skipped = 0
    seen: set[tuple[str, str]] = set()  # dedupe — 같은 (kind,id) 중복 입력 한 번만
    for kind, rid in recipients:
        key = (kind, rid)
        if key in seen:
            continue
        seen.add(key)
        if db.get_announce_optout(conn, kind, rid):
            skipped += 1
            continue
        out.append(key)
    return out, skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="dashboard /users — scoped announce 발송")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--stdin", action="store_true", help="stdin 에서 JSON 페이로드 읽기")
    src.add_argument("--base64", help="base64-인코딩된 JSON 페이로드 (SSH 안전 전송용)")
    p.add_argument("--dry-run", action="store_true", help="실제 발송 없이 검증만")
    args = p.parse_args(argv)

    payload = _load_payload(args)
    if payload is None:
        return 2
    err = _validate(payload)
    if err:
        return _err(err, code=2)

    title = payload["title"].strip()
    message = payload["message"].strip()
    sent_by = payload["sent_by"].strip()
    recipients: list[list[str]] = payload["recipients"]

    conn = db.connect()
    try:
        live, optout_skipped = _filter_optout(conn, recipients)
        n_dm = sum(1 for k, _ in live if k == "dm")
        n_ch = sum(1 for k, _ in live if k == "channel")
        print(f"[announce] recipients in={len(recipients)}  live={len(live)} "
              f"(DM {n_dm} · channel {n_ch})  optout_skipped={optout_skipped}  dry_run={args.dry_run}")

        if args.dry_run:
            return 0

        tok = bot_token()
        if not tok:
            return _err("BOT_TOKEN 미설정 — 발송 불가", code=3)

        # audit row — recipient_targets 는 *opt-out 제외 후* live set 만 보존
        recipient_json = json.dumps(live, ensure_ascii=False)
        ann_id = db.add_announcement(
            conn, title=title, message=message, sent_by=sent_by,
            recipient_targets=recipient_json,
        )
        # Discord 의 message 본문 형식: 봇 announce 는 embed 였으나 여기선 plain text 로 통일.
        # title + message 합쳐 발송 — embed 권한이 채널마다 다를 수 있어 단순화.
        body = f"📢 **{title}**\n{message}"

        dm_sent = dm_failed = ch_sent = ch_failed = 0
        for kind, rid in live:
            try:
                if kind == "dm":
                    cid = open_dm_channel(tok, rid)
                    post_message(tok, cid, body)
                    dm_sent += 1
                else:  # channel
                    post_message(tok, rid, body)
                    ch_sent += 1
                time.sleep(0.6)
            except CannotDeliver as e:
                if kind == "dm":
                    dm_failed += 1
                else:
                    ch_failed += 1
                sys.stderr.write(f"[announce] cannot-deliver {kind}:{rid}: {e}\n")
            except DiscordRestError as e:
                if kind == "dm":
                    dm_failed += 1
                else:
                    ch_failed += 1
                sys.stderr.write(f"[announce] error {kind}:{rid}: {e}\n")

        db.update_announcement_counts(
            conn, ann_id, dm_sent=dm_sent, dm_failed=dm_failed,
            channel_sent=ch_sent, channel_failed=ch_failed,
        )

        summary = {
            "ok": (dm_failed == 0 and ch_failed == 0),
            "announcement_id": ann_id,
            "dm_sent": dm_sent, "dm_failed": dm_failed,
            "channel_sent": ch_sent, "channel_failed": ch_failed,
            "optout_skipped": optout_skipped,
        }
        print(f"[announce] done: {json.dumps(summary, ensure_ascii=False)}")
        return 0 if summary["ok"] else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
