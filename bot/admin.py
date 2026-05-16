"""Owner 전용 admin 명령 — `/admin recent | inspect | fetch | reports | resolve | announce`.

가시성: `.env` 의 `ADMIN_GUILD_ID` 가 가리키는 *private* guild 에만 등록(다른 길드/DM 의 autocomplete
에 안 보임). 환경변수 없으면 admin 명령은 어디에도 등록되지 않는다 — `bot/main.py` 의 `on_ready` 가
체크해서 sync 자체를 안 함.

응답 채널: 모든 admin 명령은 *호출 채널엔 ephemeral ack 만* 보내고, 실 결과는 OWNER DM 으로 보낸다.
긴 dump 도 채널 노이즈 없이 비공개로 받기 위함. owner 확인은 `OWNER_USER_ID` 일치만 본다(추가
admin 가능성은 일단 없음 — 필요해지면 list 로 확장).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

# `.json` 파일명에 들어가도 안전한 slug 형식 — engine.slug._SANITIZE_RE 와 같은 charset.
# admin 입력이 path traversal 시도 (`../`) 를 못 하게.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._%-]+$")

import discord
from discord import app_commands

from bot import db, inspector
from bot.config import admin_guild_id, owner_user_id

ANNOUNCE_FOOTER = (
    "공지 끄기: /announce dm:false  ·  "
    "이 채널: /announce channel:false (Manage Channels 권한 필요)"
)
SEND_SLEEP = 0.5

log = logging.getLogger("bot.admin")

# main.py 에서 build_admin_tree(client, conn, dm_owner) 호출 → 등록된 commands 가 들어있는 tree 반환.
# main.py 의 메인 tree 와 분리(동일 tree 에 가드만 다는 방식이면 autocomplete 에 admin 도 노출됨).


def _is_owner(interaction: discord.Interaction) -> bool:
    oid = owner_user_id()
    return bool(oid) and str(interaction.user.id) == oid


async def send_chunked_dm(client: discord.Client, owner_id: str, text: str) -> bool:
    """OWNER 에게 DM. inspector.chunk_for_discord 로 split. 실패 시 False."""
    try:
        user = await client.fetch_user(int(owner_id))
        for chunk in inspector.chunk_for_discord(text):
            await user.send(chunk)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("admin OWNER DM 실패: %r", e)
        return False


def build_admin_tree(client: discord.Client, conn, *, admin_guild: discord.Object,
                     tree: app_commands.CommandTree) -> app_commands.CommandTree:
    """admin 명령들을 main tree 의 `/admin` 그룹으로 등록(guild=admin_guild). 같은 client 에 두 번째
    CommandTree 를 만들면 discord.py 가 거부('This client already has an associated command tree')하므로
    main 의 tree 를 재사용한다. group 자체에 guild kwarg 를 주면 그 guild 의 autocomplete 에만 노출됨."""
    paths = inspector.InspectorPaths.live()

    async def _ack_and_dm(interaction: discord.Interaction, text: str) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        ok = await send_chunked_dm(client, owner_user_id(), text)
        if ok:
            await interaction.edit_original_response(content="✅ 결과를 DM 으로 보냈습니다.")
        else:
            await interaction.edit_original_response(content="⚠️ DM 발송 실패 — 로그 확인.")

    admin = app_commands.Group(name="admin", description="owner 전용 디버그·triage 명령")

    @admin.command(name="recent", description="최근 register 잡 N개 (등록 흐름 추적)")
    @app_commands.describe(count="최근 잡 개수 (기본 20, 최대 50)")
    async def recent(interaction: discord.Interaction, count: app_commands.Range[int, 1, 50] = 20):
        rows = inspector.recent_jobs(conn, limit=int(count))
        await _ack_and_dm(interaction, inspector.format_recent_jobs(rows))

    @admin.command(name="reports", description="사용자 신고 목록")
    @app_commands.describe(status="필터: open(기본) / resolved / all")
    @app_commands.choices(status=[
        app_commands.Choice(name="open", value="open"),
        app_commands.Choice(name="resolved", value="resolved"),
        app_commands.Choice(name="all", value="all"),
    ])
    async def reports(interaction: discord.Interaction,
                      status: Optional[app_commands.Choice[str]] = None):
        s = status.value if status else "open"
        rows = db.list_reports(conn, status=None if s == "all" else s, limit=50)
        rd = [dict(r) for r in rows]
        await _ack_and_dm(interaction, inspector.format_reports(rd))

    @admin.command(name="inspect", description="구독·잡·config·state 통합 dump + 자동 진단")
    @app_commands.describe(
        job_id="(택1) jobs.id",
        report_id="(택1) reports.id",
        user_id="(택1) discord user id (slug 와 같이 줘야 함)",
        slug="(택1) slug (user_id 와 같이 또는 단독)",
    )
    async def inspect_cmd(interaction: discord.Interaction,
                          job_id: Optional[int] = None,
                          report_id: Optional[int] = None,
                          user_id: Optional[str] = None,
                          slug: Optional[str] = None):
        if all(x is None for x in (job_id, report_id, user_id, slug)):
            # any() 는 0 을 falsy 로 봐 job_id=0 같은 경계에서 잘못된 안내가 가능 — None 으로 엄격 비교.
            await interaction.response.send_message(
                "❌ job_id / report_id / user_id / slug 중 하나는 필요.", ephemeral=True)
            return
        result = inspector.inspect(conn, paths, job_id=job_id, report_id=report_id,
                                   user_id=user_id, slug=slug)
        if result is None:
            await interaction.response.send_message("❌ 일치하는 항목 없음.", ephemeral=True)
            return
        await _ack_and_dm(interaction, inspector.format_inspect_result(result))

    @admin.command(name="fetch", description="현 config 로 fetch_list 돌려 top N 결과 + 진단 갱신")
    @app_commands.describe(slug="조회할 slug", count="가져올 개수 (기본 5, 최대 20)")
    async def fetch_cmd(interaction: discord.Interaction, slug: str,
                        count: app_commands.Range[int, 1, 20] = 5):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        result = inspector.inspect(conn, paths, slug=slug)
        if result is None:
            await interaction.edit_original_response(content="❌ 일치하는 slug 없음.")
            return
        try:
            sample = await inspector.fetch_sim(paths, slug, n=int(count))
        except Exception as e:  # noqa: BLE001
            await interaction.edit_original_response(content=f"⚠️ fetch_sim 예외: {e!r}")
            return
        if sample is None:
            await interaction.edit_original_response(content="❌ config 없음 — fetch 못 함.")
            return
        inspector.update_with_fetch_sample(result, conn, paths, sample)
        ok = await send_chunked_dm(client, owner_user_id(), inspector.format_inspect_result(result))
        await interaction.edit_original_response(
            content="✅ 결과를 DM 으로 보냈습니다." if ok else "⚠️ DM 발송 실패.")

    @admin.command(name="resolve", description="신고를 해결로 표시")
    @app_commands.describe(report_id="reports.id", note="해결 메모(선택)")
    async def resolve_cmd(interaction: discord.Interaction, report_id: int,
                          note: Optional[str] = None):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        ok = db.resolve_report(conn, report_id, note)
        if ok:
            await interaction.response.send_message(
                f"✅ 신고 #{report_id} resolved.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ 신고 #{report_id} 가 없거나 이미 resolved.", ephemeral=True)

    @admin.command(name="reject", description="이 slug 의 자동 등록을 영구 거부 마커로 박음")
    @app_commands.describe(slug="거부할 slug", reason="거부 사유(짧게)", note="(선택) 자세한 메모")
    async def reject_cmd(interaction: discord.Interaction, slug: str, reason: str,
                         note: Optional[str] = None):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        if not _SLUG_RE.fullmatch(slug):
            await interaction.response.send_message(
                f"❌ slug 형식 오류 (영문/숫자/._%- 만): `{slug}`", ephemeral=True)
            return
        from scripts.register import _save_rejected  # lazy — import 시 sys.path 영향 회피
        sub_row = conn.execute(
            "SELECT url FROM subscriptions WHERE slug=? ORDER BY created_at DESC LIMIT 1",
            (slug,)).fetchone()
        url = sub_row["url"] if sub_row else "(미상)"
        p = _save_rejected(slug, url, reason, note=note)
        await interaction.response.send_message(
            f"✅ `{slug}` 거부 마커 박힘.\n• reason: {reason}\n• note: {note or '없음'}\n"
            f"• marker: `{p.name}`\n이후 같은 slug `/preview`·`/watch` 시 거부 응답.",
            ephemeral=True)

    @admin.command(name="unreject", description="거부 마커 제거 (실수 복구).")
    @app_commands.describe(slug="거부 해제할 slug")
    async def unreject_cmd(interaction: discord.Interaction, slug: str):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        if not _SLUG_RE.fullmatch(slug):
            await interaction.response.send_message(
                f"❌ slug 형식 오류 (영문/숫자/._%- 만): `{slug}`", ephemeral=True)
            return
        from scripts.register import _clear_rejected
        ok = _clear_rejected(slug)
        msg = (f"✅ `{slug}` 거부 마커 제거됨." if ok
               else f"❌ `{slug}` 거부 마커가 없음.")
        await interaction.response.send_message(msg, ephemeral=True)

    @admin.command(name="learned", description="자동 학습된 거부 패턴 목록 (host+path_prefix 단위).")
    async def learned_cmd(interaction: discord.Interaction):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        from scripts.register import _list_learned
        patterns = _list_learned()
        if not patterns:
            await interaction.response.send_message("학습된 거부 패턴 없음.", ephemeral=True)
            return
        # 최근 거부 시각 내림차순.
        patterns_sorted = sorted(patterns,
                                 key=lambda p: str(p.get("last_rejected_at") or ""),
                                 reverse=True)
        lines = [f"**학습된 거부 패턴 ({len(patterns_sorted)}건)**"]
        for p in patterns_sorted[:50]:
            pid = (p.get("id") or "")[:12]
            host = p.get("host_suffix") or "(없음)"
            pp = p.get("path_prefix") or "(빈 path)"
            cnt = p.get("reject_count") or 0
            last_ts = (p.get("last_rejected_at") or "")[:16]
            reason = (p.get("last_reason") or "").replace("\n", " ")
            if len(reason) > 60:
                reason = reason[:60] + "…"
            lines.append(f"- `{pid}` `{host}{pp}` · count={cnt} · {last_ts}\n   {reason}")
        if len(patterns_sorted) > 50:
            lines.append(f"_(처음 50건만 표시 — 전체 {len(patterns_sorted)}건)_")
        await _ack_and_dm(interaction, "\n".join(lines))

    @admin.command(name="unlearn", description="학습된 거부 패턴을 풀어줌 (false positive 복구).")
    @app_commands.describe(pattern_id="`/admin learned` 의 id (12자 hash)")
    async def unlearn_cmd(interaction: discord.Interaction, pattern_id: str):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        pat_id = pattern_id.strip().lower()
        if not re.fullmatch(r"[a-f0-9]{1,12}", pat_id):
            await interaction.response.send_message(
                f"❌ pattern_id 형식 오류 (소문자 16진 1~12자): `{pattern_id}`", ephemeral=True)
            return
        from scripts.register import _clear_learned_by_id
        ok = _clear_learned_by_id(pat_id)
        msg = (f"✅ 학습 패턴 `{pat_id}` 제거됨 — 이후 같은 host+path_prefix URL 은 다시 자동 거부 안 됨."
               if ok else f"❌ pattern_id `{pat_id}` 못 찾음. `/admin learned` 로 확인.")
        await interaction.response.send_message(msg, ephemeral=True)

    @admin.command(name="triage", description="처리 대기 backlog 요약 (신고/깨짐/실패/큐/의견).")
    async def triage_cmd(interaction: discord.Interaction):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        summary = inspector.triage_summary(conn, paths)
        await _ack_and_dm(interaction, inspector.format_triage(summary))

    @admin.command(name="feedback", description="사용자가 보낸 자유 의견 목록.")
    @app_commands.describe(count="최근 개수 (기본 10, 최대 50)")
    async def feedback_list_cmd(interaction: discord.Interaction,
                                count: app_commands.Range[int, 1, 50] = 10):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        rows = db.list_feedback(conn, limit=int(count))
        if not rows:
            await interaction.response.send_message("의견 없음.", ephemeral=True)
            return
        out_lines = [f"**의견 목록 ({len(rows)}건)**"]
        for r in rows:
            ts = (r["created_at"] or "")[:16]
            user = r["username"] or r["user_id"]
            preview = (r["message"] or "").replace("\n", " ")
            if len(preview) > 200:
                preview = preview[:200] + "…"
            out_lines.append(f"- #{r['id']} `{user}` · {ts}\n   {preview}")
        await _ack_and_dm(interaction, "\n".join(out_lines))

    @admin.command(name="announce", description="봇 공지 발송 — preview 후 버튼으로 확인 발송.")
    @app_commands.describe(
        message="공지 본문 (markdown 허용, 최대 ~4000자)",
        title="공지 제목 (기본: '📢 봇 업데이트', 최대 256자)",
    )
    async def announce_cmd(interaction: discord.Interaction, message: str,
                           title: Optional[str] = None):
        if not _is_owner(interaction):
            await interaction.response.send_message("❌ owner 전용 명령입니다.", ephemeral=True)
            return
        title_s = (title or "📢 봇 업데이트").strip()[:256]
        # discord slash 입력창은 Enter 가 제출이라 줄바꿈 입력 불가. literal `\n` (2글자) 를 실제 newline 으로 변환.
        message_s = message.strip().replace("\\n", "\n")
        if not message_s:
            await interaction.response.send_message("❌ message 가 비어있습니다.", ephemeral=True)
            return
        message_s = message_s[:4000]  # embed description 4096 한계 — footer 여유 96자
        dm_targets = db.announce_recipients_dm(conn)
        ch_targets = db.announce_recipients_channel(conn)
        embed = _build_announce_embed(title_s, message_s)
        view = AnnounceConfirmView(
            client=client, conn=conn, title=title_s, message=message_s,
            dm_targets=dm_targets, ch_targets=ch_targets,
            sent_by_id=str(interaction.user.id),
        )
        await interaction.response.send_message(
            content=f"**프리뷰** — 발송 대상: DM **{len(dm_targets)}명** · 채널 **{len(ch_targets)}개**",
            embed=embed, view=view, ephemeral=True,
        )

    tree.add_command(admin, guild=admin_guild)
    return tree


# --------------------------------------------------------------------------- #
# 공지 — embed builder · 발송 view (Button confirm)
# --------------------------------------------------------------------------- #
def _build_announce_embed(title: str, message: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=message, color=0x5865F2)
    embed.set_footer(text=ANNOUNCE_FOOTER)
    return embed


class AnnounceConfirmView(discord.ui.View):
    """Owner 전용 confirm view — 60s timeout. 버튼 1회만 동작 (재클릭/타임아웃 후 disable)."""

    def __init__(self, *, client: discord.Client, conn,
                 title: str, message: str,
                 dm_targets: list[str], ch_targets: list[str],
                 sent_by_id: str, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.client = client
        self.conn = conn
        self.title = title
        self.message = message
        self.dm_targets = dm_targets
        self.ch_targets = ch_targets
        self.sent_by_id = sent_by_id
        self._used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.sent_by_id:
            await interaction.response.send_message(
                "❌ 이 confirm 은 호출자만 누를 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="발송", style=discord.ButtonStyle.danger)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._used:
            await interaction.response.send_message("이미 처리됨.", ephemeral=True)
            return
        self._used = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="📤 발송 중… (DM/채널 발송 결과는 OWNER DM 으로)", view=self)
        task = asyncio.create_task(self._do_send())
        task.add_done_callback(self._on_send_done)

    def _on_send_done(self, task: "asyncio.Task") -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc is None:
            return
        import traceback as _tb
        tb = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        log.error("announce _do_send 예외: %s\n%s", exc, tb)
        # owner 한테 별도 알림 — 봇 종료 중이면 event loop 가 닫혀 RuntimeError. 그땐 로그만.
        try:
            asyncio.create_task(send_chunked_dm(
                self.client, self.sent_by_id,
                f"⚠️ 공지 발송 중 예외 — `{type(exc).__name__}: {exc}`\n```\n{tb[-1500:]}\n```"))
        except RuntimeError as re:
            log.warning("_on_send_done DM task 생성 실패(loop 종료?): %r", re)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._used:
            await interaction.response.send_message("이미 처리됨.", ephemeral=True)
            return
        self._used = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🛑 발송 취소됨.", view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

    async def _do_send(self) -> None:
        ann_id = db.add_announcement(
            self.conn, title=self.title, message=self.message, sent_by=self.sent_by_id)
        embed = _build_announce_embed(self.title, self.message)
        dm_sent = dm_failed = ch_sent = ch_failed = 0
        dm_fail_log: list[str] = []
        ch_fail_log: list[str] = []

        try:
            for uid in self.dm_targets:
                try:
                    user = await self.client.fetch_user(int(uid))
                    await user.send(embed=embed)
                    dm_sent += 1
                except Exception as e:  # noqa: BLE001
                    dm_failed += 1
                    dm_fail_log.append(f"  user {uid}: {type(e).__name__}: {e}")
                    log.warning("announce DM 실패 user=%s: %r", uid, e)
                await asyncio.sleep(SEND_SLEEP)

            for cid in self.ch_targets:
                try:
                    ch = self.client.get_channel(int(cid)) or await self.client.fetch_channel(int(cid))
                    await ch.send(embed=embed)
                    ch_sent += 1
                except Exception as e:  # noqa: BLE001
                    ch_failed += 1
                    ch_fail_log.append(f"  channel {cid}: {type(e).__name__}: {e}")
                    log.warning("announce channel 실패 channel=%s: %r", cid, e)
                await asyncio.sleep(SEND_SLEEP)
        finally:
            # partial 실패(예외/cancel) 에도 지금까지 누적된 카운트는 영속 — 0 카운트 row 방지.
            db.update_announcement_counts(
                self.conn, ann_id, dm_sent=dm_sent, dm_failed=dm_failed,
                channel_sent=ch_sent, channel_failed=ch_failed)

        report = [
            f"📊 공지 #{ann_id} 발송 완료",
            f"• 제목: {self.title}",
            f"• DM: {dm_sent}/{len(self.dm_targets)} 성공  ·  실패 {dm_failed}",
            f"• 채널: {ch_sent}/{len(self.ch_targets)} 성공  ·  실패 {ch_failed}",
        ]
        if dm_fail_log:
            report.append("\nDM 실패 상세:\n" + "\n".join(dm_fail_log[:20]))
        if ch_fail_log:
            report.append("\n채널 실패 상세:\n" + "\n".join(ch_fail_log[:20]))
        ok = await send_chunked_dm(self.client, self.sent_by_id, "\n".join(report))
        if not ok:
            # OWNER DM 실패 — counts 는 DB 에 이미 commit 됨. 로그에라도 남김.
            log.warning("announce #%s 결과 OWNER DM 발송 실패 — counts: DM %d/%d ch %d/%d",
                        ann_id, dm_sent, len(self.dm_targets), ch_sent, len(self.ch_targets))
