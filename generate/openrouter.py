"""OpenRouter (OpenAI-compatible) 클라이언트 — `LLMClient` 구현.

- 엔드포인트: `https://openrouter.ai/api/v1/chat/completions`. Bearer auth.
- 모델 ID: `<vendor>/<name>` (예: `google/gemini-2.5-flash`, `anthropic/claude-haiku-4-5`).
- API 키:
    1. env `OPENROUTER_API_KEY`
    2. 파일 `<repo>/OPENROUTER_API_KEY.md`
- JSON 모드: `response_format={"type":"json_object"}`. 모델이 지원 안 하면 무시되거나 400 — JSON 강제는
  prompt + validate 로도 커버됨 (gemini 와 동일 정책).
- 비용: 응답 `usage` 는 토큰만. cost 는 `generate/prices.py` 가 가격표로 계산 (cost_fn 주입).
- 옵션 헤더 `HTTP-Referer`/`X-Title` 추가 — OpenRouter ranking 용. 기능 영향 X.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx

from .llm_base import (
    LLMClient, LLMResponse,
    LLMError, LLMNetworkError, LLMQuotaError, LLMHttpError, LLMParseError,
)


API_URL = "https://openrouter.ai/api/v1/chat/completions"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_KEY_FILE = _REPO_ROOT / "OPENROUTER_API_KEY.md"


class OpenRouterError(LLMError):
    """레거시 alias 용 (현재 caller 없음)."""


def _load_key() -> str:
    v = os.environ.get("OPENROUTER_API_KEY")
    if v and v.strip():
        return v.strip()
    if _DEFAULT_KEY_FILE.exists():
        for line in _DEFAULT_KEY_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    raise OpenRouterError(
        "OpenRouter API 키가 없습니다. 다음 중 하나로 설정하세요:\n"
        "  - 환경변수 OPENROUTER_API_KEY=키\n"
        f"  - 파일 {_DEFAULT_KEY_FILE} 에 한 줄로\n"
        "키 발급: https://openrouter.ai/keys"
    )


class OpenRouterClient(LLMClient):
    provider = "openrouter"

    def __init__(self, *, model: str, timeout: float = 120.0,
                 recorder=None, cost_fn=None,
                 http_referer: Optional[str] = None,
                 x_title: Optional[str] = "notice-watcher") -> None:
        super().__init__(model=model, recorder=recorder, cost_fn=cost_fn)
        self.timeout = timeout
        self._http_referer = http_referer or os.environ.get("OPENROUTER_REFERER")
        self._x_title = x_title

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {_load_key()}",
            "Content-Type": "application/json",
        }
        if self._http_referer:
            h["HTTP-Referer"] = self._http_referer
        if self._x_title:
            h["X-Title"] = self._x_title
        return h

    def _build_body(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_text},
            ],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        body = self._build_body(system_instruction=system_instruction, user_text=user_text,
                                temperature=temperature, json_mode=json_mode)
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(API_URL, json=body, headers=self._headers())
        except httpx.HTTPError as e:
            raise LLMNetworkError(f"OpenRouter 요청 실패(네트워크): {e}") from e

        if r.status_code == 429:
            raise LLMQuotaError(f"OpenRouter quota/rate-limit (429): {r.text[:400]}")
        if r.status_code >= 400:
            raise LLMHttpError(f"OpenRouter API {r.status_code}: {r.text[:600]}", status_code=r.status_code)
        return _parse_response(r.json(), fallback_model=self.model)


def _parse_response(data: dict, *, fallback_model: str) -> LLMResponse:
    choices = data.get("choices") or []
    if not choices:
        raise LLMParseError(f"OpenRouter 응답에 choices 없음: {str(data)[:400]}")
    msg = (choices[0].get("message") or {})
    text = msg.get("content") or ""
    if not text:
        raise LLMParseError(f"OpenRouter 빈 응답 (finish={choices[0].get('finish_reason')})")
    usage = data.get("usage") or {}
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    tt = int(usage.get("total_tokens") or (pt + ct))
    # OpenRouter 가 usage.cost 를 줄 때가 있음 (request 에 usage.include=true 필요). 일단 가져가고 없으면 None.
    cost_field = usage.get("cost")
    cost_usd = float(cost_field) if isinstance(cost_field, (int, float)) else None
    raw_model = str(data.get("model") or fallback_model)
    return LLMResponse(
        text=text,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        raw_model=raw_model,
        cost_usd=cost_usd,
    )


__all__ = ["OpenRouterClient", "OpenRouterError"]
