"""Discord 봇 — 게시판 등록(/watch) · 목록(/list) · 설정(/setting) · 신고(/report). 상태는 owner 전용 `/admin status`.

- 게이트웨이 연결(아웃바운드만 — 포트포워딩 불필요). 슬래시 명령 *수신* 용.
- `/watch`(처음 보는 사이트) 는 jobs 큐에 enqueue 만 함. 실제 register.py 실행은
  bot/worker.py 의 단일 백그라운드 task 가 FIFO 로 처리(chromium_lock 안). 처리 끝나면 사용자가
  본 채널 메시지를 worker 가 직접 edit(interaction token 만료와 무관). 폴링의 re-probe 도 같은 큐.
- 구독 정보(필터·스케줄·발송대상)는 SQLite(output/bot.sqlite3, bot/db.py)에만 — configs/·poll_state/ 엔 안 씀.
- 실제 알림 발송은 polling 쪽(scripts/notify.py)이 봇 토큰으로 REST 직접 — 이 봇 프로세스가 떠 있을 필요 없음.
- 미처리 예외는 로그 + OWNER_USER_ID 에게 DM(쿨다운).

실행: python -m bot.main      (env: BOT_TOKEN 필수, OWNER_USER_ID/GUILD_ID 선택; .env 도 읽음)
"""
from __future__ import annotations

import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord  # noqa: E402
from discord import app_commands  # noqa: E402

from bot import admin as admin_mod, db, delivery_tick, inspector, site_ops, url_gate, worker  # noqa: E402
from bot.config import (  # noqa: E402
    admin_guild_id, bot_token, feedback_max_len, guild_id, owner_user_id, safe_browsing_api_key,
)
from bot.messages import render as msg  # noqa: E402
from bot.runtime_config import settings  # noqa: E402
from probe.paths import url_to_slug  # noqa: E402

STATE_DIR = site_ops.STATE_DIR

# N100 systemd user journal 가 안 잡히는 환경(persistent storage 비활성)을 위해 file 도 같이.
# output/ 은 git ignored — runtime log 자연 위치.
_LOG_FILE = ROOT / "output" / "bot.log"
_LOG_FILE.parent.mkdir(exist_ok=True)
_log_fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=_log_fmt, handlers=[
    RotatingFileHandler(_LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8"),
    logging.StreamHandler(),
])
log = logging.getLogger("bot")

# ADR 0006 — 발송 시각은 수신처별 설정(user_settings/channel_settings, 기본 08:30 KST).
# 폴링은 새 글을 posts 캐시에 모으고, 봇 내부 1분 tick(delivery_tick)이 사용자 발송 시각에
# scripts/deliver_due.py 로 요약·필터·발송. realtime 즉시 발송 폐지.

START_TS = time.time()
LAST_ERROR: dict = {"when": None, "text": None}
_OWNER_DM_COOLDOWN: dict[str, float] = {}

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_conn = db.connect()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# site_ops 의 헬퍼를 짧은 alias 로 — 기존 호출부 호환
_is_registered = site_ops.is_registered
_baseline_count = site_ops.baseline_count
_body_warning = site_ops.body_warning


# --------------------------------------------------------------------------- #
# URL 게이트 wrapper — 거부 시 OWNER DM 등 부수 처리
# --------------------------------------------------------------------------- #
def _check_rate_limit(user_id: Optional[str]) -> Optional[str]:
    """settings.rate_limit 따라 user_id 의 register 잡 빈도 검사. 한도 초과면 사용자에 보여줄 메시지, OK면 None.
    한도 값 <=0 이면 그 검사 끔."""
    if not user_id:
        return None
    rl = settings.rate_limit
    now = datetime.now(timezone.utc)
    if rl.per_user_per_hour > 0:
        cnt = db.count_user_register_jobs_since(
            _conn, user_id, (now - timedelta(hours=1)).isoformat())
        if cnt >= rl.per_user_per_hour:
            return msg("rate_limit_hourly", limit=rl.per_user_per_hour, cnt=cnt)
    if rl.per_user_per_day > 0:
        cnt = db.count_user_register_jobs_since(
            _conn, user_id, (now - timedelta(days=1)).isoformat())
        if cnt >= rl.per_user_per_day:
            return msg("rate_limit_daily", limit=rl.per_user_per_day, cnt=cnt)
    return None


def _check_queue_depth() -> Optional[str]:
    """전역 워커 큐 pending 상한 검사. settings.rate_limit.queue_depth_cap > 0 이고 그 이상이면 reject."""
    cap = settings.rate_limit.queue_depth_cap
    if cap <= 0:
        return None
    n = db.queue_pending_count(_conn)
    if n >= cap:
        return msg("queue_full", n=n, cap=cap)
    return None


async def _gate_check(url: str, *, article_url: Optional[str], via: str,
                       requested_by: Optional[dict]) -> Optional[str]:
    """URL 게이트 통과 시 None, 거부 시 사용자에게 보여줄 메시지(이미 OWNER DM 등 부수 처리 완료).
    url_gate.check → per-user rate-limit → 전역 큐 깊이 cap 순서."""
    try:
        await url_gate.check(url, article_url=article_url)
    except url_gate.UrlRejected as e:
        log.info("[url_gate] reject %s (article=%s): %s — %s", url, article_url, e.reason, e.msg)
        if e.reason == "malicious":
            await _dm_owner(msg("url_gate_malicious_owner_dm", url=url, msg=e.msg,
                                user_name=(requested_by or {}).get('name', '?'), via=via),
                            key="url_gate_malicious")
        elif e.reason == "gsb_error":
            await _dm_owner(msg("url_gate_gsb_error_owner_dm", msg=e.msg, url=url),
                            key="url_gate_gsb")
        return e.msg
    user_id = (requested_by or {}).get("id") if isinstance(requested_by, dict) else None
    err = _check_rate_limit(user_id) or _check_queue_depth()
    if err:
        log.info("[gate] enqueue throttled user=%s via=%s url=%s — %s", user_id, via, url, err)
    return err


# --------------------------------------------------------------------------- #
# OWNER DM (에러 알림)
# --------------------------------------------------------------------------- #
async def _dm_owner(text: str, *, key: str = "err") -> None:
    oid = owner_user_id()
    if not oid or not oid.isdigit():
        return
    now = time.time()
    if now - _OWNER_DM_COOLDOWN.get(key, 0) < 600:  # 같은 종류 10분 쿨다운
        return
    _OWNER_DM_COOLDOWN[key] = now
    try:
        user = await client.fetch_user(int(oid))
        await user.send(text[:1900])
    except Exception as e:  # noqa: BLE001
        log.warning("OWNER DM 실패: %r", e)


def _record_error(where: str, exc: BaseException) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    LAST_ERROR["when"] = _now_iso()
    LAST_ERROR["text"] = f"{where}: {type(exc).__name__}: {exc}"
    log.error("[%s] %s\n%s", where, exc, tb)
    return tb


# --------------------------------------------------------------------------- #
# 슬래시 명령
# --------------------------------------------------------------------------- #
@tree.command(name="watch", description="게시판 URL 을 등록해 새 글 알림을 받습니다.")
@app_commands.describe(
    url="공지/게시판 목록 페이지 URL",
    filter="(선택) 어떤 글만 받을지 자연어로. 예: '점검 공지는 빼고 신규 콘텐츠/이벤트만'. 비우면 새 글 전부.",
    here="(선택) 켜면 이 채널에 발송. 끄면(기본) 내 DM 으로.",
    notify_empty="(선택) 켜면 폴링했는데 새 글이 없을 때도 '새 공지 없음' 한 줄을 보냄. 끄면(기본) 새 글 있을 때만.",
    article_url="(선택) 처음 등록하는 사이트가 자동 분석에 실패할 때, 그 게시판의 실제 글 하나 URL 을 같이 주면 분석 성공률이 올라갑니다.",
)
async def watch(interaction: discord.Interaction, url: str, filter: Optional[str] = None,
                here: bool = False, notify_empty: bool = False,
                article_url: Optional[str] = None):
    await interaction.response.defer(thinking=True)
    url = url.strip()
    if not re.match(r"^https?://", url):
        await interaction.edit_original_response(content=msg("validation_url_required"))
        return
    art = (article_url or "").strip() or None
    if art and not re.match(r"^https?://", art):
        await interaction.edit_original_response(content=msg("validation_article_url_required"))
        return

    slug = url_to_slug(url)
    # 같은 board 가 다른 slug 로 이미 등록돼 있으면(recognizer 도입 등 slug 스키마 변화) 그 slug 로 흡수 —
    # 새 config 중복 등록·중복 폴링(새 글 2번 알림) 방지.
    if not _is_registered(slug):
        alias = site_ops.find_registered_alias(url, exclude_slug=slug)
        if alias:
            slug = alias
    if site_ops.is_blocked(slug):
        kind_m = site_ops.marker_kind(slug)
        if kind_m == "bug":
            await interaction.edit_original_response(content=msg("blocked_bug", slug=slug))
        else:
            info = site_ops.blocked_info(slug) or {}
            await interaction.edit_original_response(
                content=msg("rejected_site",
                            reason=site_ops.public_reason(info.get('reason')),
                            note=info.get('note') or '없음'))
        return
    user_id = str(interaction.user.id)
    target_kind = "channel" if here else "dm"
    target_id = str(interaction.channel_id) if here else user_id
    filter_prompt = (filter.strip() if filter and filter.strip() else None)
    where = "이 채널" if here else "내 DM"

    # 이미 등록된 사이트면 큐 안 거치고 즉시 subscription 추가 + 예시
    if _is_registered(slug):
        display_title = db.display_title_for_slug(_conn, slug) or _state_display_title(slug)
        db.add_subscription(_conn, user_id=user_id, slug=slug, url=url,
                            filter_prompt=filter_prompt, schedule="realtime",
                            target_kind=target_kind, target_id=target_id,
                            notify_empty=notify_empty,
                            display_title=display_title)
        # 발송 시각 설정 행 보장 (ADR 0006) — due 쿼리 인덱스 스캔용. 기본 08:30.
        db.ensure_setting(_conn, target_kind=target_kind, target_id=target_id)
        n = _baseline_count(slug)
        head = msg("watch_already_registered_head",
                   slug=slug,
                   n=(n if n is not None else '?'),
                   filter=(filter_prompt or '없음(새 글 전부)'),
                   where=where,
                   notify_empty=('예' if notify_empty else '아니오'),
                   warn=_body_warning(slug))
        await interaction.edit_original_response(
            content=head + "\n\n" + msg("watch_example_loading_suffix"))
        example = await site_ops.make_example(slug)
        if example:
            await interaction.edit_original_response(
                content=head + "\n\n" + msg("watch_example_present_prefix") + "\n" + example)
        else:
            await interaction.edit_original_response(
                content=head + "\n\n" + msg("watch_example_skip"))
        return

    # 신규 사이트 — URL 게이트 → 큐 enqueue → worker 가 처리하면 ack 메시지 edit
    requested_by = {"id": user_id, "name": str(interaction.user)}
    err = await _gate_check(url, article_url=art, via="watch", requested_by=requested_by)
    if err:
        await interaction.edit_original_response(content=msg("gate_rejected", err=err))
        return

    # interaction 응답을 채널 메시지로 promote → worker 가 token 만료와 무관하게 edit 가능
    await interaction.edit_original_response(content=msg("enqueueing"))
    ack_msg = await interaction.original_response()
    sub_payload = json.dumps({
        "user_id": user_id, "filter_prompt": filter_prompt, "schedule": "realtime",
        "target_kind": target_kind, "target_id": target_id, "notify_empty": bool(notify_empty),
    })
    job_id, inserted = db.enqueue_job(
        _conn, kind="register", url=url, slug=slug, article_url=art,
        via="watch", requested_by=json.dumps(requested_by),
        ack_channel_id=str(ack_msg.channel.id), ack_message_id=str(ack_msg.id),
        sub_payload=sub_payload, dedupe=False,
    )
    # 같은 URL 의 다른 잡이 이미 큐/실행 중이면 K1/K3 ack ("이미 처리 중") — worker 의 SQL skip +
    # claim 가드가 자연 흡수해 subprocess 는 1회만 돈다.
    inflight = db.find_earlier_same_slug_job(_conn, slug, exclude_id=job_id)
    if inflight is not None:
        text = msg("queued_same_url", job_id=inflight)
    else:
        pos = db.queue_position(_conn, job_id)
        if pos <= 1:
            text = msg("watch_queued_first", job_id=job_id)
        else:
            text = msg("watch_queued_wait", job_id=job_id, pos=pos)
    await interaction.edit_original_response(content=text)


async def _own_slug_autocomplete(interaction: discord.Interaction, current: str
                                  ) -> list[app_commands.Choice[str]]:
    """본인 subscriptions 의 slug 자동완성. Discord Choice.value 100자 한계 — 그 이상은 제외."""
    rows = db.list_subscriptions(_conn, user_id=str(interaction.user.id))
    cur = (current or "").lower()
    out: list[app_commands.Choice[str]] = []
    for r in rows:
        slug = r["slug"]
        if len(slug) > 100:
            continue
        if not cur or cur in slug.lower():
            out.append(app_commands.Choice(name=slug[:100], value=slug))
            if len(out) >= 25:
                break
    return out


_GENERIC_TITLES = {
    "blog", "home", "index", "software", "tools", "loading...", "loading",
    "untitled", "redirect", "redirecting", "please wait", "page not found",
    "404", "403", "discord", "github",
}


def _display_title(row) -> str:
    title = (row["display_title"] if "display_title" in row.keys() else None) or ""
    title = title.strip()
    # 짧거나 generic 한 title (예: codingapple.com/blog 의 "Blog") 는 host 가 더 정보적.
    if not title or len(title) < 6 or title.lower() in _GENERIC_TITLES:
        u = urlparse(row["url"] or "")
        host_path = (u.netloc + u.path).strip("/")
        title = host_path or row["slug"]
    return title[:80]


def _state_display_title(slug: str) -> Optional[str]:
    try:
        title = json.loads((STATE_DIR / f"{slug}.json").read_text(encoding="utf-8")).get("display_title")
    except Exception:  # noqa: BLE001
        return None
    title = str(title or "").strip()
    return title or None


def _short_text(text: Optional[str], limit: int) -> str:
    s = (text or "").replace("\n", " ").strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


class SubscriptionRemoveButton(discord.ui.Button["SubscriptionListView"]):
    """Section 의 accessory — 행 옆 inline 해제 button. emoji-only + secondary
    = Discord 의 compact icon button (label 박으면 크고 두드러져 사용자 거부 2026-05-23)."""

    def __init__(self, sub_id: int) -> None:
        super().__init__(emoji="❌", style=discord.ButtonStyle.secondary,
                         custom_id=f"sub_rem_{sub_id}")
        self.sub_id = sub_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = self.view  # type: ignore[assignment]
        db.remove_subscription_by_id(_conn, user_id=view.user_id, sub_id=self.sub_id)
        new_view = SubscriptionListView(user_id=view.user_id, page=view.page)
        await interaction.edit_original_response(view=new_view)


class SubscriptionNavButton(discord.ui.Button["SubscriptionListView"]):
    """페이지 nav — direction ±1."""

    def __init__(self, label: str, direction: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary,
                         custom_id=f"sub_nav_{direction}")
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        view = self.view  # type: ignore[assignment]
        new_page = max(0, min(view._max_page(), view.page + self.direction))
        new_view = SubscriptionListView(user_id=view.user_id, page=new_page)
        await interaction.edit_original_response(view=new_view)


class SubscriptionListView(discord.ui.LayoutView):
    """Components v2 (discord.py 2.4+) 패턴 — 각 sub 가 Section + accessory=Button 으로
    행 옆에 inline ✕ 버튼. 사용자 요청 (2026-05-23) 으로 v1 의 ActionRow-only 한계 회피.

    구조:
      Container(accent_color=blurple):
        TextDisplay("## 📋 내 구독 (N개 · p/m페이지) ...")
        Separator()
        Section("**1. <title>**", "필터: ... · 발송: ...", accessory=✕)
        Section(... 2 ...)
        ...
        Separator()
        ActionRow([◀ 이전][다음 ▶])  # max_page > 0 시만

    매 callback (✕·nav) 마다 *새 view 인스턴스* 만들어 edit_message — children 동적 mutate 회피.
    embed/content 사용 안 함 (v2 한계: 동시 사용 X). 모든 텍스트 TextDisplay/Section 안.
    필터 수정 기능 없음 (사용자 결정 — Modal UX 거부). 필터 바꾸려면 unwatch + 재 /watch.
    """

    # Components V2 의 LayoutView 가 max 40 children 한계. Section = 4 children 카운트
    # (codex 최종 리뷰 확인 — discord.py 2.7.1 에서 ValueError reproduce 됨).
    # 8 sections × 4 + Container + nav (Separator + ActionRow + footer TextDisplay)
    # ≈ 36 — 안전 마진.
    PAGE_SIZE = 8

    def __init__(self, *, user_id: str, page: int = 0) -> None:
        super().__init__(timeout=300)
        self.user_id = user_id
        self.rows = db.list_subscriptions(_conn, user_id=user_id)
        max_page = max(0, (len(self.rows) - 1) // self.PAGE_SIZE)
        self.page = max(0, min(page, max_page))

        if not self.rows:
            self.add_item(discord.ui.Container(
                discord.ui.TextDisplay(
                    "구독이 없어요. `/watch <url>` 로 추가하세요."
                ),
                accent_color=discord.Color.blurple(),
            ))
            return

        start = self.page * self.PAGE_SIZE
        prs = self.rows[start:start + self.PAGE_SIZE]

        children: list = []
        for offset, r in enumerate(prs):
            idx = start + offset + 1
            where = "내 DM" if r["target_kind"] == "dm" else f"<#{r['target_id']}>"
            filt = _short_text(r["filter_prompt"] or "없음 (새 글 전부)", 200)
            title = _display_title(r)
            url = r["url"] or ""
            # 제목 markdown link — 클릭 시 외부 URL 열림
            title_md = f"[{title}]({url})" if url else title
            children.append(discord.ui.Section(
                f"**{idx}. {title_md}**",
                f"📝 필터: {filt} · 📨 발송: {where}",
                accessory=SubscriptionRemoveButton(int(r["id"])),
            ))

        if max_page > 0:
            prev_btn: discord.ui.Button
            next_btn: discord.ui.Button
            if self.page > 0:
                prev_btn = SubscriptionNavButton("◀ 이전", -1)
            else:
                prev_btn = discord.ui.Button(label="◀ 이전",
                                             style=discord.ButtonStyle.secondary,
                                             disabled=True, custom_id="sub_nav_prev_dis")
            if self.page < max_page:
                next_btn = SubscriptionNavButton("다음 ▶", +1)
            else:
                next_btn = discord.ui.Button(label="다음 ▶",
                                             style=discord.ButtonStyle.secondary,
                                             disabled=True, custom_id="sub_nav_next_dis")
            children.append(discord.ui.Separator(visible=True))
            children.append(discord.ui.ActionRow(prev_btn, next_btn))
            children.append(discord.ui.TextDisplay(
                f"-# {len(self.rows)}개 구독 · {self.page + 1}/{max_page + 1}페이지"
            ))

        container = discord.ui.Container(
            *children, accent_color=discord.Color.blurple(),
        )
        self.add_item(container)

    def _max_page(self) -> int:
        return max(0, (len(self.rows) - 1) // self.PAGE_SIZE)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "이 목록은 호출한 사람만 조작할 수 있어요.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log.error("[list view] item=%s error=%s\n%s",
                  getattr(item, 'custom_id', '?'), error, tb)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"⚠️ 오류: {type(error).__name__} — 다시 시도해 주세요.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"⚠️ 오류: {type(error).__name__} — 다시 시도해 주세요.", ephemeral=True)
        except Exception:  # noqa: BLE001
            pass


@tree.command(name="list", description="내 구독 목록과 편집 UI")
async def list_cmd(interaction: discord.Interaction):
    # 3초 ack 안전망 — View 생성·db 조회가 sqlite lock 시 느려질 수 있음 (Unknown interaction 10062 회피).
    await interaction.response.defer(ephemeral=True)
    view = SubscriptionListView(user_id=str(interaction.user.id))
    # Components v2 — embed/content 동시 사용 불가능. view 만 박음 (header 는 view 안 TextDisplay).
    await interaction.followup.send(view=view, ephemeral=True)


_FEEDBACK_MAX_LEN_AT_LOAD = feedback_max_len()  # description 은 등록 시점에 고정 — restart 시 갱신


@tree.command(
    name="feedback",
    description=f"자유 의견 (slug 무관, 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자).",
)
@app_commands.describe(
    message=f"의견 — 자연어 자유 입력. 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자.",
)
async def feedback_cmd(interaction: discord.Interaction, message: str):
    # 3초 ack 안전망.
    await interaction.response.defer(ephemeral=True)
    max_len = feedback_max_len()
    text = (message or "").strip()
    if not text:
        await interaction.followup.send(msg("feedback_empty"), ephemeral=True)
        return
    if len(text) > max_len:
        await interaction.followup.send(
            msg("feedback_too_long", max_len=max_len, cur_len=len(text)),
            ephemeral=True,
        )
        return
    fid = db.add_feedback(
        _conn, user_id=str(interaction.user.id),
        username=str(interaction.user), message=text,
    )
    await interaction.followup.send(
        msg("feedback_received", fid=fid),
        ephemeral=True,
    )
    # OWNER DM — 전문 그대로. send_chunked_dm 이 2000자 단위로 split.
    try:
        oid = owner_user_id()
        if oid and oid.isdigit():
            body = msg("feedback_owner_dm",
                       fid=fid,
                       user=interaction.user,
                       user_id=interaction.user.id,
                       at_iso=_now_iso(),
                       message=text)
            await admin_mod.send_chunked_dm(client, oid, body)
    except Exception as e:  # noqa: BLE001
        log.warning("feedback owner DM 실패: %r", e)


_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _normalize_hhmm(raw: str) -> Optional[str]:
    """'8:30' / '08:30' → '08:30' (zero-pad). 형식 틀리면 None.
    zero-pad 는 due 쿼리의 문자열 시각 비교(deliver_at <= now)가 맞으려면 필수."""
    m = _HHMM_RE.match(raw.strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


class SettingTimeModal(discord.ui.Modal):
    def __init__(self, view: "SettingView", target_kind: str, target_id: str, current: str) -> None:
        super().__init__(title="발송 시각")
        self.view_ref = view
        self.target_kind = target_kind
        self.target_id = target_id
        self.time_input = discord.ui.TextInput(
            label="발송 시각 (HH:MM, KST 24시간)",
            default=current,
            required=True,
            max_length=5,
            placeholder="예: 08:30",
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        hhmm = _normalize_hhmm(str(self.time_input.value or ""))
        if not hhmm:
            await interaction.response.send_message(
                "시각 형식이 올바르지 않아요. `HH:MM` (예: `08:30`)으로 적어 주세요.",
                ephemeral=True,
            )
            return
        # codex 리뷰 Critical 2 — sqlite lock 대비 즉시 ack.
        await interaction.response.defer()
        db.set_deliver_at(_conn, target_kind=self.target_kind, target_id=self.target_id,
                          deliver_at=hhmm)
        self.view_ref.refresh()
        await interaction.edit_original_response(embed=self.view_ref.embed(),
                                                 view=self.view_ref)


class SettingView(discord.ui.View):
    """RoboDanny 패턴 — item set 고정, refresh() 가 label/disabled 만 mutate.

    레이아웃 (5 ActionRow 안):
      Row0: [📨 DM 공지: ON/OFF]  [📣 채널 공지: ON/OFF]  ← 채널 버튼은 guild 일 때만 enable
      Row1: [⏰ DM 시각: hh:mm ✎] [⏰ 채널 시각: hh:mm ✎]
      Row2: [❌ 닫기]

    DM(=guild 아님) 컨텍스트에선 채널 버튼 둘 다 disabled. guild 인데 Manage Channels 권한 없으면 disabled.
    """

    def __init__(self, *, user_id: str, channel_id: Optional[str], manage_channels: bool) -> None:
        super().__init__(timeout=300)
        self.user_id = user_id
        self.channel_id = channel_id
        self.manage_channels = manage_channels
        # 모든 item __init__ 에 한 번만 add — 이후 refresh() 가 label/disabled mutate
        self.dm_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, row=0,
                                        custom_id="set_dm")
        self.ch_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, row=0,
                                        custom_id="set_ch")
        self.dm_time_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, row=1,
                                             custom_id="set_dm_time")
        self.ch_time_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, row=1,
                                             custom_id="set_ch_time")
        self.close_btn = discord.ui.Button(label="❌ 닫기", style=discord.ButtonStyle.secondary,
                                           row=2, custom_id="set_close")
        self.dm_btn.callback = self._dm_cb
        self.ch_btn.callback = self._ch_cb
        self.dm_time_btn.callback = self._dm_time_cb
        self.ch_time_btn.callback = self._ch_time_cb
        self.close_btn.callback = self._close_cb
        for it in (self.dm_btn, self.ch_btn, self.dm_time_btn, self.ch_time_btn, self.close_btn):
            self.add_item(it)
        self.refresh()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "이 설정은 호출한 사람만 조작할 수 있어요.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception,
                       item: discord.ui.Item) -> None:
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log.error("[setting view] item=%s error=%s\n%s",
                  getattr(item, 'custom_id', '?'), error, tb)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"⚠️ 오류: {type(error).__name__} — 다시 시도해 주세요.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"⚠️ 오류: {type(error).__name__} — 다시 시도해 주세요.", ephemeral=True)
        except Exception:  # noqa: BLE001
            pass

    def refresh(self) -> None:
        # DM 공지·시각 — 본인 user 컨텍스트, 항상 enable
        dm_off = db.get_announce_optout(_conn, "dm", self.user_id)
        self.dm_btn.label = f"📨 DM 공지: {'OFF' if dm_off else 'ON'}"
        dm_time = db.get_deliver_at(_conn, target_kind="dm", target_id=self.user_id)
        self.dm_time_btn.label = f"⏰ DM 시각: {dm_time} ✎"
        # 채널 공지·시각 — guild 면 권한 따라 토글, DM 컨텍스트면 둘 다 비활성
        if self.channel_id:
            ch_off = db.get_announce_optout(_conn, "channel", self.channel_id)
            self.ch_btn.label = f"📣 채널 공지: {'OFF' if ch_off else 'ON'}"
            self.ch_btn.disabled = not self.manage_channels
            ch_time = db.get_deliver_at(_conn, target_kind="channel", target_id=self.channel_id)
            self.ch_time_btn.label = f"⏰ 채널 시각: {ch_time} ✎"
            self.ch_time_btn.disabled = not self.manage_channels
        else:
            self.ch_btn.label = "📣 채널 공지: (DM 에선 불가)"
            self.ch_btn.disabled = True
            self.ch_time_btn.label = "⏰ 채널 시각: (DM 에선 불가)"
            self.ch_time_btn.disabled = True

    def embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚙️ 발송 설정", color=0x5865F2)
        dm_off = db.get_announce_optout(_conn, "dm", self.user_id)
        dm_time = db.get_deliver_at(_conn, target_kind="dm", target_id=self.user_id)
        lines = [
            f"📨 DM 공지: **{'OFF (받지 않음)' if dm_off else 'ON (받음)'}**",
            f"⏰ DM 발송 시각: **{dm_time} (KST)**",
        ]
        if self.channel_id:
            ch_off = db.get_announce_optout(_conn, "channel", self.channel_id)
            ch_time = db.get_deliver_at(_conn, target_kind="channel", target_id=self.channel_id)
            suffix = "" if self.manage_channels else " — *Manage Channels 권한 필요*"
            lines.append("")
            lines.append(f"📣 채널 공지: **{'OFF' if ch_off else 'ON'}**{suffix}")
            lines.append(f"⏰ 채널 발송 시각: **{ch_time} (KST)**{suffix}")
        embed.description = "\n".join(lines)
        return embed

    async def _dm_cb(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        cur = db.get_announce_optout(_conn, "dm", self.user_id)
        db.set_announce_optout(_conn, "dm", self.user_id, opted_out=not cur)
        self.refresh()
        await interaction.edit_original_response(embed=self.embed(), view=self)

    async def _ch_cb(self, interaction: discord.Interaction) -> None:
        if not self.channel_id:
            await interaction.response.send_message(
                "DM 컨텍스트에서는 채널 공지를 토글할 수 없어요.", ephemeral=True)
            return
        await interaction.response.defer()
        cur = db.get_announce_optout(_conn, "channel", self.channel_id)
        db.set_announce_optout(_conn, "channel", self.channel_id, opted_out=not cur)
        self.refresh()
        await interaction.edit_original_response(embed=self.embed(), view=self)

    async def _dm_time_cb(self, interaction: discord.Interaction) -> None:
        cur = db.get_deliver_at(_conn, target_kind="dm", target_id=self.user_id)
        await interaction.response.send_modal(
            SettingTimeModal(self, "dm", self.user_id, cur))

    async def _ch_time_cb(self, interaction: discord.Interaction) -> None:
        if not self.channel_id:
            await interaction.response.send_message(
                "DM 컨텍스트에서는 채널 시각을 바꿀 수 없어요.", ephemeral=True)
            return
        cur = db.get_deliver_at(_conn, target_kind="channel", target_id=self.channel_id)
        await interaction.response.send_modal(
            SettingTimeModal(self, "channel", self.channel_id, cur))

    async def _close_cb(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(view=None)


@tree.command(name="setting", description="발송·공지 설정")
async def setting_cmd(interaction: discord.Interaction):
    # 3초 ack 안전망 — sqlite lock 시 느려질 수 있음.
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    channel_id = str(interaction.channel_id) if interaction.guild is not None and interaction.channel_id else None
    view = SettingView(user_id=user_id, channel_id=channel_id,
                       manage_channels=bool(interaction.permissions.manage_channels))
    await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)


@tree.command(name="help", description="봇 명령어 안내")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="📖 notice-watcher 명령어",
        description=msg("help_embed_description"),
        color=0x5865F2,
    )
    embed.add_field(
        name="구독 관리",
        value=(
            "`/watch <url> [filter:] [here:] [notify_empty:] [article_url:]`\n"
            "└ 게시판 URL 등록. filter 로 자연어 조건, here=true 면 이 채널에, 끄면 내 DM.\n"
            "`/list` — 내 구독 목록, 필터 수정, 구독 해제."
        ),
        inline=False,
    )
    embed.add_field(name="문제 신고 · 의견",
                    value=(
                        "`/report <issue> [slug:] [url:]` — 사이트 문제 신고 또는 지원 요청.\n"
                        f"`/feedback <message>` — 자유 의견(slug 무관, 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자)."
                    ),
                    inline=False)
    embed.add_field(
        name="설정",
        value="`/setting` — DM/채널 공지 ON/OFF 와 매일 발송 시각을 버튼으로 설정.",
        inline=False,
    )
    embed.add_field(name="기타", value=msg("help_field_misc_value"), inline=False)
    embed.set_footer(text=msg("help_footer"))
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="report", description="사이트 문제 신고 또는 지원 요청")
@app_commands.describe(
    issue="어떤 문제인지 자연어로 적어 주세요 (예: '아카 공식 탭만 받고 싶은데 일반 게시판 글이 와요')",
    slug="문제 있는 구독의 `slug` — 본인 구독 자동완성 돼요 (선택)",
    url="문제 있는 URL 또는 지원 요청 URL — `https://` 로 시작해요 (선택)",
)
@app_commands.autocomplete(slug=_own_slug_autocomplete)
async def report_cmd(interaction: discord.Interaction, issue: str,
                     slug: Optional[str] = None, url: Optional[str] = None):
    # 3초 ack 안전망 — inspector.inspect / db 호출 무거울 수 있음.
    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)
    issue = (issue or "").strip()
    if not issue:
        await interaction.followup.send(msg("report_issue_empty"), ephemeral=True)
        return
    slug = (slug or "").strip() or None
    url = (url or "").strip() or None
    if not slug and not url:
        await interaction.followup.send(
            "URL 없는 자유 의견은 `/feedback` 으로 보내주세요.", ephemeral=True)
        return
    if url and not re.match(r"^https?://", url):
        await interaction.followup.send(msg("validation_url_required"), ephemeral=True)
        return
    if slug:
        # slug 가 본인 구독이 아니면 거부 (자동완성 우회 입력 차단)
        own = {r["slug"] for r in db.list_subscriptions(_conn, user_id=user_id)}
        if slug not in own:
            await interaction.followup.send(
                msg("report_slug_not_owned", slug=slug), ephemeral=True)
            return
    issue_body = issue[:1500]
    if slug and url:
        issue_body = f"{issue_body}\n\nURL: {url}"
    report_id = db.add_report(_conn, user_id=user_id, username=str(interaction.user),
                              slug=slug, url=url, issue=issue_body)
    await interaction.followup.send(
        msg("report_received", report_id=report_id, slug=(slug or url or "URL")),
        ephemeral=True)
    # owner DM — 자동 진단 결과까지 함께. admin.send_chunked_dm 재사용(2000 chars split, 실패 시 False).
    try:
        paths = inspector.InspectorPaths.live()
        result = inspector.inspect(_conn, paths, report_id=report_id)
        if result:
            body = inspector.format_inspect_result(result)
        else:
            body = f"신고 #{report_id} — URL 기반 신고\nurl={url or '(없음)'}\nissue={issue_body}"
        oid = owner_user_id()
        if oid and oid.isdigit():
            await admin_mod.send_chunked_dm(client, oid, msg("report_owner_dm_prefix") + body)
    except Exception as e:  # noqa: BLE001
        log.warning("report owner DM 실패: %r", e)


# --------------------------------------------------------------------------- #
# 에러 핸들러 / lifecycle
# --------------------------------------------------------------------------- #
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    tb = _record_error("slash", error)
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=msg("error_slash_done"))
        else:
            await interaction.response.send_message(msg("error_slash_ephemeral"), ephemeral=True)
    except Exception:  # noqa: BLE001
        pass
    await _dm_owner(f"[봇 에러] {LAST_ERROR['text']}\n```\n{tb[-1500:]}\n```")


@client.event
async def on_error(event_method: str, *args, **kwargs):
    exc = sys.exc_info()[1]
    if exc:
        tb = _record_error(f"event:{event_method}", exc)
        await _dm_owner(f"[봇 이벤트 에러] {LAST_ERROR['text']}\n```\n{tb[-1500:]}\n```", key=f"evt:{event_method}")


@client.event
async def on_guild_join(guild: "discord.Guild"):
    # GUILD_ID 고정(dev) — 그 길드만 씀, 새 길드는 무시. production(글로벌) — 글로벌 commands 가
    # 자동으로 새 길드에 노출되므로 별도 sync 불필요. 둘 다 로그만 남김.
    log.info("joined guild %s (%s)", guild.id, getattr(guild, "name", "?"))


@client.event
async def on_ready():
    log.info("logged in as %s (id=%s); guilds=%s", client.user,
             client.user.id if client.user else "?", [g.id for g in client.guilds])
    if not safe_browsing_api_key():
        log.warning("⚠ SAFE_BROWSING_API_KEY 가 .env 에 없습니다 — URL 게이트의 Safe Browsing 검사가 "
                    "fail-closed 라 /watch(처음 보는 사이트)가 전부 거부됩니다. .env 에 키를 설정하세요 "
                    "(GCP 콘솔 → Safe Browsing API 사용 설정 → API 키).")
    # 잡 큐 worker 시작 — 재시작 시 running 잡 → pending 리셋. on_ready 가 reconnect 마다 호출돼도 worker.start 안에서 idempotent.
    try:
        await worker.start(client, _conn, dm_owner=_dm_owner)
    except Exception as e:  # noqa: BLE001
        _record_error("worker.start", e)
    # 발송창 tick 시작 (ADR 0006) — 1분 주기로 due 수신처 확인 후 deliver_due subprocess.
    try:
        await delivery_tick.start(_conn)
    except Exception as e:  # noqa: BLE001
        _record_error("delivery_tick.start", e)
    gid = guild_id()
    agid = admin_guild_id()
    try:
        if gid:
            # dev mode — GUILD_ID 지정. 그 길드에 즉시 sync (copy_global_to 로 글로벌 set 도 포함).
            g = discord.Object(id=gid)
            tree.copy_global_to(guild=g)
            synced = await tree.sync(guild=g)
            log.info("synced %d commands to guild %s (dev mode)", len(synced), gid)
        else:
            # production — 글로벌 sync 만. 기존에 guild-scoped 로 복사된 commands 가 있으면 clear
            # (이전 버전이 copy_global_to + per-guild sync 도 같이 해서 검색 결과에 명령이 2개씩 떴음).
            # admin guild 는 /admin 그룹을 guild-scope 로 일부러 두므로 clear 대상에서 제외.
            for g in client.guilds:
                if agid and g.id == agid:
                    continue
                try:
                    tree.clear_commands(guild=g)
                    await tree.sync(guild=g)
                except Exception as e:  # noqa: BLE001
                    log.warning("guild %s 기존 guild-scoped commands 정리 실패: %r", g.id, e)
            synced = await tree.sync()
            log.info("synced %d global commands (전파 ~1h)", len(synced))
    except Exception as e:  # noqa: BLE001
        _record_error("tree.sync", e)

    # admin 전용 명령(`/admin ...`) — ADMIN_GUILD_ID 설정된 경우만 그 길드에 sync.
    # 메인 tree 와 분리: 다른 길드/DM autocomplete 에 admin 명령이 노출되지 않게 한다.
    if agid:
        try:
            ag = discord.Object(id=agid)
            # reconnect 마다 on_ready 가 다시 불릴 수 있음 — admin group 중복 등록 가드.
            # build_admin_tree 가 이미 박혀있으면 skip (idempotent).
            if tree.get_command("admin", guild=ag) is None:
                admin_mod.build_admin_tree(client, _conn, admin_guild=ag, tree=tree,
                                           start_ts=START_TS, last_error=LAST_ERROR)
            synced = await tree.sync(guild=ag)
            log.info("synced %d admin commands to admin guild %s (guild-scoped)", len(synced), agid)
        except Exception as e:  # noqa: BLE001
            _record_error("admin_tree.sync", e)
    else:
        log.info("ADMIN_GUILD_ID 미설정 — admin 명령 등록 생략(보안 디폴트)")


def main() -> int:
    tok = bot_token()
    if not tok:
        print("[ERROR] BOT_TOKEN 이 없습니다. .env 또는 환경변수에 설정하세요.", file=sys.stderr)
        return 2
    client.run(tok, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
