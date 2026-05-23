"""dev mode 의 tree.copy_global_to(guild=g) 가 등록한 guild-scope 명령을 dev guild 에서 *삭제* 하는 1회용 script.

이유: dev mode (on_ready 의 GUILD_ID 분기) 가 copy_global_to + sync(guild=g) 하면 guild-scope 명령
이 생기는데, 그 후 production 분기로 돌아가 global sync 만 해도 admin guild 의 guild-scope 명령은
clear 분기에서 제외되어 *영구* 남는다. 결과: dev guild 의 사용자에게 같은 이름 명령이 두 번 보임
(guild-scope + global).

해결: 이 script 1회 실행 → guild-scope user commands 전부 clear. admin commands 는 N100 봇 startup 시 build_admin_tree 가 다시 sync.

사용: python scripts/clear_dev_guild_commands.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord
from discord import app_commands

from bot.config import bot_token, guild_id, admin_guild_id


async def main() -> int:
    tok = bot_token()
    if not tok:
        print("[ERROR] BOT_TOKEN 없음")
        return 2
    target = guild_id() or admin_guild_id()
    if not target:
        print("[ERROR] GUILD_ID 도 ADMIN_GUILD_ID 도 없음 — clear 할 길드 모름")
        return 2

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    done = asyncio.Event()

    @client.event
    async def on_ready():
        g = discord.Object(id=target)
        tree.clear_commands(guild=g)
        synced = await tree.sync(guild=g)
        print(f"[clear] guild {target}: {len(synced)} 명령 남음 (0 이면 깨끗)")
        done.set()

    task = asyncio.create_task(client.start(tok))
    try:
        await asyncio.wait_for(done.wait(), timeout=30)
    except asyncio.TimeoutError:
        print("[ERROR] 30초 안에 on_ready 안 옴")
        return 1
    await client.close()
    try:
        await task
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
