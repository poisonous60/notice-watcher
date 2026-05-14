"""Discord 봇 — 게시판 등록(/watch) · 미리보기(/preview) · 목록(/list) · 해제(/unwatch) · 상태(/status).

- 게이트웨이 연결(아웃바운드만 — 포트포워딩 불필요). 슬래시 명령 *수신* 용.
- `/watch`·`/preview`(처음 보는 사이트) 는 jobs 큐에 enqueue 만 함. 실제 register.py 실행은
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
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord  # noqa: E402
from discord import app_commands  # noqa: E402

from bot import admin as admin_mod, db, inspector, site_ops, url_gate, worker  # noqa: E402
from bot.config import (  # noqa: E402
    admin_guild_id, bot_token, feedback_max_len, guild_id, owner_user_id, safe_browsing_api_key,
)
from probe.paths import url_to_slug  # noqa: E402

CONFIGS_DIR = site_ops.CONFIGS_DIR
STATE_DIR = site_ops.STATE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

# 모든 구독은 polling 직후 notify.py 가 즉시 발송(schedule='realtime'). 사용자 시간 선택 없음.

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


# --------------------------------------------------------------------------- #
# URL 게이트 wrapper — 거부 시 OWNER DM 등 부수 처리
# --------------------------------------------------------------------------- #
async def _gate_check(url: str, *, article_url: Optional[str], via: str,
                       requested_by: Optional[dict]) -> Optional[str]:
    """URL 게이트 통과 시 None, 거부 시 사용자에게 보여줄 메시지(이미 OWNER DM 등 부수 처리 완료)."""
    try:
        await url_gate.check(url, article_url=article_url)
        return None
    except url_gate.UrlRejected as e:
        log.info("[url_gate] reject %s (article=%s): %s — %s", url, article_url, e.reason, e.msg)
        if e.reason == "malicious":
            await _dm_owner(f"⚠️ [url_gate] 악성 URL 등록 시도 차단\nURL: {url}\n사유: {e.msg}\n"
                            f"요청: {(requested_by or {}).get('name', '?')} (via {via})", key="url_gate_malicious")
        elif e.reason == "gsb_error":
            await _dm_owner(f"⚠️ [url_gate] Safe Browsing 검사 실패 — {e.msg}\nURL: {url}", key="url_gate_gsb")
        return e.msg


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
        await interaction.edit_original_response(content="❌ http(s):// 로 시작하는 URL 을 주세요.")
        return
    art = (article_url or "").strip() or None
    if art and not re.match(r"^https?://", art):
        await interaction.edit_original_response(content="❌ article_url 은 http(s):// 로 시작하는 글 URL 이어야 해요.")
        return

    slug = url_to_slug(url)
    user_id = str(interaction.user.id)
    target_kind = "channel" if here else "dm"
    target_id = str(interaction.channel_id) if here else user_id
    filter_prompt = (filter.strip() if filter and filter.strip() else None)
    where = "이 채널" if here else "내 DM"

    # 이미 등록된 사이트면 큐 안 거치고 즉시 subscription 추가 + 예시
    if _is_registered(slug):
        db.add_subscription(_conn, user_id=user_id, slug=slug, url=url,
                            filter_prompt=filter_prompt, schedule="realtime",
                            target_kind=target_kind, target_id=target_id,
                            notify_empty=notify_empty)
        n = _baseline_count(slug)
        head = (f"✅ 구독 추가 — `{slug}` (이미 등록된 사이트)\n"
                f"• baseline {n if n is not None else '?'}건\n"
                f"• 필터: {filter_prompt or '없음(새 글 전부)'}\n"
                f"• 발송: 폴링 직후 즉시\n"
                f"• 알림: {where}\n"
                f"• 새 글 없을 때도 알림: {'예' if notify_empty else '아니오'}")
        await interaction.edit_original_response(content=head + "\n\n📋 예시 알림 만드는 중…")
        example = await site_ops.make_example(slug)
        if example:
            await interaction.edit_original_response(
                content=head + "\n\n📋 **예시 알림** (이런 형식으로 옵니다):\n" + example)
        else:
            await interaction.edit_original_response(content=head + "\n\n(예시 알림 생성은 건너뜀 — 등록은 정상)")
        return

    # 신규 사이트 — URL 게이트 → 큐 enqueue → worker 가 처리하면 ack 메시지 edit
    requested_by = {"id": user_id, "name": str(interaction.user)}
    err = await _gate_check(url, article_url=art, via="watch", requested_by=requested_by)
    if err:
        await interaction.edit_original_response(content=f"⚠️ {err}")
        return

    # interaction 응답을 채널 메시지로 promote → worker 가 token 만료와 무관하게 edit 가능
    await interaction.edit_original_response(content="📥 큐 추가 중…")
    msg = await interaction.original_response()
    sub_payload = json.dumps({
        "user_id": user_id, "filter_prompt": filter_prompt, "schedule": "realtime",
        "target_kind": target_kind, "target_id": target_id, "notify_empty": bool(notify_empty),
    })
    job_id, inserted = db.enqueue_job(
        _conn, kind="register", url=url, slug=slug, article_url=art,
        via="watch", requested_by=json.dumps(requested_by),
        ack_channel_id=str(msg.channel.id), ack_message_id=str(msg.id),
        sub_payload=sub_payload, dedupe=False,
    )
    pos = db.queue_position(_conn, job_id)
    if pos <= 1:
        text = f"📥 큐 추가됨 (잡 #{job_id}) — 곧 처리 시작합니다. 끝나면 이 메시지로 알려드릴게요."
    else:
        text = (f"📥 큐 추가됨 (잡 #{job_id}) — 현재 대기열 **{pos}번째**. "
                f"이전 잡들이 끝나면 처리되고, 결과는 이 메시지로 알려드릴게요.")
    await interaction.edit_original_response(content=text)


@tree.command(name="preview", description="등록 없이 그 게시판의 최신 글 하나를 요약해 알림 예시를 보여줍니다.")
@app_commands.describe(
    url="공지/게시판 목록 페이지 URL",
    article_url="(선택) 이 사이트가 처음이고 자동 분석에 실패할 때, 그 게시판의 실제 글 하나 URL 을 같이 주면 분석 성공률이 올라갑니다.",
)
async def preview(interaction: discord.Interaction, url: str, article_url: Optional[str] = None):
    # ephemeral=False 로 — worker 가 채널 메시지 edit 으로 ack 해야 하니까 (token 만료 영향 X).
    # 단 등록 끝나면 자동 unsubscribe — preview 만 보고 싶었던 사용자를 위해 결과 보여준 후 정리.
    await interaction.response.defer(thinking=True)
    url = url.strip()
    if not re.match(r"^https?://", url):
        await interaction.edit_original_response(content="❌ http(s):// 로 시작하는 URL 을 주세요.")
        return
    art = (article_url or "").strip() or None
    if art and not re.match(r"^https?://", art):
        await interaction.edit_original_response(content="❌ article_url 은 http(s):// 로 시작하는 글 URL 이어야 해요.")
        return

    slug = url_to_slug(url)
    if _is_registered(slug):
        # 등록된 사이트 — 즉시 예시만
        await interaction.edit_original_response(content="⏳ 최신 글 가져와 요약 중…")
        example = await site_ops.make_example(slug)
        if example:
            await interaction.edit_original_response(content="📋 **이 게시판 알림 예시:**\n" + example)
        else:
            await interaction.edit_original_response(content="⚠️ 예시를 만들지 못했어요(목록이 비었거나 본문 추출 실패).")
        return

    # 신규 사이트 — URL 게이트 → 큐 enqueue
    requested_by = {"id": str(interaction.user.id), "name": str(interaction.user)}
    err = await _gate_check(url, article_url=art, via="preview", requested_by=requested_by)
    if err:
        await interaction.edit_original_response(content=f"⚠️ {err}")
        return

    await interaction.edit_original_response(content="📥 큐 추가 중…")
    msg = await interaction.original_response()
    job_id, inserted = db.enqueue_job(
        _conn, kind="register", url=url, slug=slug, article_url=art,
        via="preview", requested_by=json.dumps(requested_by),
        ack_channel_id=str(msg.channel.id), ack_message_id=str(msg.id),
        sub_payload=None,  # preview 는 subscription 안 만듦
        dedupe=False,
    )
    pos = db.queue_position(_conn, job_id)
    if pos <= 1:
        text = f"📥 큐 추가됨 (잡 #{job_id}) — 곧 처리 시작합니다. 끝나면 이 메시지에 예시 알림이 뜹니다."
    else:
        text = (f"📥 큐 추가됨 (잡 #{job_id}) — 현재 대기열 **{pos}번째**. "
                f"끝나면 이 메시지에 예시 알림이 뜹니다.")
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


@tree.command(name="unwatch", description="구독 해제. slug 또는 URL 을 줍니다.")
@app_commands.describe(target="해제할 구독의 slug (자동완성) 또는 등록할 때 쓴 URL")
@app_commands.autocomplete(target=_own_slug_autocomplete)
async def unwatch(interaction: discord.Interaction, target: str):
    t = target.strip()
    slug = url_to_slug(t) if re.match(r"^https?://", t) else t
    n = db.remove_subscription(_conn, user_id=str(interaction.user.id), slug=slug)
    if n:
        await interaction.response.send_message(f"🔕 구독 해제: `{slug}` ({n}건)", ephemeral=True)
    else:
        await interaction.response.send_message(f"해당 구독 없음: `{slug}` — `/list` 로 확인해 주세요.", ephemeral=True)


@tree.command(name="list", description="내 구독 목록")
async def list_cmd(interaction: discord.Interaction):
    rows = db.list_subscriptions(_conn, user_id=str(interaction.user.id))
    if not rows:
        await interaction.response.send_message("구독 없음. `/watch <url>` 로 추가하세요.", ephemeral=True)
        return
    lines = ["**내 구독:**"]
    for r in rows:
        where = "DM" if r["target_kind"] == "dm" else f"<#{r['target_id']}>"
        ne = " — 새글없음알림:on" if r["notify_empty"] else ""  # connect() 가 항상 _migrate 하므로 컬럼은 늘 있음
        lines.append(f"• `{r['slug']}` — 필터: {r['filter_prompt'] or '없음'} — {where}{ne} — 등록 {r['created_at'][:10]}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


_FEEDBACK_MAX_LEN_AT_LOAD = feedback_max_len()  # description 은 등록 시점에 고정 — restart 시 갱신


@tree.command(
    name="feedback",
    description=f"자유 의견 (slug 무관, 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자).",
)
@app_commands.describe(
    message=f"의견 — 자연어 자유 입력. 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자.",
)
async def feedback_cmd(interaction: discord.Interaction, message: str):
    max_len = feedback_max_len()
    msg = (message or "").strip()
    if not msg:
        await interaction.response.send_message("❌ message 가 비어있습니다.", ephemeral=True)
        return
    if len(msg) > max_len:
        await interaction.response.send_message(
            f"❌ 너무 깁니다 — {max_len}자 이내로 줄여 주세요. (현재 {len(msg)}자)",
            ephemeral=True,
        )
        return
    fid = db.add_feedback(
        _conn, user_id=str(interaction.user.id),
        username=str(interaction.user), message=msg,
    )
    await interaction.response.send_message(
        f"✅ 의견 접수됨 (#{fid}). 읽어볼게요. 추가 의견은 다시 `/feedback`.",
        ephemeral=True,
    )
    # OWNER DM — 전문 그대로. send_chunked_dm 이 2000자 단위로 split.
    try:
        oid = owner_user_id()
        if oid and oid.isdigit():
            body = (f"💬 새 의견 #{fid}\n"
                    f"• from: {interaction.user} (id={interaction.user.id})\n"
                    f"• at: {_now_iso()}\n\n{msg}")
            await admin_mod.send_chunked_dm(client, oid, body)
    except Exception as e:  # noqa: BLE001
        log.warning("feedback owner DM 실패: %r", e)


@tree.command(name="announce", description="봇 공지 수신 설정 — 인자 없이 호출하면 현재 상태 표시.")
@app_commands.describe(
    dm="내 DM 으로 공지 받기 (true=받음 / false=옵트아웃). 미지정이면 변경 안 함.",
    channel="이 채널로 공지 받기 (true=받음 / false=옵트아웃). 'Manage Channels' 권한 필요. DM 에선 사용 불가.",
)
async def announce_cmd(interaction: discord.Interaction,
                       dm: Optional[bool] = None,
                       channel: Optional[bool] = None):
    user_id = str(interaction.user.id)
    is_guild = interaction.guild is not None
    ch_id = str(interaction.channel_id) if interaction.channel_id else None
    lines: list[str] = []

    # dm 토글 — bool 인자 제공 시
    if dm is not None:
        db.set_announce_optout(_conn, "dm", user_id, opted_out=not dm)
        lines.append(f"📩 DM 공지: **{'ON' if dm else 'OFF'}** 로 설정됨.")

    # channel 토글 — guild 안 + manage_channels 권한 + 채널에 봇이 알림 보내는 곳인지.
    # interaction.permissions 는 항상 Permissions 객체(DM 이면 빈, guild 채널이면 effective).
    if channel is not None:
        if not is_guild or not ch_id:
            lines.append("❌ `channel:` 인자는 길드 채널에서만 사용 가능 (DM 에선 불가).")
        elif not interaction.permissions.manage_channels:
            lines.append("❌ 이 채널의 공지 설정은 `Manage Channels` 권한이 있는 사람만 변경 가능.")
        else:
            db.set_announce_optout(_conn, "channel", ch_id, opted_out=not channel)
            lines.append(f"📢 이 채널 공지: **{'ON' if channel else 'OFF'}** 로 설정됨.")

    # 무인자 또는 토글 후 — 현재 상태 표시
    dm_off = db.get_announce_optout(_conn, "dm", user_id)
    state = [f"📩 내 DM 공지: **{'OFF' if dm_off else 'ON'}**"]
    if is_guild and ch_id:
        ch_off = db.get_announce_optout(_conn, "channel", ch_id)
        state.append(f"📢 이 채널 공지: **{'OFF' if ch_off else 'ON'}**")
    if not lines:
        lines.append("**현재 공지 설정**")
    lines.append("")
    lines.extend(state)
    lines.append("")
    lines.append("토글: `/announce dm:false` 로 DM 끄기, `/announce dm:true` 로 다시 켜기. "
                 "채널은 `Manage Channels` 권한자가 그 채널에서 `/announce channel:false`.")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="help", description="봇 명령어 안내")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 notice-watcher 명령어",
        description="공지/게시판을 등록해 새 글이 올라오면 Discord 로 알려주는 봇.",
        color=0x5865F2,
    )
    embed.add_field(
        name="구독 관리",
        value=(
            "`/watch <url> [filter:] [here:] [notify_empty:] [article_url:]`\n"
            "└ 게시판 URL 등록. filter 로 자연어 조건, here=true 면 이 채널에, 끄면 내 DM.\n"
            "`/preview <url>` — 등록 없이 최신 글 한 건으로 알림 예시 보기.\n"
            "`/list` — 내 구독 목록.\n"
            "`/unwatch <slug 또는 url>` — 구독 해제 (slug 자동완성)."
        ),
        inline=False,
    )
    embed.add_field(
        name="문제 신고 · 의견 · 상태",
        value=(
            "`/report <slug> <issue>` — 본인 구독에 문제 있을 때 신고. 관리자가 진단·해결.\n"
            f"`/feedback <message>` — 자유 의견(slug 무관, 최대 {_FEEDBACK_MAX_LEN_AT_LOAD}자).\n"
            "`/status` — 봇·폴링 상태 (가동시간, 잡 큐, 마지막 폴링 등)."
        ),
        inline=False,
    )
    embed.add_field(
        name="공지 수신 설정",
        value=(
            "`/announce` — 현재 공지 수신 상태 표시.\n"
            "`/announce dm:false` — 내 DM 공지 끄기 / `dm:true` 로 다시 켜기.\n"
            "`/announce channel:false` — 이 채널 공지 끄기 (`Manage Channels` 권한 필요)."
        ),
        inline=False,
    )
    embed.add_field(
        name="기타",
        value=(
            "`/help` — 이 안내.\n"
            "모든 응답은 ephemeral (본인만 보임). 알림 발송은 폴링 직후 즉시."
        ),
        inline=False,
    )
    embed.set_footer(text="문제가 생기면 /report 로 신고해 주세요.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="report", description="본인 구독에 문제가 있을 때 신고 — 관리자가 진단·해결합니다.")
@app_commands.describe(
    slug="문제 있는 구독의 slug (목록에서 자동완성)",
    issue="무슨 문제? 자연어로 자유롭게 (예: '아카 공식 탭만 받고 싶은데 일반 게시판 글이 와요')",
)
@app_commands.autocomplete(slug=_own_slug_autocomplete)
async def report_cmd(interaction: discord.Interaction, slug: str, issue: str):
    user_id = str(interaction.user.id)
    issue = (issue or "").strip()
    if not issue:
        await interaction.response.send_message("❌ issue 설명이 비어있습니다.", ephemeral=True)
        return
    # slug 가 본인 구독이 아니면 거부 (자동완성 우회 입력 차단)
    own = {r["slug"] for r in db.list_subscriptions(_conn, user_id=user_id)}
    if slug not in own:
        await interaction.response.send_message(
            f"❌ `{slug}` 은(는) 본인 구독 목록에 없습니다 — `/list` 로 확인해 주세요.", ephemeral=True)
        return
    report_id = db.add_report(_conn, user_id=user_id, username=str(interaction.user),
                              slug=slug, issue=issue[:1500])
    await interaction.response.send_message(
        f"✅ 신고 접수됨 (#{report_id}, `{slug}`). 관리자가 확인 후 조치합니다. 다른 문제가 더 있으면 다시 `/report`.",
        ephemeral=True)
    # owner DM — 자동 진단 결과까지 함께. admin.send_chunked_dm 재사용(2000 chars split, 실패 시 False).
    try:
        paths = inspector.InspectorPaths.live()
        result = inspector.inspect(_conn, paths, report_id=report_id)
        body = inspector.format_inspect_result(result) if result else f"신고 #{report_id} — inspect 실패"
        oid = owner_user_id()
        if oid and oid.isdigit():
            await admin_mod.send_chunked_dm(client, oid, "🚩 새 신고\n\n" + body)
    except Exception as e:  # noqa: BLE001
        log.warning("report owner DM 실패: %r", e)


@tree.command(name="status", description="봇/폴링 상태")
async def status(interaction: discord.Interaction):
    cnt = db.counts(_conn)
    jq = db.jobs_summary(_conn)
    n_configs = len(list(CONFIGS_DIR.glob("*.json"))) if CONFIGS_DIR.exists() else 0
    last_poll = None
    broken: list[str] = []
    failed: list[str] = []
    if STATE_DIR.exists():
        for f in STATE_DIR.glob("*.json"):
            if f.name.endswith(".FAILED.json"):
                failed.append(f.name[: -len(".FAILED.json")])
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            lp = d.get("last_poll_at")
            if lp and (last_poll is None or lp > last_poll):
                last_poll = lp
            if int(d.get("consecutive_breakage", 0) or 0) > 0:
                broken.append(d.get("slug", f.stem))
    up = int(time.time() - START_TS)
    gate = url_gate.rejection_summary_24h()
    gate_line = ("• URL 게이트 거부(24h, 재시작 시 리셋): "
                 + (", ".join(f"{k} {v}" for k, v in sorted(gate.items())) if gate else "없음")
                 + f"  · blacklist: {url_gate.blacklist_status()}"
                 + ("" if safe_browsing_api_key() else "  · ⚠SAFE_BROWSING_API_KEY 미설정 — 신규 등록 전부 거부됨"))
    jq_line = (f"• 잡 큐: pending {jq.get('pending', 0)}건 / running {jq.get('running', 0)}건 "
               f"/ done {jq.get('done', 0)} / failed {jq.get('failed', 0)}")
    lines = [
        "**봇 상태**",
        f"• uptime: {up // 3600}h {(up % 3600) // 60}m",
        gate_line,
        jq_line,
        f"• 등록 config: {n_configs}개 / 구독: {cnt['subscriptions']}건 ({cnt['slugs']} slug) / pending(레거시 미발송): {cnt['pending']}건",
        f"• 마지막 폴링: {last_poll or '아직 없음'}",
        f"• 깨짐 신호 있는 slug: {', '.join(broken) if broken else '없음'}",
        f"• 자동등록 실패 slug: {', '.join(failed) if failed else '없음'}",
        f"• 마지막 에러: {(LAST_ERROR['when'] + ' — ' + LAST_ERROR['text']) if LAST_ERROR['when'] else '없음'}",
    ]
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


# --------------------------------------------------------------------------- #
# 에러 핸들러 / lifecycle
# --------------------------------------------------------------------------- #
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    tb = _record_error("slash", error)
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content="⚠️ 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
        else:
            await interaction.response.send_message("⚠️ 처리 중 오류가 발생했어요.", ephemeral=True)
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
    log.info("joined guild %s (%s)", guild.id, getattr(guild, "name", "?"))
    if guild_id():
        return  # GUILD_ID 고정 모드면 거기만 씀
    try:
        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)
        log.info("synced %d commands to new guild %s", len(synced), guild.id)
    except Exception as e:  # noqa: BLE001
        log.warning("new guild %s sync 실패: %r", guild.id, e)


@client.event
async def on_ready():
    log.info("logged in as %s (id=%s); guilds=%s", client.user,
             client.user.id if client.user else "?", [g.id for g in client.guilds])
    if not safe_browsing_api_key():
        log.warning("⚠ SAFE_BROWSING_API_KEY 가 .env 에 없습니다 — URL 게이트의 Safe Browsing 검사가 "
                    "fail-closed 라 /watch·/preview(처음 보는 사이트)가 전부 거부됩니다. .env 에 키를 설정하세요 "
                    "(GCP 콘솔 → Safe Browsing API 사용 설정 → API 키).")
    # 잡 큐 worker 시작 — 재시작 시 running 잡 → pending 리셋. on_ready 가 reconnect 마다 호출돼도 worker.start 안에서 idempotent.
    try:
        await worker.start(client, _conn, dm_owner=_dm_owner)
    except Exception as e:  # noqa: BLE001
        _record_error("worker.start", e)
    gid = guild_id()
    try:
        if gid:
            g = discord.Object(id=gid)
            tree.copy_global_to(guild=g)
            synced = await tree.sync(guild=g)
            log.info("synced %d commands to guild %s", len(synced), gid)
        else:
            # GUILD_ID 미설정 — 봇이 들어가 있는 길드들에 즉시 동기화 + 글로벌(DM/추후 길드용, 전파 ~1h)
            for g in client.guilds:
                try:
                    tree.copy_global_to(guild=g)
                    synced = await tree.sync(guild=g)
                    log.info("synced %d commands to guild %s", len(synced), g.id)
                except Exception as e:  # noqa: BLE001
                    log.warning("guild %s sync 실패: %r", g.id, e)
            synced = await tree.sync()
            log.info("synced %d global commands (DM/추후 길드용, 전파 ~1h)", len(synced))
    except Exception as e:  # noqa: BLE001
        _record_error("tree.sync", e)

    # admin 전용 명령(`/admin ...`) — ADMIN_GUILD_ID 설정된 경우만 그 길드에 sync.
    # 메인 tree 와 분리: 다른 길드/DM autocomplete 에 admin 명령이 노출되지 않게 한다.
    agid = admin_guild_id()
    if agid:
        try:
            ag = discord.Object(id=agid)
            admin_mod.build_admin_tree(client, _conn, admin_guild=ag, tree=tree)
            synced = await tree.sync(guild=ag)
            log.info("synced %d admin commands to admin guild %s (포함: main + admin)", len(synced), agid)
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
