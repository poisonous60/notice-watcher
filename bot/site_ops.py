"""봇 + worker 공통 헬퍼 — register.py subprocess 실행, 사이트 상태 조회, 예시 알림 생성.

main.py 와 worker.py 가 둘 다 사용. 순환 import 방지용으로 분리.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"
TRIAGE_QUEUE = ROOT / "output" / "triage_queue.jsonl"
REGISTER_PY = ROOT / "scripts" / "register.py"
PY = sys.executable

log = logging.getLogger("bot.site_ops")

# lazy import — module-level import 하면 discord/asyncio 진입 전 무거운 chunk 가 로드되어 봇 start-up 느려짐
from scripts._chromium_lock import chromium_lock  # noqa: E402
from scripts.notify import format_message, summarize_post  # noqa: E402
from engine import load_config, make_adapter  # noqa: E402
from generate import client_for  # noqa: E402
from bot.runtime_config import settings  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# 사이트 상태 조회
# --------------------------------------------------------------------------- #
def config_path_for(slug: str) -> Optional[Path]:
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


def is_registered(slug: str) -> bool:
    return (STATE_DIR / f"{slug}.json").exists() and not (STATE_DIR / f"{slug}.FAILED.json").exists()


def baseline_count(slug: str) -> Optional[int]:
    st = STATE_DIR / f"{slug}.json"
    try:
        return int(json.loads(st.read_text(encoding="utf-8")).get("n_baseline", 0))
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# register.py subprocess (chromium 락 안에서; 호출자는 워커 스레드에서 to_thread 로 부른다)
# --------------------------------------------------------------------------- #
def blocking_register(url: str, article_url: Optional[str] = None) -> tuple[int, str]:
    """register.py 를 chromium 락 안에서 실행. (rc, last_~4000 chars of stdout/stderr).
    timeout 들은 settings.chromium_lock 에서 (config.toml).

    부모 trace (worker 의 probe trace) 가 있으면 env 로 trace_id 를 register.py 에 전달 →
    register.py 의 inner spans 이 같은 trace_id 안에 append.
    """
    import os
    from engine.tracing import env_for_child
    cmd = [PY, "-u", str(REGISTER_PY), url]
    if article_url:
        cmd += ["--article-url", article_url]
    child_env = {**os.environ, **env_for_child()}
    try:
        with chromium_lock(timeout=settings.chromium_lock.bot_timeout):
            proc = subprocess.Popen(cmd, cwd=str(ROOT),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", bufsize=1,
                                    env=child_env)
            timed_out = threading.Event()

            def _kill_on_timeout() -> None:
                if proc.poll() is None:
                    timed_out.set()
                    proc.kill()

            killer = threading.Timer(settings.chromium_lock.register_subprocess_timeout, _kill_on_timeout)
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
            log.info("register.py 종료: rc=%s%s (%s)", rc,
                     " (타임아웃 kill)" if timed_out.is_set() else "", url)
        if timed_out.is_set():
            return -2, f"register.py 실행 시간 초과 ({int(settings.chromium_lock.register_subprocess_timeout)}s)"
        return rc, "\n".join(tail)[-4000:]
    except TimeoutError as e:
        return -1, f"chromium 락 대기 초과: {e}"
    except Exception as e:  # noqa: BLE001
        return -3, f"register.py 실행 중 예외: {e!r}"


def append_triage_queue(url: str, slug: str, via: str,
                        requested_by: Optional[dict], note: str) -> None:
    """자동 등록 실패를 output/triage_queue.jsonl 에 한 줄 append. scripts/triage.py 가 읽음."""
    try:
        TRIAGE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now_iso(), "url": url, "slug": slug, "via": via,
               "requested_by": requested_by or {}, "register_tail": (note or "")[-2000:]}
        with TRIAGE_QUEUE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log.warning("triage_queue 기록 실패 (%s): %r", slug, e)


# --------------------------------------------------------------------------- #
# 예시 알림 생성 (등록 직후 사용자에게 미리보기)
# --------------------------------------------------------------------------- #
async def make_example(slug: str) -> Optional[str]:
    cfg_path = config_path_for(slug)
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
        summary = await asyncio.to_thread(summarize_post, client_for("notify_summarize"), post_dict, slug=slug)
        return format_message(post_dict, summary)
    except Exception as e:  # noqa: BLE001
        log.warning("예시 생성 실패 (%s): %r", slug, e)
        return None


# --------------------------------------------------------------------------- #
# Discord 메시지 edit (interaction token 만료와 무관 — 채널 메시지 직접 edit)
# --------------------------------------------------------------------------- #
async def edit_channel_message(client, channel_id: Optional[str], message_id: Optional[str],
                               content: str) -> bool:
    """봇이 보낸 채널 메시지를 edit. interaction token 만료(15분)와 무관해서 큐 대기가 길어도 OK.
    실패 시 False (메시지 삭제·권한 등). 호출자는 fallback (DM 등) 고려."""
    if not channel_id or not message_id:
        return False
    try:
        ch = client.get_channel(int(channel_id))
        if ch is None:
            ch = await client.fetch_channel(int(channel_id))
        msg = await ch.fetch_message(int(message_id))
        await msg.edit(content=content[:1900])
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("ack 메시지 edit 실패 (ch=%s, msg=%s): %r", channel_id, message_id, e)
        return False
