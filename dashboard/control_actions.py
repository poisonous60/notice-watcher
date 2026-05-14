"""dashboard `/control` 페이지의 백엔드 — validate · write · push · exec.

각 액션 = (a) 입력 검증, (b) 로컬 staging 파일에 쓰기, (c) `scripts/push.py` / `scripts/remote.py`
subprocess 호출, (d) audit log 추가. 모두 동기·단일 사용자 가정.

원격 실행 결과는 `dict(ok, rc, output)` 형태로 반환 — 템플릿이 그대로 표시.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parent.parent
ROUTING_PATH = ROOT / "output" / "llm_routing.json"
RUNTIME_PATH = ROOT / "config.local.toml"
ENV_PUSH_PATH = ROOT / ".env.push"
TIMER_PATH = ROOT / "output" / "notice-poll.timer"
AUDIT_PATH = ROOT / "output" / "control_audit.jsonl"
PUSH_SCRIPT = ROOT / "scripts" / "push.py"
REMOTE_SCRIPT = ROOT / "scripts" / "remote.py"
PRICES_PATH = ROOT / "model_prices.json"


# 4 call_site + _default. UI dropdown 순서/라벨용.
CALL_SITES = [
    ("config_generate",  "신규 config 생성 (1차)"),
    ("config_retry",     "config 생성 retry (i≥2)"),
    ("notify_summarize", "공지 본문 요약"),
    ("notify_filter",    "사용자 필터 판정"),
    ("_default",         "기본 (위 매핑 없을 때)"),
]


# `.env` 에서 마스킹할 키 (값을 ●●●● 로 표시). 부분 매치 (in) 로 검사.
SECRET_KEY_HINTS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(action: str, *, ok: bool, detail: Any = None) -> None:
    """매 control 작업 한 줄 append. 사후 디버그 + 사고 추적용."""
    rec = {"ts": _now_iso(), "action": action, "ok": ok, "detail": detail}
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 감사 로그 실패가 액션 자체를 막으면 안 됨


# --------------------------------------------------------------------------- #
# subprocess helpers
# --------------------------------------------------------------------------- #
def _run_blocking(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, cwd=str(ROOT),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, errors="replace")
    return {"ok": p.returncode == 0, "rc": p.returncode, "output": p.stdout or ""}


async def _run(cmd: list[str]) -> dict:
    """Windows asyncio 기본 event loop 는 subprocess 미지원 (`NotImplementedError`).
    `to_thread` 로 동기 호출을 워커 스레드에 보내 우회. POSIX 에서도 동일하게 동작."""
    return await asyncio.to_thread(_run_blocking, cmd)


async def run_push(target: str, *, slug: Optional[str] = None) -> dict:
    cmd = [sys.executable, str(PUSH_SCRIPT), target]
    if slug:
        cmd.append(slug)
    res = await _run(cmd)
    audit(f"push.{target}", ok=res["ok"], detail={"rc": res["rc"]})
    return res


async def run_remote(action: str, *args: str) -> dict:
    cmd = [sys.executable, str(REMOTE_SCRIPT), action, *args]
    res = await _run(cmd)
    audit(f"remote.{action}", ok=res["ok"], detail={"rc": res["rc"], "args": list(args)})
    return res


# --------------------------------------------------------------------------- #
# routing.json
# --------------------------------------------------------------------------- #
_VALID_CALL_SITES = {"config_generate", "config_retry", "notify_summarize", "notify_filter", "_default"}


def load_routing_local() -> dict:
    if not ROUTING_PATH.exists():
        return {}
    try:
        d = json.loads(ROUTING_PATH.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            # _comment 같은 메타 키 제외
            return {k: v for k, v in d.items() if isinstance(v, str)}
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def known_models() -> list[str]:
    """`model_prices.json` 의 키에서 'provider:model' 형식만 뽑아 정렬. 드롭다운 옵션 source."""
    out: list[str] = []
    try:
        data = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    for k in data.keys():
        if k.startswith("_"):
            continue
        if ":" in k and "/" not in k.split(":", 1)[0]:
            # 'gemini:...' 또는 'openrouter:...' 형식만
            prefix = k.split(":", 1)[0]
            if prefix in ("gemini", "openrouter"):
                out.append(k)
    return sorted(set(out))


def validate_routing(data: dict) -> Optional[str]:
    if not isinstance(data, dict):
        return "JSON 객체 (dict) 가 아닙니다."
    for k, v in data.items():
        if k.startswith("_") and k != "_default":
            continue  # _comment 같은 키 허용
        if k not in _VALID_CALL_SITES:
            return f"알 수 없는 call_site: {k!r}. 허용: {sorted(_VALID_CALL_SITES)}"
        if not isinstance(v, str) or ":" not in v:
            return f"{k}: 값 형식이 'provider:model' 가 아님 → {v!r}"
        provider = v.split(":", 1)[0].strip()
        if provider not in ("gemini", "openrouter"):
            return f"{k}: 알 수 없는 provider {provider!r}"
    return None


async def save_routing(routing: dict) -> dict:
    """call_site → 'provider:model' dict. 빈 값은 routing 에서 제거."""
    cleaned = {k: v.strip() for k, v in routing.items() if isinstance(v, str) and v.strip()}
    err = validate_routing(cleaned)
    if err:
        audit("save.routing", ok=False, detail={"err": err})
        return {"ok": False, "rc": -1, "output": err}
    ROUTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_comment": "dashboard /control 저장. mtime 캐시가 다음 LLM 호출에서 재로드.", **cleaned}
    ROUTING_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    audit("save.routing", ok=True, detail={"keys": sorted(cleaned.keys())})
    return await run_push("routing")


# --------------------------------------------------------------------------- #
# config.local.toml (runtime tuning)
# --------------------------------------------------------------------------- #
def load_runtime_local() -> str:
    if not RUNTIME_PATH.exists():
        return ""
    try:
        return RUNTIME_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


# `bot/runtime_config.py` 의 dataclass 필드 → UI 폼 메타.
# (section, field, type, default, description) — 변경 시 양쪽 동기화 필요.
RUNTIME_FIELDS: list[tuple[str, str, type, object, str]] = [
    ("poll", "concurrency_httpx",    int,   8,      "httpx polling 동시 요청 수"),
    ("poll", "concurrency_chromium", int,   1,      "chromium polling 동시 (보통 1)"),
    ("poll", "page_size",            int,   30,     "한 페이지 글 수"),
    ("poll", "max_new_articles",     int,   10,     "한 사이클 최대 새 글"),
    ("poll", "breakage_threshold",   int,   2,      "연속 실패 임계 (이후 FAILED)"),
    ("poll", "seen_cap",             int,   5000,   "seen post id 보관 상한"),
    ("worker", "idle_poll_seconds",  float, 2.0,    "워커 idle 주기 (초)"),
    ("chromium_lock", "bot_timeout",                   float, 900.0,  "봇 chromium lock 타임아웃 (초)"),
    ("chromium_lock", "poll_timeout",                  float, 1800.0, "폴링 chromium lock 타임아웃 (초)"),
    ("chromium_lock", "register_subprocess_timeout",   float, 600.0,  "register 서브프로세스 타임아웃 (초)"),
    ("notify", "delivered_cap",      int,   5000,   "delivered id 보관 상한"),
]


def runtime_current() -> dict:
    """`config.local.toml` 파싱해 {section: {field: value}} 반환. 없는 키는 default 가 적용됨."""
    import tomllib
    if not RUNTIME_PATH.exists():
        return {}
    try:
        return tomllib.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def runtime_rows() -> list[dict]:
    """UI 가 렌더링할 행. 각 항목: section/field/type/default/desc + current value (override 있을 때만)."""
    cur = runtime_current()
    out = []
    for section, field, t, default, desc in RUNTIME_FIELDS:
        v = cur.get(section, {}).get(field)
        out.append({
            "section": section,
            "field": field,
            "name": f"{section}__{field}",   # form name (TOML 키와 매핑)
            "type": "int" if t is int else "float",
            "default": default,
            "current": "" if v is None else v,
            "desc": desc,
        })
    return out


def build_runtime_toml(form_data: dict) -> str:
    """form_data {f'{section}__{field}': str_value} → config.local.toml 텍스트. 빈 값/default 와 같은 값은 생략."""
    by_section: dict[str, dict[str, object]] = {}
    for section, field, t, default, _desc in RUNTIME_FIELDS:
        key = f"{section}__{field}"
        raw = form_data.get(key, "")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            if t is int:
                val = int(raw.strip())
            else:
                val = float(raw.strip())
        except ValueError:
            raise ValueError(f"{section}.{field}: 숫자 변환 실패 ({raw!r})")
        if val == default:
            continue  # default 와 같으면 override 불필요
        by_section.setdefault(section, {})[field] = val
    # TOML 직렬화 — stdlib 에 writer 없어서 손으로
    lines: list[str] = []
    for section in ("poll", "worker", "chromium_lock", "notify"):
        if section not in by_section:
            continue
        lines.append(f"[{section}]")
        for k, v in by_section[section].items():
            if isinstance(v, float):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f"{k} = {v}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def validate_toml(text: str) -> Optional[str]:
    import tomllib
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return f"TOML 파싱 실패: {e}"
    return None


async def save_runtime(toml_text: str, *, restart: bool = False) -> dict:
    err = validate_toml(toml_text)
    if err:
        audit("save.runtime", ok=False, detail={"err": err})
        return {"ok": False, "rc": -1, "output": err}
    RUNTIME_PATH.write_text(toml_text, encoding="utf-8")
    audit("save.runtime", ok=True, detail={"size": len(toml_text), "restart": restart})
    res = await run_push("runtime")
    if not res["ok"]:
        return res
    if restart:
        for unit in ("bot",):
            await run_remote("restart-bot") if unit == "bot" else None
    return res


# --------------------------------------------------------------------------- #
# .env  — N100 에서 read → 로컬 staging → push
# --------------------------------------------------------------------------- #
_ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def is_secret_key(key: str) -> bool:
    K = key.upper()
    return any(h in K for h in SECRET_KEY_HINTS)


def parse_env(text: str) -> list[tuple[str, str, str]]:
    """text → [(kind, key_or_raw, value)]. kind ∈ {kv, comment, blank}."""
    out: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        s = line.rstrip("\r")
        if not s.strip():
            out.append(("blank", "", ""))
            continue
        if s.lstrip().startswith("#"):
            out.append(("comment", s, ""))
            continue
        m = _ENV_LINE_RE.match(s)
        if not m:
            out.append(("comment", s, ""))  # 알 수 없는 형식 — comment 로 보존
            continue
        k, v = m.group(1), m.group(2)
        # trailing comment 분리 안 함 — 단순 보존
        out.append(("kv", k, v))
    return out


async def load_env_remote() -> tuple[bool, str]:
    """N100 의 .env 를 가져옴. ok==False 면 stderr 반환."""
    res = await run_remote("read", "env")
    return res["ok"], res["output"]


def env_for_display(text: str) -> list[dict]:
    """템플릿용 — secret 은 마스킹."""
    out = []
    for kind, k, v in parse_env(text):
        if kind == "kv":
            out.append({"kind": "kv", "key": k, "value": v, "masked": is_secret_key(k)})
        else:
            out.append({"kind": kind, "raw": k})
    return out


async def save_env(env_text: str, *, restart: bool = False) -> dict:
    """env_text 를 그대로 .env.push 로 쓰고 push. (마스킹 복원은 caller 책임 X — UI 가 변경된 값만 보내거나 raw 전송.)"""
    if "BOT_TOKEN" not in env_text and "GEMINI_API_KEYS" not in env_text:
        audit("save.env", ok=False, detail={"err": "BOT_TOKEN/GEMINI_API_KEYS 없음 — 부분 텍스트로 보임"})
        return {"ok": False, "rc": -1, "output": "안전장치: BOT_TOKEN/GEMINI_API_KEYS 가 없습니다. 전체 .env 내용을 붙여넣으세요."}
    ENV_PUSH_PATH.write_text(env_text, encoding="utf-8")
    audit("save.env", ok=True, detail={"size": len(env_text), "restart": restart})
    res = await run_push("env")
    if not res["ok"]:
        return res
    if restart:
        r2 = await run_remote("restart-bot")
        res["output"] += "\n--- restart-bot ---\n" + r2["output"]
    return res


# --------------------------------------------------------------------------- #
# notice-poll.timer
# --------------------------------------------------------------------------- #
_ONCAL_RE = re.compile(r"^(OnCalendar\s*=).*$", re.MULTILINE)
_VALID_ONCAL_RE = re.compile(r"^[\w*:\-,/\s.]+$")  # 단순 안전성 — 진짜 검증은 systemd 가


async def load_timer_remote() -> tuple[bool, str]:
    res = await run_remote("read", "timer")
    return res["ok"], res["output"]


def parse_oncalendar(timer_text: str) -> Optional[str]:
    m = _ONCAL_RE.search(timer_text)
    if not m:
        return None
    line = timer_text[m.start():m.end()]
    return line.split("=", 1)[1].strip()


def validate_oncalendar(s: str) -> Optional[str]:
    s = s.strip()
    if not s:
        return "비어있음"
    if not _VALID_ONCAL_RE.match(s):
        return "허용되지 않은 문자가 포함됨 (자유 텍스트 차단)"
    if len(s) > 200:
        return "너무 김"
    return None


async def save_timer(oncalendar: str, *, restart: bool = True) -> dict:
    err = validate_oncalendar(oncalendar)
    if err:
        audit("save.timer", ok=False, detail={"err": err, "oncalendar": oncalendar})
        return {"ok": False, "rc": -1, "output": err}
    ok, current = await load_timer_remote()
    if not ok:
        return {"ok": False, "rc": -1, "output": f"원격 timer 읽기 실패:\n{current}"}
    if _ONCAL_RE.search(current):
        new = _ONCAL_RE.sub(f"\\1{oncalendar}", current, count=1)
    else:
        # [Timer] 섹션 안에 추가 — 간단히 마지막에 붙임
        new = current.rstrip() + f"\nOnCalendar={oncalendar}\n"
    TIMER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIMER_PATH.write_text(new, encoding="utf-8")
    audit("save.timer", ok=True, detail={"oncalendar": oncalendar})
    res = await run_push("timer")  # push.py 가 자동으로 daemon-reload 호출
    if not res["ok"]:
        return res
    if restart:
        r2 = await run_remote("status", "poll-timer")  # restart timer 는 status 보고 판단
        # timer 는 restart 명령 대신 stop + start 하거나 그냥 두면 다음 OnCalendar 적용 시 적용됨.
        # 안전하게 restart 명령 추가:
        r3 = await _run([sys.executable, str(REMOTE_SCRIPT), "logs", "poll-timer", "--tail", "10"])
        res["output"] += "\n--- status poll-timer ---\n" + r2["output"]
        res["output"] += "\n--- recent timer log ---\n" + r3["output"]
    return res


# --------------------------------------------------------------------------- #
# 통합 페이지 데이터 — GET /control 이 호출
# --------------------------------------------------------------------------- #
async def gather_state(*, load_remote: bool = False) -> dict:
    """페이지 진입 시 보여줄 현재 상태. load_remote 가 False 면 N100 안 건드리고 로컬만 표시.

    원격 읽기는 SSH 비용이 있어 기본은 off — 사용자가 명시적 클릭(Load) 으로 트리거.
    """
    routing_map = load_routing_local()
    state = {
        "routing": {
            "local_present": ROUTING_PATH.exists(),
            "current": routing_map,                # {call_site: 'provider:model'}
            "models":  known_models(),             # dropdown 옵션
            "call_sites": CALL_SITES,
        },
        "runtime": {
            "local_present": RUNTIME_PATH.exists(),
            "local_text": load_runtime_local(),
            "rows": runtime_rows(),
        },
        "env": {
            "loaded": False,
            "rows": [],
            "raw": "",
        },
        "timer": {
            "loaded": False,
            "oncalendar": "",
            "raw": "",
        },
    }
    if load_remote:
        ok, txt = await load_env_remote()
        state["env"] = {"loaded": ok, "rows": env_for_display(txt) if ok else [], "raw": txt}
        ok2, t2 = await load_timer_remote()
        state["timer"] = {"loaded": ok2, "oncalendar": parse_oncalendar(t2) or "", "raw": t2}
    return state
