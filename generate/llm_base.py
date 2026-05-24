"""LLM 추상화 공통 타입. provider 추가 시 이 파일은 안 바뀜.

- `LLMResponse`     : 본문 + 토큰/비용/지연 메타.
- `LLMError` 계열   : status 라벨 분류용 (quota_429 / http_4xx / parse_error / network / other).
- `LLMClient`       : ABC. 자식은 `_do_request` 구현. `generate(...)` 가 시간 측정·recorder 기록·cost 계산 처리.
- 기록 누락 방지: `generate` 정상/예외 양쪽 path 에서 recorder.write 호출.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class LLMError(RuntimeError):
    """일반 실패. `status` 로 분류 기록됨."""
    status: str = "other"


class LLMNetworkError(LLMError):
    status = "network"


class LLMQuotaError(LLMError):
    """429 또는 키 소진. recorder 는 `quota_429` 로 기록."""
    status = "quota_429"


class LLMHttpError(LLMError):
    """4xx/5xx (429 제외). status_code 보존."""
    status = "http_error"

    def __init__(self, msg: str, status_code: int):
        super().__init__(msg)
        self.status_code = status_code


class LLMParseError(LLMError):
    status = "parse_error"


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_usd: Optional[float] = None
    raw_model: str = ""           # provider 가 알려준 정확 모델명 (별칭 해석된 결과)
    key_idx: Optional[int] = None  # gemini 직링크 멀티키 라운드로빈에서 어느 키 썼나
    prompt_chars: int = 0
    response_chars: int = 0
    provider: str = ""             # 응답 *준* 실제 provider — FallbackClient 가 primary/fallback 중
                                   # 어느 게 응답했는지 caller 가 알 수 있음. base `LLMClient.generate`
                                   # 가 success path 에서 self.provider 로 채움 (FallbackClient 도
                                   # 자기 primary/fallback 의 generate() 가 채운 값 그대로 반환).


@dataclass
class _Recorded:
    call_site: str
    slug: Optional[str]
    attempt: int


class LLMClient(ABC):
    """공통 facade. 자식은 `_do_request` 만 구현."""

    provider: str = "unknown"

    def __init__(self, *, model: str, recorder: Optional["UsageRecorder"] = None,  # noqa: F821
                 cost_fn: Optional[callable] = None) -> None:
        self.model = model
        self.recorder = recorder
        self._cost_fn = cost_fn  # (provider, model, prompt_tokens, completion_tokens) -> float|None

    @abstractmethod
    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        """raw 호출. 시간 측정·기록은 부모가 함. 실패 시 LLMError 계열 raise."""
        ...

    def generate(self, *, system_instruction: str, user_text: str,
                 temperature: float = 0.2, json_mode: bool = True,
                 call_site: str = "legacy", slug: Optional[str] = None,
                 attempt: int = 1) -> LLMResponse:
        prompt_chars = len(system_instruction) + len(user_text)
        t0 = time.monotonic()
        try:
            resp = self._do_request(system_instruction=system_instruction, user_text=user_text,
                                    temperature=temperature, json_mode=json_mode)
        except LLMError as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            self._record_safe(call_site=call_site, slug=slug, attempt=attempt,
                              status=e.status, latency_ms=elapsed,
                              prompt_chars=prompt_chars, response_chars=0,
                              prompt_tokens=0, completion_tokens=0, total_tokens=0,
                              cost_usd=None, key_idx=None, raw_model="")
            raise

        elapsed = int((time.monotonic() - t0) * 1000)
        resp.latency_ms = elapsed
        resp.prompt_chars = prompt_chars
        resp.response_chars = len(resp.text)
        resp.provider = self.provider
        if resp.cost_usd is None and self._cost_fn is not None:
            try:
                resp.cost_usd = self._cost_fn(self.provider, resp.raw_model or self.model,
                                              resp.prompt_tokens, resp.completion_tokens)
            except Exception:  # noqa: BLE001 — 비용 계산 실패가 호출을 막으면 안 됨
                resp.cost_usd = None
        self._record_safe(call_site=call_site, slug=slug, attempt=attempt, status="ok",
                          latency_ms=elapsed, prompt_chars=prompt_chars,
                          response_chars=resp.response_chars,
                          prompt_tokens=resp.prompt_tokens,
                          completion_tokens=resp.completion_tokens,
                          total_tokens=resp.total_tokens,
                          cost_usd=resp.cost_usd, key_idx=resp.key_idx,
                          raw_model=resp.raw_model or self.model)
        return resp

    def _record_safe(self, **kw) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder.write(provider=self.provider, model=self.model, **kw)
        except Exception:  # noqa: BLE001 — 기록 실패가 호출을 막으면 안 됨
            pass


__all__ = [
    "LLMClient", "LLMResponse",
    "LLMError", "LLMNetworkError", "LLMQuotaError", "LLMHttpError", "LLMParseError",
]
