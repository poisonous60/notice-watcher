"""TOML 기반 운영 튜닝값 로더.

비밀(BOT_TOKEN/GEMINI_API_KEYS 등)은 .env, 운영 튜닝(동시성/타임아웃 등)은 이 모듈이 담당.

우선순위 (낮음 → 높음):
  1. 코드 default — 각 dataclass 의 필드 default
  2. <repo>/config.toml — repo 기본값 (커밋 대상)
  3. <repo>/config.local.toml — 머신별 override (gitignore). 일부 키만 적으면 그것만 덮음.

사용:
    from bot.runtime_config import settings
    settings.poll.concurrency_httpx
    settings.chromium_lock.bot_timeout

값을 바꾸려면 config.toml(전 머신) 또는 config.local.toml(이 머신만) 수정 후 봇/폴링 재시작.
import 시점에 한 번 읽고 캐싱 — 런타임 리로드 X.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

# 이 프로젝트는 Python 3.11+ 요구(N100 = Arch 최신, dev박스도 3.13). tomllib 는 stdlib.
import tomllib

ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = ROOT / "config.toml"
_LOCAL_PATH = ROOT / "config.local.toml"


@dataclass
class PollSection:
    concurrency_httpx: int = 8
    concurrency_chromium: int = 1
    page_size: int = 30
    max_new_articles: int = 10
    breakage_threshold: int = 2
    seen_cap: int = 5000
    # posts 캐시 TTL GC 보존 일수 (ADR 0006). 발송 지연(~1d) ≫ 보다 충분히 커야 미수신 글 안 날림.
    posts_keep_days: int = 7
    # ADR 0019 Phase 1 — chromium 사이트가 flock(_chromium_lock) 잡을 때 대기 budget(초).
    # 초과 시 그 사이트만 status='chromium_lock_timeout' 으로 종료. register subprocess 가 영구
    # hang 해도 poll cron 이 systemd 외각 timeout 까지 안 매달리게 차단.
    chromium_lock_wait_budget_s: float = 300.0


@dataclass
class WorkerSection:
    idle_poll_seconds: float = 2.0
    # 동시에 처리할 register/reprobe 잡 수. bot/worker.py 가 start() 에서 이 수만큼 task spawn.
    # ≥2 면 chromium_lock.slots 도 같은 수로 올려야 chromium 단계가 직렬화돼서 throughput 안 막힘.
    pool_size: int = 2


@dataclass
class ChromiumLockSection:
    bot_timeout: float = 900.0
    poll_timeout: float = 1800.0
    register_subprocess_timeout: float = 600.0
    # 동시 chromium 컨텍스트 슬롯. bot worker pool + poll.py 의 chromium 사이트 fetch 가 공유 (multi-file flock).
    # daemon (notice-pw-daemon.service) 가 떠 있으면 chromium 1개에 컨텍스트 N개로 share —
    # 컨텍스트당 ~100MB 추가. daemon 없으면 chromium binary 가 N개 = OOM 위험.
    slots: int = 2


@dataclass
class NotifySection:
    delivered_cap: int = 5000
    # 2-phase parallel notify (summarize/filter) 의 동시 LLM 호출 상한. ThreadPoolExecutor max_workers.
    # paid Gemini Tier 1 (4000 RPM) 한참 밑, HTTP I/O 라 RAM 영향 X. 손튠으로 늘리거나 1 로 내려 직렬화 가능.
    llm_concurrency: int = 8


@dataclass
class RateLimitSection:
    """사용자 1명이 봇으로 register 요청(/preview·/watch)을 짧은 시간에 폭주시키는 걸 막는다.
    `bot/main.py::_check_rate_limit` + `_check_queue_depth` 가 `_gate_check` 안에서 검사, 초과면
    사용자에게 안내 메시지 응답 (워커 큐 enqueue 안 함). 각 값 ≤0 이면 그 검사 끔."""
    per_user_per_hour: int = 10         # 시간당 동일 사용자 register 잡 enqueue 상한
    per_user_per_day: int = 30          # 24h 동일 사용자 register 잡 enqueue 상한
    queue_depth_cap: int = 100          # 워커 큐 pending 잡 전역 상한 — 초과 시 새 enqueue reject


@dataclass
class PruneSection:
    """`scripts/prune_probe.py` (cron) 가 oldness 검사할 기준 (일 단위). 0 이하면 그 카테고리 prune 끔."""
    probe_failed_max_age_days: int = 30      # .FAILED.json 동반된 probe artifact: 30일 지나면 삭제
    probe_unregistered_max_age_days: int = 90  # state.json 도 없는 orphan probe artifact: 90일


@dataclass
class RegisterSection:
    """`scripts/register.py` 의 LLM 생성+검증 라운드 동작."""
    max_attempts: int = 4    # gemini 생성+검증 시도 횟수. CLI --max-attempts 가 override.


@dataclass
class Settings:
    poll: PollSection = field(default_factory=PollSection)
    worker: WorkerSection = field(default_factory=WorkerSection)
    chromium_lock: ChromiumLockSection = field(default_factory=ChromiumLockSection)
    notify: NotifySection = field(default_factory=NotifySection)
    rate_limit: RateLimitSection = field(default_factory=RateLimitSection)
    prune: PruneSection = field(default_factory=PruneSection)
    register: RegisterSection = field(default_factory=RegisterSection)
    # 로딩 정보 — 디버깅용
    sources: list[str] = field(default_factory=list)


_SECTIONS = ("poll", "worker", "chromium_lock", "notify", "rate_limit", "prune", "register")


def _coerce(value: Any, annotation: Any) -> Any:
    """TOML int 가 float 필드로 들어오는 경우 등 가벼운 타입 코어션. 다른 케이스는 그대로 통과.
    `from __future__ import annotations` 때문에 annotation 은 보통 문자열 — 둘 다 처리."""
    name = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    if name == "float" and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def _apply(section_obj: Any, data: dict, *, source: str) -> list[str]:
    """data 의 키 중 dataclass 필드와 일치하는 것만 setattr (타입 코어션 포함). unknown 키는 경고."""
    warnings = []
    field_map = {f.name: f for f in fields(section_obj)}
    for k, v in (data or {}).items():
        if k in field_map:
            setattr(section_obj, k, _coerce(v, field_map[k].type))
        else:
            warnings.append(f"[runtime_config] {source}: 알 수 없는 키 무시 → {section_obj.__class__.__name__}.{k}")
    return warnings


def _load_from(path: Path, target: Settings) -> None:
    if not path.exists():
        return
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"[runtime_config] {path.name} 파싱 실패: {e!r} — 무시(이전 값 유지)", file=sys.stderr)
        return
    src = path.name
    warns: list[str] = []
    for sec in _SECTIONS:
        warns.extend(_apply(getattr(target, sec), data.get(sec, {}), source=src))
    for k in data.keys():
        if k not in _SECTIONS:
            warns.append(f"[runtime_config] {src}: 알 수 없는 section 무시 → [{k}]")
    for w in warns:
        print(w, file=sys.stderr)
    target.sources.append(src)


def _populate(target: Settings) -> Settings:
    """대상 Settings 객체를 in-place 로 채움. defaults 위에 config.toml, 그 위에 config.local.toml."""
    target.sources.clear()
    _load_from(_CONFIG_PATH, target)
    _load_from(_LOCAL_PATH, target)
    return target


settings = _populate(Settings())


def reload() -> Settings:
    """디스크 다시 읽어 module-level settings 객체를 **in-place** 갱신.

    중요: `from bot.runtime_config import settings` 로 가져간 기존 caller 들이 같은 객체를 들고 있어
    in-place 갱신이 그들에게도 보임. (만약 settings 를 새 객체로 replace 하면 기존 caller 는 stale.)
    필드 단위로 reset 후 다시 채움 — 이전에 override 됐다 사라진 키도 default 로 복원됨.
    """
    # 모든 section 의 필드를 dataclass default 로 리셋
    fresh_defaults = Settings()
    for sec in _SECTIONS:
        defaults = getattr(fresh_defaults, sec)
        target = getattr(settings, sec)
        for f in fields(target):
            setattr(target, f.name, getattr(defaults, f.name))
    return _populate(settings)
