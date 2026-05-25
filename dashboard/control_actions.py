"""dashboard `/control` 페이지의 백엔드 — validate · write · push · exec.

각 액션 = (a) 입력 검증, (b) 로컬 staging 파일에 쓰기, (c) `scripts/push.py` / `scripts/remote.py`
subprocess 호출, (d) audit log 추가. 모두 동기·단일 사용자 가정.

원격 실행 결과는 `dict(ok, rc, output)` 형태로 반환 — 템플릿이 그대로 표시.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dashboard.shell import async_run


ROOT = Path(__file__).resolve().parent.parent
ROUTING_PATH = ROOT / "output" / "llm_routing.json"
RUNTIME_PATH = ROOT / "config.local.toml"
ENV_PUSH_PATH = ROOT / ".env.push"
TIMER_PATH = ROOT / "output" / "notice-poll.timer"
AUDIT_PATH = ROOT / "output" / "control_audit.jsonl"
PUSH_SCRIPT = ROOT / "scripts" / "push.py"
REMOTE_SCRIPT = ROOT / "scripts" / "remote.py"
PRICES_PATH = ROOT / "model_prices.json"


# 5 call_site + _default. UI dropdown 순서/라벨용.
CALL_SITES = [
    ("config_generate",       "신규 config 생성 (1차)"),
    ("config_retry",          "config 생성 retry (i≥2)"),
    ("classify_index_content", "게시판/단일글 veto 분류 (ADR 0007)"),
    ("notify_summarize",      "공지 본문 요약"),
    ("notify_filter",         "사용자 필터 판정"),
    ("_default",              "기본 (위 매핑 없을 때)"),
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
# subprocess wrappers — dashboard.shell.async_run 가 Windows 호환 처리
# --------------------------------------------------------------------------- #
async def run_push(target: str, *, slug: Optional[str] = None) -> dict:
    cmd = [sys.executable, str(PUSH_SCRIPT), target]
    if slug:
        cmd.append(slug)
    res = await async_run(cmd, cwd=ROOT)
    audit(f"push.{target}", ok=res["ok"], detail={"rc": res["rc"], "trace_id": res.get("trace_id")})
    return res


async def run_remote(action: str, *args: str) -> dict:
    cmd = [sys.executable, str(REMOTE_SCRIPT), action, *args]
    res = await async_run(cmd, cwd=ROOT)
    audit(f"remote.{action}", ok=res["ok"],
          detail={"rc": res["rc"], "args": list(args), "trace_id": res.get("trace_id")})
    return res


# --------------------------------------------------------------------------- #
# /users 페이지 액션 — remote.py 의 새 verb 들을 호출.
# 인자 검증은 remote.py 가 정규식으로 한 번 더 거름 (중복 방어 — XSS/injection 가드).
# --------------------------------------------------------------------------- #
async def users_poll_now_slug(slugs_csv: str) -> dict:
    """M1 — 일부 slug 즉시 poll-now + notify (정상 pipeline; fan-out 발송)."""
    res = await run_remote("poll-now-slug", slugs_csv)
    audit("users.poll_now_slug", ok=res["ok"],
          detail={"slugs": slugs_csv, "rc": res["rc"], "trace_id": res.get("trace_id")})
    return res


async def users_replay(slug: str, target_kind: str, target_id: str,
                       post_id: str | None = None) -> dict:
    """M2 (post_id 있음) / M3 (없음) — replay.py 가 lock+직렬 실행."""
    args = [slug, target_kind, target_id] + ([post_id] if post_id else [])
    res = await run_remote("replay-deliveries", *args)
    audit("users.replay", ok=res["ok"],
          detail={"slug": slug, "kind": target_kind, "id": target_id,
                  "post": post_id, "bulk": post_id is None, "rc": res["rc"],
                  "trace_id": res.get("trace_id")})
    return res


async def users_notify_target(slug: str, target_kind: str, target_id: str) -> dict:
    """현 collected dir 의 새 글을 그 target 만 발송. (poll-now 동반 안 됨 — 이미 polling 된 상태 가정)."""
    res = await run_remote("notify-target", slug, target_kind, target_id)
    audit("users.notify_target", ok=res["ok"],
          detail={"slug": slug, "kind": target_kind, "id": target_id, "rc": res["rc"],
                  "trace_id": res.get("trace_id")})
    return res


async def users_m1_solo(slug: str, target_kind: str, target_id: str) -> dict:
    """M1 단독 — `poll-now-slug-quiet` (poll 만, notify 생략) 후 `notify-target` 으로 그 target 만 발송.

    poll → collected/<ts>/<slug>.new.json → notify-target 이 처리 후 `.notified` 마커 작성 →
    이후 notice-poll.timer / notice-notify.timer tick 에서 같은 dir 재처리 안 됨 → 다른
    구독자 자동 fan-out 차단. poll 실패 시 notify 단계 skip.

    quiet 변종을 쓰는 이유: 기본 `poll-now-slug` 은 정상 pipeline (poll_cron) 이라 새 글이
    있으면 *모든* 구독자에 fan-out 됨 → 격리 발송 의도가 깨짐.
    """
    r1 = await run_remote("poll-now-slug-quiet", slug)
    audit("users.m1_solo.poll", ok=r1["ok"],
          detail={"slug": slug, "rc": r1["rc"], "trace_id": r1.get("trace_id")})
    if not r1["ok"]:
        return r1
    r2 = await run_remote("notify-target", slug, target_kind, target_id)
    audit("users.m1_solo.notify", ok=r2["ok"],
          detail={"slug": slug, "kind": target_kind, "id": target_id, "rc": r2["rc"],
                  "trace_id": r2.get("trace_id")})
    combined = {
        "ok": r2["ok"],
        "rc": r2["rc"],
        "output": (r1.get("output") or "")
                  + "\n--- notify-target ---\n"
                  + (r2.get("output") or ""),
    }
    return combined


async def users_announce(title: str, message: str, sent_by: str,
                         recipients: list[tuple[str, str]]) -> dict:
    """Scoped announce — title/message/recipients 를 JSON 으로 직렬화→base64→N100 announce.py 에 전달.

    recipients = [(kind, id), ...]. 빈 list 면 fail-fast (announce.py 에서 validation).
    """
    import base64
    import json
    payload = {
        "title": title, "message": message, "sent_by": sent_by,
        "recipients": [list(r) for r in recipients],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    res = await run_remote("announce-scoped", b64)
    audit("users.announce", ok=res["ok"],
          detail={"title": title[:80], "n_recipients": len(recipients),
                  "size_b64": len(b64), "rc": res["rc"], "trace_id": res.get("trace_id")})
    return res


_ACTIVE_RE = re.compile(r"^\s*Active:\s*(\S+)\s*(?:\(([^)]+)\))?", re.MULTILINE)


def interpret_systemctl_status(output: str) -> str:
    """`systemctl status` 의 `Active:` 줄을 파싱해 의미 있는 상태로.

    Returns:
      - "active"        — 현재 실행 중
      - "inactive_ok"   — one-shot 서비스가 정상 종료 후 다음 trigger 대기 중 (정상)
      - "failed"        — 진짜 실패 (`Active: failed (...)` 또는 마지막 exit 비0)
      - "activating"    — 시작 중
      - "deactivating"  — 종료 중
      - "unknown"       — 파싱 실패 (서비스 없음 등)

    rc 만 보면 inactive 도 fail 로 잘못 분류됨 — one-shot/timer-triggered 서비스에 특히 중요.
    """
    m = _ACTIVE_RE.search(output or "")
    if not m:
        return "unknown"
    state = m.group(1).strip().lower()
    if state == "active":
        return "active"
    if state == "failed":
        return "failed"
    if state == "inactive":
        # `Main PID: ... (code=exited, status=0/SUCCESS)` 가 있으면 정상 종료
        if re.search(r"code=exited,\s*status=0/SUCCESS", output):
            return "inactive_ok"
        # 종료 코드가 명시 안 됨 (한 번도 안 돈 timer) → 보수적으로 inactive_ok
        if "code=exited" not in output and "status=" not in output:
            return "inactive_ok"
        return "failed"
    if state == "activating":
        return "activating"
    if state == "deactivating":
        return "deactivating"
    return "unknown"


# --------------------------------------------------------------------------- #
# routing.json
# --------------------------------------------------------------------------- #
_VALID_CALL_SITES = {"config_generate", "config_retry", "classify_index_content",
                     "notify_summarize", "notify_filter", "_default"}

# codex 전용 reasoning effort 옵션 (UI 드롭다운 + 검증). 빈 값 = 모델명 기반 자동 추론.
REASONING_EFFORTS = ["low", "medium", "high"]


def split_routing_value(v: str) -> tuple[str, str]:
    """'provider:model#effort' → ('provider:model', 'effort'). effort 없으면 ('provider:model', '')."""
    if not isinstance(v, str):
        return "", ""
    if "#" in v:
        model, eff = v.split("#", 1)
        return model.strip(), eff.strip().lower()
    return v.strip(), ""


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
            # 'gemini:...' / 'openrouter:...' / 'codex:...' 형식만
            prefix = k.split(":", 1)[0]
            if prefix in ("gemini", "openrouter", "codex"):
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
        if not isinstance(v, str):
            return f"{k}: 값 형식이 'provider:model' 가 아님 → {v!r}"
        model_part, effort = split_routing_value(v)
        if ":" not in model_part:
            return f"{k}: 값 형식이 'provider:model' 가 아님 → {v!r}"
        provider = model_part.split(":", 1)[0].strip()
        if provider not in ("gemini", "openrouter", "codex"):
            return f"{k}: 알 수 없는 provider {provider!r}"
        if effort:
            if effort not in REASONING_EFFORTS:
                return f"{k}: 알 수 없는 reasoning effort {effort!r} (low|medium|high)"
            if provider != "codex":
                return f"{k}: reasoning effort 는 codex provider 만 지원 → {v!r}"
    return None


def build_routing_form(form: dict) -> dict:
    """form_data → {call_site: 'provider:model' 또는 'provider:model#effort'}.

    각 call_site 의 모델 select(name=call_site) + effort select(name=f'{call_site}__effort').
    effort 는 codex 모델에만 붙임 (그 외 무시). 빈 모델은 '' → save_routing 이 매핑 제거.
    """
    out: dict[str, str] = {}
    for cs in _VALID_CALL_SITES:
        model = (form.get(cs) or "").strip()
        if not model:
            out[cs] = ""
            continue
        effort = (form.get(f"{cs}__effort") or "").strip().lower()
        if effort in REASONING_EFFORTS and model.split(":", 1)[0].strip() == "codex":
            out[cs] = f"{model}#{effort}"
        else:
            out[cs] = model
    return out


async def save_routing(routing: dict) -> dict:
    """call_site → 'provider:model' dict. 빈 값은 routing 에서 제거.

    push 실패 시 로컬 파일을 이전 내용으로 rollback — 로컬/원격 divergence 방지."""
    cleaned = {k: v.strip() for k, v in routing.items() if isinstance(v, str) and v.strip()}
    err = validate_routing(cleaned)
    if err:
        audit("save.routing", ok=False, detail={"err": err})
        return {"ok": False, "rc": -1, "output": err}
    ROUTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    prev = ROUTING_PATH.read_text(encoding="utf-8") if ROUTING_PATH.exists() else None
    payload = {"_comment": "dashboard /control 저장. mtime 캐시가 다음 LLM 호출에서 재로드.", **cleaned}
    ROUTING_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    audit("save.routing", ok=True, detail={"keys": sorted(cleaned.keys())})
    res = await run_push("routing")
    if not res["ok"]:
        # push 실패 → 로컬 원복 (다음 save 시 stale state 로 시작하지 않도록)
        if prev is None:
            try:
                ROUTING_PATH.unlink()
            except OSError:
                pass
        else:
            ROUTING_PATH.write_text(prev, encoding="utf-8")
        audit("save.routing.rollback", ok=False, detail={"rc": res["rc"]})
    return res


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
    ("worker", "pool_size",          int,   2,      "동시 처리 register/reprobe 잡 수 (chromium_lock.slots 와 같이 올림)"),
    ("chromium_lock", "bot_timeout",                   float, 900.0,  "봇 chromium lock 타임아웃 (초)"),
    ("chromium_lock", "poll_timeout",                  float, 1800.0, "폴링 chromium lock 타임아웃 (초)"),
    ("chromium_lock", "register_subprocess_timeout",   float, 600.0,  "register 서브프로세스 타임아웃 (초)"),
    ("chromium_lock", "slots",                         int,   2,      "동시 chromium 컨텍스트 슬롯 (bot+poll 공유, daemon 필수)"),
    ("notify", "delivered_cap",      int,   5000,   "delivered id 보관 상한"),
    ("rate_limit", "per_user_per_hour",   int, 10,  "시간당 동일 사용자 register 잡 enqueue 상한 (≤0=끔)"),
    ("rate_limit", "per_user_per_day",    int, 30,  "24h 동일 사용자 register 잡 enqueue 상한 (≤0=끔)"),
    ("rate_limit", "queue_depth_cap",     int, 100, "워커 큐 pending 잡 전역 상한 (≤0=끔)"),
    ("prune", "probe_failed_max_age_days",       int, 30, "scripts/prune_probe.py: .FAILED 동반 probe artifact prune age (일, ≤0=끔)"),
    ("prune", "probe_unregistered_max_age_days", int, 90, "scripts/prune_probe.py: orphan probe artifact prune age (일, ≤0=끔)"),
    ("register", "max_attempts", int, 4, "register.py LLM 생성+검증 시도 횟수 (실패당 비용 발생, 1~2 권장)"),
]

# UI 표시용 section 라벨. 키 없으면 template 가 section 키 자체를 fallback 으로 씀
# → 새 RUNTIME_FIELDS 항목 추가해도 UI 가 자동 노출됨 (라벨만 빈 채).
SECTION_LABELS: dict[str, str] = {
    "poll":          "폴링",
    "worker":        "워커",
    "chromium_lock": "Chromium 락",
    "notify":        "알림",
    "rate_limit":    "Rate Limit",
    "prune":         "Probe 산출물 prune",
    "register":      "사이트 등록",
}


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
    # TOML 직렬화 — stdlib writer 없음. int / float 둘 다 str() 으로 충분
    # (int 는 정수 출력, float 는 `1.0` 같은 dot 포함 출력 → TOML 둘 다 valid).
    lines: list[str] = []
    for section in ("poll", "worker", "chromium_lock", "notify", "rate_limit", "prune", "register"):
        if section not in by_section:
            continue
        lines.append(f"[{section}]")
        for k, v in by_section[section].items():
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
        r2 = await run_remote("restart-bot")
        res["output"] += "\n--- restart-bot ---\n" + r2["output"]
        if not r2["ok"]:
            res["ok"] = False
            res["rc"] = r2["rc"]
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
    """env_text 를 .env.push 로 쓰고 push. push 끝나면 (성공/실패 무관) 로컬 staging 파일 삭제 — 비밀 누설 방지.

    안전장치: BOT_TOKEN 이 활성 kv (주석 X) 로 존재해야 함. 부분 텍스트 / 주석된 키 차단.
    """
    rows = parse_env(env_text)
    active_keys = {k for kind, k, _ in rows if kind == "kv"}
    if "BOT_TOKEN" not in active_keys:
        audit("save.env", ok=False, detail={"err": "BOT_TOKEN active kv missing"})
        return {"ok": False, "rc": -1, "output": "안전장치: 활성 BOT_TOKEN= 행이 없습니다. 전체 .env 내용을 붙여넣으세요 (주석 처리된 줄은 카운트 안 됨)."}
    ENV_PUSH_PATH.write_text(env_text, encoding="utf-8")
    audit("save.env", ok=True, detail={"size": len(env_text), "restart": restart})
    try:
        res = await run_push("env")
        if res["ok"] and restart:
            r2 = await run_remote("restart-bot")
            res["output"] += "\n--- restart-bot ---\n" + r2["output"]
            if not r2["ok"]:
                res["ok"] = False
                res["rc"] = r2["rc"]
        return res
    finally:
        # push 성공/실패와 무관하게 staging 비밀 파일 제거 — 실패 시 파일에 비밀이 남는 risk 차단.
        try:
            ENV_PUSH_PATH.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# notice-poll.timer
# --------------------------------------------------------------------------- #
_ONCAL_RE = re.compile(r"^(OnCalendar\s*=).*$", re.MULTILINE)
# 단순 안전성 — `\s` 는 newline 포함이라 multi-line 통과 risk. horizontal whitespace ([ \t]) 만 허용.
_VALID_ONCAL_RE = re.compile(r"^[\w*:\-,/ \t.]+$")


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
        # timer 는 restart 명령 대신 stop+start 하거나 그냥 두면 다음 OnCalendar 적용 시 자동 반영.
        # 여기선 진단 정보만 표시 — daemon-reload 는 push.py 가 이미 호출.
        r2 = await run_remote("status", "poll-timer")
        r3 = await run_remote("logs", "poll-timer", "--tail", "10")
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
    # 실제로 적용되는 모델 — `generate.routing.resolve()` 가 routing.json 캐시를 무시하지 않고 dev박스 로컬 파일만 봄.
    # routing 가 비어있어도 fallback (`GEMINI_MODEL` env 또는 gemini-2.5-flash) 을 표시할 수 있게 effective 계산.
    from generate import routing as _routing
    effective: dict[str, str] = {}
    for cs, _ in CALL_SITES:
        if cs == "_default":
            r = _routing.resolve("__nonexistent_for_default__")  # _default 또는 fallback
        else:
            r = _routing.resolve(cs)
        effective[cs] = f"{r.provider}:{r.model}" + (f"#{r.effort}" if r.effort else "")
    # 모델/effort 를 분리해 둠 — 템플릿이 model select 와 effort select 를 각각 채우게.
    current_model: dict[str, str] = {}
    current_effort: dict[str, str] = {}
    effective_model: dict[str, str] = {}
    effective_effort: dict[str, str] = {}
    for cs, _ in CALL_SITES:
        cm, ce = split_routing_value(routing_map.get(cs, ""))
        current_model[cs], current_effort[cs] = cm, ce
        em, ee = split_routing_value(effective.get(cs, ""))
        effective_model[cs], effective_effort[cs] = em, ee
    state = {
        "routing": {
            "local_present": ROUTING_PATH.exists(),
            "current": routing_map,                # {call_site: 'provider:model[#effort]'} — 명시 override 만
            "effective": effective,                # {call_site: 'provider:model[#effort]'} — 실제 적용 (override 없으면 fallback)
            "current_model": current_model,        # override 의 모델 부분만
            "current_effort": current_effort,      # override 의 effort 부분만 ('' = 미지정)
            "effective_model": effective_model,
            "effective_effort": effective_effort,
            "models":  known_models(),             # model dropdown 옵션
            "efforts": REASONING_EFFORTS,          # effort dropdown 옵션 (codex 전용)
            "call_sites": CALL_SITES,
        },
        "runtime": {
            "local_present": RUNTIME_PATH.exists(),
            "local_text": load_runtime_local(),
            "rows": runtime_rows(),
            "section_labels": SECTION_LABELS,
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
        # env + timer SSH 호출 병렬 — 두 round-trip 합산이 페이지 로드 latency 의 대부분
        env_res, timer_res = await asyncio.gather(load_env_remote(), load_timer_remote())
        ok, txt = env_res
        ok2, t2 = timer_res
        state["env"] = {"loaded": ok, "rows": env_for_display(txt) if ok else [], "raw": txt}
        state["timer"] = {"loaded": ok2, "oncalendar": parse_oncalendar(t2) or "", "raw": t2}
    return state
