"""Owner 전용 admin 명령 — `/admin recent | inspect | fetch | reports | resolve`.

가시성: `.env` 의 `ADMIN_GUILD_ID` 가 가리키는 *private* guild 에만 등록(다른 길드/DM 의 autocomplete
에 안 보임). 환경변수 없으면 admin 명령은 어디에도 등록되지 않는다 — `bot/main.py` 의 `on_ready` 가
체크해서 sync 자체를 안 함.

응답 채널: 모든 admin 명령은 *호출 채널엔 ephemeral ack 만* 보내고, 실 결과는 OWNER DM 으로 보낸다.
긴 dump 도 채널 노이즈 없이 비공개로 받기 위함. owner 확인은 `OWNER_USER_ID` 일치만 본다(추가
admin 가능성은 일단 없음 — 필요해지면 list 로 확장).
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from bot import db, inspector
from bot.config import admin_guild_id, owner_user_id

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


def build_admin_tree(client: discord.Client, conn, *, admin_guild: discord.Object) -> app_commands.CommandTree:
    """admin 전용 CommandTree 를 만들어 반환. main.py 가 admin_guild 에 sync.
    admin tree 는 main tree 와 별개 — main tree 의 `on_app_command_error` 핸들러를 못 받으므로
    여기서 자체 에러 핸들러를 등록한다(미등록 시 admin 명령 실행 중 예외가 owner 모르게 사라짐)."""
    tree = app_commands.CommandTree(client)
    paths = inspector.InspectorPaths.live()

    @tree.error
    async def _admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        import traceback
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        log.error("admin 명령 예외: %s\n%s", error, tb)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content=f"⚠️ admin 명령 처리 중 오류: `{type(error).__name__}: {error}`")
            else:
                await interaction.response.send_message(
                    f"⚠️ admin 명령 처리 중 오류: `{type(error).__name__}: {error}`", ephemeral=True)
        except Exception:  # noqa: BLE001
            pass
        oid = owner_user_id()
        if oid and oid.isdigit():
            await send_chunked_dm(client, oid, f"[admin 에러] `{type(error).__name__}: {error}`\n```\n{tb[-1500:]}\n```")

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

    tree.add_command(admin, guild=admin_guild)
    return tree
