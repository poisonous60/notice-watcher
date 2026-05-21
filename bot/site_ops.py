"""봇 + worker 공통 헬퍼 — register.py subprocess 실행, 사이트 상태 조회, 예시 알림 생성.

main.py 와 worker.py 가 둘 다 사용. 순환 import 방지용으로 분리.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
STATE_DIR = ROOT / "output" / "poll_state"
TRIAGE_QUEUE = ROOT / "output" / "triage_queue.jsonl"
REGISTER_PY = ROOT / "scripts" / "register.py"
PY = sys.executable

log = logging.getLogger("bot.site_ops")


def _signal_name(rc: int) -> str:
    sig = -rc
    try:
        return signal.Signals(sig).name
    except Exception:  # noqa: BLE001
        return f"SIG{sig}"


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

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
    """polling 대상으로 등록됐는지. `state.json` 있고 `.FAILED.json`/`.REJECTED.json`/`.BUG.json` 모두 없을 때 True.
    어느 마커라도 있으면 False — 옛 state 가 남아 있더라도 polling/봇 fast-path 가 안 타게."""
    return ((STATE_DIR / f"{slug}.json").exists()
            and not (STATE_DIR / f"{slug}.FAILED.json").exists()
            and not (STATE_DIR / f"{slug}.REJECTED.json").exists()
            and not (STATE_DIR / f"{slug}.BUG.json").exists())


_ALIAS_MARKER_SUFFIX = (".FAILED.json", ".REJECTED.json", ".BUG.json")


def find_registered_alias(url: str, *, exclude_slug: Optional[str] = None) -> Optional[str]:
    """`url` 과 같은 canonical 을 가진 *이미 등록된* slug 를 poll_state 에서 역조회.

    recognizer 추가/슬러그 스키마 변경으로 같은 게시판 URL 이 deploy 전후 다른 slug 를 받으면,
    `is_registered(새 slug)`=False 가 되어 같은 board 가 2번째 config 로 중복 등록·폴링될 수 있다
    (사용자가 그 board 를 다시 `/watch` 하면 old/new 양쪽 구독 → 새 글 2번 알림).
    canonical_url 신원으로 기존 slug 를 찾아 그쪽으로 흡수해 중복을 막는다.
    `exclude_slug`(보통 방금 계산한 새 slug) 는 후보에서 제외. 없으면 None.
    """
    from engine.slug import canonical_url
    if not url or not STATE_DIR.exists():
        return None
    try:
        target = canonical_url(url)
    except Exception:  # noqa: BLE001
        return None
    for f in STATE_DIR.glob("*.json"):
        name = f.name
        if name.endswith(_ALIAS_MARKER_SUFFIX):
            continue
        slug = name[:-5]  # ".json" 제거
        if slug == exclude_slug:
            continue
        try:
            stored = (json.loads(f.read_text(encoding="utf-8")) or {}).get("url")
        except Exception:  # noqa: BLE001
            continue
        if not stored:
            continue
        try:
            same = canonical_url(stored) == target
        except Exception:  # noqa: BLE001
            continue
        if same and is_registered(slug):
            return slug
    return None


def marker_kind(slug: str) -> Optional[str]:
    """slug 의 차단 마커 종류 반환. 'rejected' / 'failed' / 'bug' / None (없음).
    여럿 동시 존재 시 우선순위: rejected > bug > failed (영구 거부가 가장 단호, BUG 는 운영자 점검, FAILED 는 hand-config).
    """
    if (STATE_DIR / f"{slug}.REJECTED.json").exists():
        return "rejected"
    if (STATE_DIR / f"{slug}.BUG.json").exists():
        return "bug"
    if (STATE_DIR / f"{slug}.FAILED.json").exists():
        return "failed"
    return None


def is_blocked(slug: str) -> bool:
    """REJECTED+FAILED+BUG 마커 중 하나라도 있으면 True. `/preview`·`/watch` 진입 시점 및 worker
    claim 시점 첫 가드 — 같은 slug 의 subprocess 재시도 차단. 응답 문구는 `marker_kind` 로 분기.
    """
    return marker_kind(slug) is not None


def blocked_info(slug: str) -> Optional[dict]:
    """현재 박힌 마커의 dump. `marker_kind` 우선순위와 일치.
    - rejected: {slug, url, reason, note, rejected_at, learned} (`_save_rejected`)
    - bug:      {slug, url, first_at, last_at, count, rc, reason, tail} (`_save_bug`)
    - failed:   {slug, url, failed_at, reason, last_config, last_feedback} (`_save_failed`)
    """
    kind = marker_kind(slug)
    if kind is None:
        return None
    suffix = {"rejected": ".REJECTED.json", "bug": ".BUG.json", "failed": ".FAILED.json"}[kind]
    p = STATE_DIR / f"{slug}{suffix}"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def is_rejected(slug: str) -> bool:
    """Deprecated alias — `is_blocked` 로 쓰는 게 의미 정확. 호출처 정리 후 제거 예정."""
    return is_blocked(slug)


def rejected_info(slug: str) -> Optional[dict]:
    """Deprecated alias — `blocked_info` 로 쓰는 게 의미 정확."""
    return blocked_info(slug)


# reason 끝 ` (...)` triage/디버그 hint — 사용자에 안 보이고 owner 운영용. 사용자 향 메시지에 쓸 때만 strip.
_INTERNAL_HINT_TAIL_RE = re.compile(r"\s*\([^()]+\)\s*$")


def public_reason(reason: Optional[str]) -> str:
    """저장된 reason 의 끝부분 ` (...)` 내부 triage hint 제거해 사용자 향 짧은 사유만 반환.
    예: 'backfill: gemini 생성+검증 3회 실패 (preflight: 글페이지 HAR re-probe + probe 신호 hint 적용 상태)'
        → 'backfill: gemini 생성+검증 3회 실패'
    None/빈 문자열 → '-' (메시지 template 에서 '-' 표시)."""
    if not reason:
        return "-"
    return _INTERNAL_HINT_TAIL_RE.sub("", reason).strip() or "-"


def baseline_count(slug: str) -> Optional[int]:
    st = STATE_DIR / f"{slug}.json"
    try:
        return int(json.loads(st.read_text(encoding="utf-8")).get("n_baseline", 0))
    except Exception:  # noqa: BLE001
        return None


def body_empty_at_baseline(slug: str) -> Optional[bool]:
    """등록 직후 첫 글 본문이 모두 0자였나(`register.py::_check_body_at_baseline` 결과).
    None=확인 안 됨(state 옛 버전 또는 fetch 예외), True=빔(비공개/등급제한 의심), False=정상.
    `/preview`·`/watch`·worker ack 메시지가 이 플래그로 경고 표시."""
    st = STATE_DIR / f"{slug}.json"
    try:
        v = json.loads(st.read_text(encoding="utf-8")).get("body_empty_at_baseline")
        return v if isinstance(v, bool) else None
    except Exception:  # noqa: BLE001
        return None


def body_warning(slug: str) -> str:
    """`/preview`·`/watch`·worker 응답에 합쳐 쓸 본문-빔 경고 문구. 빔 아니면 빈 문자열."""
    if body_empty_at_baseline(slug) is True:
        return "\n⚠️ 본문 추출 안 됨 (등급/로그인 필요 가능) — 알림은 제목·URL 만 옵니다."
    return ""


# --------------------------------------------------------------------------- #
# register.py subprocess (chromium 락 안에서; 호출자는 워커 스레드에서 to_thread 로 부른다)
# --------------------------------------------------------------------------- #
def blocking_register(url: str, article_url: Optional[str] = None,
                      *, no_recognize: bool = False,
                      on_phase: Optional[Callable[[str], None]] = None) -> tuple[int, str]:
    """register.py 를 chromium 락 안에서 실행. (rc, last_~4000 chars of stdout/stderr).
    timeout 들은 settings.chromium_lock 에서 (config.toml).

    부모 trace (worker 의 probe trace) 가 있으면 env 로 trace_id 를 register.py 에 전달 →
    register.py 의 inner spans 이 같은 trace_id 안에 append.

    `no_recognize=True` 면 register.py 에 `--no-recognize` 전달 — recognizer 가 깨진 사이트를
    같은 fast-path 로 다시 박는 무한 루프 방지용 (reprobe 시 worker 가 켬).

    `on_phase` 콜백: register.py / generator.py 가 stdout 에 `[PHASE] <label>` 을 찍으면 그 label
    (`recognize`, `probe`, `preflight`, `digest`, `generate max=N`, `gemini_attempt i/N`, `baseline`)
    이 인자로 호출됨. worker thread 에서 실행되므로 콜백은 thread-safe 해야 함 (asyncio loop 에
    edit 을 schedule 하는 식). 콜백 예외는 ack 메시지 갱신 실패로 끝나면 됨 — register 자체는 계속.
    """
    import os
    from engine.tracing import env_for_child
    cmd = [PY, "-u", str(REGISTER_PY), url]
    if article_url:
        cmd += ["--article-url", article_url]
    if no_recognize:
        cmd.append("--no-recognize")
    child_env = {**os.environ, **env_for_child()}
    try:
        with chromium_lock(timeout=settings.chromium_lock.bot_timeout,
                           slots=settings.chromium_lock.slots):
            # start_new_session=True → register.py 를 새 process group leader 로. timeout 시
            # killpg 로 손자 (probe.py, playwright driver, chrome) 까지 전부 SIGKILL 해야
            # register stdout pipe 의 writer 가 다 닫혀 `for line in proc.stdout` 가 EOF 로 빠짐.
            # 없으면 register 만 죽고 손자가 pipe 잡고 있어 봇 워커가 무한 block — job 영원 'running',
            # triage 큐도 안 들어감.
            proc = subprocess.Popen(cmd, cwd=str(ROOT),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", bufsize=1,
                                    env=child_env,
                                    start_new_session=True)
            timed_out = threading.Event()

            def _kill_on_timeout() -> None:
                if proc.poll() is None:
                    timed_out.set()
                    _kill_process_group(proc)

            killer = threading.Timer(settings.chromium_lock.register_subprocess_timeout, _kill_on_timeout)
            killer.start()
            tail: "collections.deque[str]" = collections.deque(maxlen=400)
            log.info("register.py 시작: %s", url)
            try:
                for line in (proc.stdout or []):
                    s = line.rstrip("\n")
                    tail.append(s)
                    log.info("[register] %s", s)
                    if on_phase and s.startswith("[PHASE] "):
                        try:
                            on_phase(s[len("[PHASE] "):])
                        except Exception as ce:  # noqa: BLE001
                            log.warning("on_phase 콜백 예외 (무시): %r", ce)
                rc = proc.wait()
                if rc < 0 and not timed_out.is_set():
                    sig_name = _signal_name(rc)
                    _kill_process_group(proc)
                    tail.append(f"register.py subprocess terminated by signal {-rc} ({sig_name})")
            finally:
                killer.cancel()
            log.info("register.py 종료: rc=%s%s (%s)", rc,
                     " (타임아웃 kill)" if timed_out.is_set() else "", url)
        if timed_out.is_set():
            return -2, f"register.py 실행 시간 초과 ({int(settings.chromium_lock.register_subprocess_timeout)}s)"
        if rc < 0:
            sig_name = _signal_name(rc)
            return -3, f"register.py subprocess terminated by signal {-rc} ({sig_name})\n" + "\n".join(tail)[-3900:]
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
