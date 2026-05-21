"""call_site → (provider, model) routing factory.

- `output/llm_routing.json` 가 source. 형식:
    {
      "config_generate":  "gemini:gemini-2.5-flash",
      "config_retry":     "gemini:gemini-2.5-pro",
      "notify_summarize": "openrouter:google/gemini-flash-1.5-8b",
      "notify_filter":    "openrouter:google/gemini-flash-1.5-8b",
      "_default":         "gemini:gemini-2.5-flash"
    }
- 값 형식: `<provider>:<model>` 또는 `<provider>:<model>#<effort>`. provider 생략 시 gemini 로 가정.
  `#<effort>` (low|medium|high) 는 codex 전용 reasoning effort override — 없으면 모델명 기반 자동 추론.
- 파일 없거나 키 없으면 `_default` → 그것도 없으면 `GEMINI_MODEL` env 또는 gemini-2.5-flash.
- mtime 캐시 — 파일 바뀌면 다음 호출에서 자동 재로드. (대시보드가 파일 쓰면 즉시 반영.)
- 동일 (provider, model) 에 대해 클라이언트 인스턴스 캐싱 — httpx 는 호출마다 새로 열지만 클라이언트 객체
  자체는 가벼워서 의미 큰 최적화는 아니지만, recorder 주입 일관성을 보장.
- `set_process_override(...)` — CLI `--model` 옵션 같은 1회성 override. 모든 call_site 에 적용.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .codex import CodexClient
from .gemini import GeminiClient, default_model as gemini_default_model
from .openrouter import OpenRouterClient
from .llm_base import LLMClient, LLMError, LLMResponse
from .prices import compute_cost
from .usage_recorder import get_default_recorder


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROUTING = _REPO_ROOT / "output" / "llm_routing.json"


@dataclass(frozen=True)
class _Route:
    provider: str
    model: str
    effort: Optional[str] = None  # codex reasoning effort override (low|medium|high)


_VALID_EFFORTS = ("low", "medium", "high")


def _parse_target(s: str) -> _Route:
    s = s.strip()
    effort: Optional[str] = None
    # 끝의 `#<low|medium|high>` 만 effort 로 인식. 그 외 '#' 는 모델명 일부로 보존(backward-compat —
    # 모델 id 에 '#' 가 들어와도 잘리지 않음).
    if "#" in s:
        base, _, suffix = s.rpartition("#")
        if suffix.strip().lower() in _VALID_EFFORTS:
            s = base.strip()
            effort = suffix.strip().lower()
    if ":" not in s:
        provider, model = "gemini", s
    else:
        p, m = s.split(":", 1)
        provider, model = p.strip(), m.strip()
    # effort 는 codex 만 의미 있음 — 그 외 provider 면 버려서 cache key 오염/오설정 은닉 방지.
    if provider != "codex":
        effort = None
    return _Route(provider, model, effort)


_cache_mtime: float = -1.0
_cache_table: dict[str, _Route] = {}
_client_cache: dict[tuple[str, str, Optional[str]], LLMClient] = {}
_process_override: Optional[str] = None


def _routing_path() -> Path:
    return _DEFAULT_ROUTING


def _reload_if_changed() -> None:
    global _cache_mtime, _cache_table, _client_cache
    p = _routing_path()
    try:
        mt = p.stat().st_mtime
    except OSError:
        if _cache_table:
            _cache_table = {}
            _client_cache.clear()
            _cache_mtime = -1.0
        return
    if mt == _cache_mtime:
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # 파싱 실패면 기존 캐시 유지 (잘못된 편집이 운영 중단시키지 않게)
    out: dict[str, _Route] = {}
    for k, v in data.items():
        if isinstance(v, str) and v.strip():
            try:
                out[k] = _parse_target(v)
            except ValueError:
                continue
    _cache_table = out
    _cache_mtime = mt
    _client_cache.clear()


def set_process_override(model_str: Optional[str]) -> None:
    """CLI `--model` 같은 1회성 process-wide override. None 으로 해제."""
    global _process_override
    if model_str != _process_override:
        _client_cache.clear()
    _process_override = model_str


def _fallback_default() -> _Route:
    return _Route("gemini", gemini_default_model())


def resolve(call_site: str, *, override: Optional[str] = None) -> _Route:
    _reload_if_changed()
    eff_override = override or _process_override
    if eff_override:
        return _parse_target(eff_override)
    route = _cache_table.get(call_site) or _cache_table.get("_default")
    return route or _fallback_default()


def client_for(call_site: str, *, override: Optional[str] = None,
               recorder=None) -> LLMClient:
    """call_site 에 해당하는 LLMClient 반환. (provider, model) 단위 캐싱.

    `override` (이 호출 한정) > `set_process_override` > routing.json > _default > GEMINI_MODEL env.
    """
    route = resolve(call_site, override=override)
    key = (route.provider, route.model, route.effort)
    cli = _client_cache.get(key)
    if cli is None:
        rec = recorder if recorder is not None else get_default_recorder()
        if route.provider == "gemini":
            cli = GeminiClient(model=route.model, recorder=rec, cost_fn=compute_cost)
        elif route.provider == "openrouter":
            cli = OpenRouterClient(model=route.model, recorder=rec, cost_fn=compute_cost)
        elif route.provider == "codex":
            primary = CodexClient(model=route.model, reasoning_effort=route.effort,
                                  recorder=rec, cost_fn=compute_cost)
            fallback = GeminiClient(model=gemini_default_model(), recorder=rec, cost_fn=compute_cost)
            cli = FallbackClient(primary, fallback)
        else:
            raise ValueError(f"unknown provider {route.provider!r} in routing for call_site={call_site!r}")
        _client_cache[key] = cli
    return cli


class FallbackClient(LLMClient):
    """primary 실패 시 fallback 으로 자동 전환.

    `generate()` 자체를 override 해서 primary 와 fallback 가 각자의 recorder/cost 흐름으로
    기록되게 한다 — primary 실패 1건 + fallback 성공 1건 (총 2건) 기록 → quota 고갈 모니터링 가능.
    provider/cost 라벨도 각 client 자기 것 그대로 (mislabel 없음).
    """

    provider = "fallback"  # wrapper 자체는 직접 _do_request 안 함

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        # wrapper 의 recorder/cost_fn 은 안 씀 (primary/fallback 이 직접 기록).
        super().__init__(model=primary.model, recorder=None, cost_fn=None)
        self.primary = primary
        self.fallback = fallback

    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        raise NotImplementedError("FallbackClient overrides generate() — _do_request unused")

    def generate(self, *, system_instruction: str, user_text: str,
                 temperature: float = 0.2, json_mode: bool = True,
                 call_site: str = "legacy", slug: Optional[str] = None,
                 attempt: int = 1) -> LLMResponse:
        try:
            return self.primary.generate(
                system_instruction=system_instruction, user_text=user_text,
                temperature=temperature, json_mode=json_mode,
                call_site=call_site, slug=slug, attempt=attempt,
            )
        except LLMError as e:
            print(f"  [{self.primary.provider}→{self.fallback.provider} fallback] "
                  f"{type(e).__name__}: {e}")
            return self.fallback.generate(
                system_instruction=system_instruction, user_text=user_text,
                temperature=temperature, json_mode=json_mode,
                call_site=call_site, slug=slug, attempt=attempt,
            )


__all__ = ["client_for", "resolve", "set_process_override"]
