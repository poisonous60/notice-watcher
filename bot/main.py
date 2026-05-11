"""Discord 봇 — 게시판 등록(/watch) · 미리보기(/preview) · 목록(/list) · 해제(/unwatch) · 상태(/status).

- 게이트웨이 연결(아웃바운드만 — 포트포워딩 불필요). 슬래시 명령 *수신* 용.
- `/watch`·`/preview`(처음 보는 사이트) 는 register.py 를 subprocess 로 실행(chromium 락 안에서, 워커 스레드). >3s 걸리므로 즉시 defer 응답 후 수정.
  register.py 의 stdout/stderr 는 `[register] …` 로 봇 로그에 실시간 흘러나감 → `journalctl --user-unit notice-bot.service -f` 로 config 생성 과정 관전 가능.
- 구독 정보(필터·스케줄·발송대상)는 SQLite(output/bot.sqlite3, bot/db.py)에만 — configs/·poll_state/ 엔 안 씀.
- 실제 알림 발송은 polling 쪽(scripts/notify.py)이 봇 토큰으로 REST 직접 — 이 봇 프로세스가 떠 있을 필요 없음.
- 미처리 예외는 로그 + OWNER_USER_ID 에게 DM(쿨다운).

실행: python -m bot.main      (env: BOT_TOKEN 필수, OWNER_USER_ID/GUILD_ID 선택; .env 도 읽음)
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import discord  # noqa: E402
from discord import app_commands  # noqa: E402

from bot import db  # noqa: E402
from bot.config import bot_token, owner_user_id, guild_id  # noqa: E402
from scripts._chromium_lock import chromium_lock  # noqa: E402
from scripts.notify import format_message, summarize_post  # noqa: E402
from probe.paths import url_to_slug  # noqa: E402
from engine import load_config, make_adapter  # noqa: E402
from generate import GeminiClient, GeminiError  # noqa: E402

CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"
TRIAGE_QUEUE = ROOT / "output" / "triage_queue.jsonl"  # 자동 등록 실패한 /preview·/watch 기록 (scripts/triage.py 가 읽음)
REGISTER_PY = ROOT / "scripts" / "register.py"
PY = sys.executable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

_SCHEDULE_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_HOUR_RE = re.compile(r"^([01]?\d|2[0-3])$")

START_TS = time.time()
LAST_ERROR: dict = {"when": None, "text": None}
_OWNER_DM_COOLDOWN: dict[str, float] = {}

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_conn = db.connect()
_gemini: Optional[GeminiClient] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gemini_client() -> GeminiClient:
    global _gemini
    if _gemini is None:
        _gemini = GeminiClient()
    return _gemini


def _config_path_for(slug: str) -> Optional[Path]:
    st = STATE_DIR / f"{slug}.json"
    if st.exists():
        try:
            cp = json.loads(st.read_text(encoding="utf-8")).get("config_path")
            if cp and Path(cp).exists():
                return Path(cp)
        except Exception:  # noqa: BLE001
            pass
    default = CONFIGS_DIR / f"{slug}.json"
    return default if default.exists() else None


def _is_registered(slug: str) -> bool:
    return (STATE_DIR / f"{slug}.json").exists() and not (STATE_DIR / f"{slug}.FAILED.json").exists()


def _baseline_count(slug: str) -> Optional[int]:
    st = STATE_DIR / f"{slug}.json"
    try:
        return int(json.loads(st.read_text(encoding="utf-8")).get("n_baseline", 0))
    except Exception:  # noqa: BLE001
        return None


def _parse_schedule(raw: Optional[str]) -> Optional[str]:
    """'realtime' | 'HH:MM' | 'HH' → 정규화. 잘못된 값이면 None."""
    if not raw:
        return "realtime"
    s = raw.strip().lower()
    if s in ("realtime", "rt", "즉시", "실시간"):
        return "realtime"
    s = raw.strip()
    if _SCHEDULE_RE.match(s):
        h, m = s.split(":")
        return f"{int(h):02d}:{m}"
    if _HOUR_RE.match(s):
        return f"{int(s):02d}:00"
    return None


# --------------------------------------------------------------------------- #
# register.py subprocess (chromium 락 안에서, 워커 스레드)
# --------------------------------------------------------------------------- #
def _blocking_register(url: str) -> tuple[int, str]:
    """register.py 를 chromium 락 안에서 실행.
    stdout/stderr 를 줄 단위로 봇 로그(`[register] …`)에 흘려보냄 → N100 콘솔에서
    `journalctl --user-unit notice-bot.service -f` 로 config 생성 과정 실시간 확인 가능.
    실패 시 Discord 에 보여줄 마지막 ~4000자는 따로 모아 반환. (-u: 자식 출력 버퍼링 끔)"""
    try:
        with chromium_lock(timeout=900.0):
            proc = subprocess.Popen([PY, "-u", str(REGISTER_PY), url], cwd=str(ROOT),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", bufsize=1)
            timed_out = threading.Event()

            def _kill_on_timeout() -> None:
                if proc.poll() is None:
                    timed_out.set()
                    proc.kill()

            killer = threading.Timer(600.0, _kill_on_timeout)
            killer.start()
            tail: "collections.deque[str]" = collections.deque(maxlen=400)
            log.info("register.py 시작: %s", url)
            try:
                for line in (proc.stdout or []):
                    s = line.rstrip("\n")
                    tail.append(s)
                    log.info("[register] %s", s)
                rc = proc.wait()
            finally:
                killer.cancel()
            log.info("register.py 종료: rc=%s%s (%s)", rc, " (타임아웃 kill)" if timed_out.is_set() else "", url)
        if timed_out.is_set():
            return -2, "register.py 실행 시간 초과 (10분)"
        return rc, "\n".join(tail)[-4000:]
    except TimeoutError as e:  # chromium 락 못 잡음
        return -1, f"chromium 락 대기 초과: {e}"
    except Exception as e:  # noqa: BLE001
        return -3, f"register.py 실행 중 예외: {e!r}"


def _append_triage_queue(url: str, slug: str, via: str, requested_by: Optional[dict], note: str) -> None:
    """자동 등록 실패를 output/triage_queue.jsonl 에 한 줄 append.
    나중에 dev박스에서 `python scripts/triage.py pull/list` 로 보고 hand-config 스킬로 처리한다.
    (register.py 가 쓰는 <slug>.FAILED.json 에 [FAIL] 사유·last_config 가 있고, 이쪽은 누가/어떤 명령으로 실패했는지.)"""
    try:
        TRIAGE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": _now_iso(), "url": url, "slug": slug, "via": via,
               "requested_by": requested_by or {}, "register_tail": (note or "")[-2000:]}
        with TRIAGE_QUEUE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("triage_queue 기록 실패 (%s): %r", slug, e)


async def _ensure_registered(url: str, *, via: str = "?", requested_by: Optional[dict] = None) -> tuple[bool, str, str]:
    """등록돼 있으면 그대로, 아니면 register.py 실행. 반환 (ok, slug, msg).
    via/requested_by 는 실패 시 triage_queue.jsonl 에 남길 맥락(어떤 명령/누가)."""
    slug = url_to_slug(url)
    if _is_registered(slug):
        return True, slug, "이미 등록됨"
    rc, out = await asyncio.to_thread(_blocking_register, url)
    if rc == 0 and _is_registered(slug):
        return True, slug, "등록 완료"
    if rc == -1:
        return False, slug, "다른 작업이 크롤러를 쓰는 중입니다. 잠시 후 다시 시도해 주세요."
    if rc == -2:
        _append_triage_queue(url, slug, via, requested_by, "TIMEOUT — register.py 10분 초과")
        return False, slug, "사이트 분석 시간 초과(10분) — 너무 느리거나 막힌 사이트일 수 있습니다."
    # 그 외: 자동 등록 실패
    tail = "\n".join((out or "").strip().splitlines()[-6:])
    _append_triage_queue(url, slug, via, requested_by, tail)
    return False, slug, ("이 사이트는 자동 등록이 안 됩니다 — 손어댑터가 필요합니다 "
                         "(docs/사이트 어댑터 추가 가이드.md).\n```\n" + tail + "\n```")


# --------------------------------------------------------------------------- #
# 예시 1건 생성 (config 로드 → fetch_list → fetch_article → 요약 → format_message)
# --------------------------------------------------------------------------- #
async def _make_example(slug: str) -> Optional[str]:
    cfg_path = _config_path_for(slug)
    if not cfg_path:
        return None
    try:
        cfg = load_config(cfg_path)
        async with make_adapter(cfg) as a:
            posts = await a.fetch_list(page=1, page_size=10)
            if not posts:
                return None
            try:
                full = await a.fetch_article(posts[0])
            except Exception:  # noqa: BLE001
                full = posts[0]
        post_dict = full.to_dict()
        summary = await asyncio.to_thread(summarize_post, _gemini_client(), post_dict)
        return format_message(post_dict, summary)
    except (GeminiError, Exception) as e:  # noqa: BLE001
        log.warning("예시 생성 실패 (%s): %r", slug, e)
        return None


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
    schedule="(선택) 'realtime'(기본, 폴링 때마다 바로) 또는 'HH:MM'/'HH'(매일 그 시각에 하루치 모아서, KST)",
    here="(선택) 켜면 이 채널에 발송. 끄면(기본) 내 DM 으로.",
    notify_empty="(선택) 켜면 폴링했는데 새 글이 없을 때도 '새 공지 없음' 한 줄을 보냄. 끄면(기본) 새 글 있을 때만. realtime 일 때만 동작.",
)
async def watch(interaction: discord.Interaction, url: str, filter: Optional[str] = None,
                schedule: Optional[str] = "realtime", here: bool = False, notify_empty: bool = False):
    await interaction.response.defer(thinking=True)
    sched = _parse_schedule(schedule)
    if sched is None:
        await interaction.edit_original_response(
            content="❌ schedule 형식 오류 — 'realtime' 또는 'HH:MM'(예: 09:00) / 'HH'(예: 9) 로 적어주세요.")
        return
    if notify_empty and sched != "realtime":
        await interaction.edit_original_response(
            content="❌ notify_empty(새 공지 없음 알림)는 schedule='realtime' 일 때만 돼요. 다이제스트 모드에선 못 켭니다.")
        return
    if not re.match(r"^https?://", url.strip()):
        await interaction.edit_original_response(content="❌ http(s):// 로 시작하는 URL 을 주세요.")
        return

    await interaction.edit_original_response(content="⏳ 사이트 분석 중… (처음 보는 사이트면 수 분 걸릴 수 있어요)")
    ok, slug, msg = await _ensure_registered(
        url.strip(), via="watch",
        requested_by={"id": str(interaction.user.id), "name": str(interaction.user)})
    if not ok:
        await interaction.edit_original_response(content=f"⚠️ {msg}")
        return

    target_kind = "channel" if here else "dm"
    target_id = str(interaction.channel_id) if here else str(interaction.user.id)
    db.add_subscription(_conn, user_id=str(interaction.user.id), slug=slug, url=url.strip(),
                        filter_prompt=(filter.strip() if filter and filter.strip() else None),
                        schedule=sched, target_kind=target_kind, target_id=target_id,
                        notify_empty=notify_empty)
    n = _baseline_count(slug)
    where = "이 채널" if here else "내 DM"
    head = (f"✅ 등록 완료 — `{slug}`\n"
            f"• baseline {n if n is not None else '?'}건(이 글들은 '새 글' 아님)\n"
            f"• 필터: {filter.strip() if filter and filter.strip() else '없음(새 글 전부)'}\n"
            f"• 스케줄: {sched}\n"
            f"• 알림: {where}\n"
            f"• 새 글 없을 때도 알림: {'예' if notify_empty else '아니오'}")
    await interaction.edit_original_response(content=head + "\n\n📋 예시 알림 만드는 중…")
    example = await _make_example(slug)
    if example:
        await interaction.edit_original_response(content=head + "\n\n📋 **예시 알림** (이런 형식으로 옵니다):\n" + example)
    else:
        await interaction.edit_original_response(content=head + "\n\n(예시 알림 생성은 건너뜀 — 등록은 정상)")


@tree.command(name="preview", description="등록 없이 그 게시판의 최신 글 하나를 요약해 알림 예시를 보여줍니다.")
@app_commands.describe(url="공지/게시판 목록 페이지 URL")
async def preview(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    if not re.match(r"^https?://", url.strip()):
        await interaction.edit_original_response(content="❌ http(s):// 로 시작하는 URL 을 주세요.")
        return
    slug = url_to_slug(url.strip())
    if not _is_registered(slug):
        await interaction.edit_original_response(content="⏳ config 생성 중… (이 사이트는 처음이라 수 분 걸려요)")
        ok, slug, msg = await _ensure_registered(
            url.strip(), via="preview",
            requested_by={"id": str(interaction.user.id), "name": str(interaction.user)})
        if not ok:
            await interaction.edit_original_response(content=f"⚠️ {msg}")
            return
    await interaction.edit_original_response(content="⏳ 최신 글 가져와 요약 중…")
    example = await _make_example(slug)
    if example:
        await interaction.edit_original_response(content="📋 **이 게시판 알림 예시:**\n" + example)
    else:
        await interaction.edit_original_response(content="⚠️ 예시를 만들지 못했어요(목록이 비었거나 본문 추출 실패).")


@tree.command(name="unwatch", description="구독 해제. slug 또는 URL 을 줍니다.")
@app_commands.describe(target="해제할 구독의 slug, 또는 등록할 때 쓴 URL")
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
        lines.append(f"• `{r['slug']}` — 필터: {r['filter_prompt'] or '없음'} — 스케줄: {r['schedule']} — {where}{ne} — 등록 {r['created_at'][:10]}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@tree.command(name="status", description="봇/폴링 상태")
async def status(interaction: discord.Interaction):
    cnt = db.counts(_conn)
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
    lines = [
        "**봇 상태**",
        f"• uptime: {up // 3600}h {(up % 3600) // 60}m",
        f"• 등록 config: {n_configs}개 / 구독: {cnt['subscriptions']}건 ({cnt['slugs']} slug) / pending(다이제스트 대기): {cnt['pending']}건",
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


def main() -> int:
    tok = bot_token()
    if not tok:
        print("[ERROR] BOT_TOKEN 이 없습니다. .env 또는 환경변수에 설정하세요.", file=sys.stderr)
        return 2
    client.run(tok, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
