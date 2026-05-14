"""probe digest → config(JSON) 자동 생성 + LLM 추상화.

- llm_base.py       : LLMClient ABC + LLMResponse + 예외 계열
- gemini.py         : Gemini REST (`LLMClient` 구현)
- openrouter.py     : OpenRouter (OpenAI-compatible) (`LLMClient` 구현)
- usage_recorder.py : 호출 기록 sqlite writer
- prices.py         : 모델 단가표 + 비용 계산
- prompt.py         : 시스템 지침 + few-shot + digest → 프롬프트
- generator.py      : digest → gemini → JSON 파싱 → validate_config (M3: 1-shot. M5: 재시도/partial-regen).
"""
from __future__ import annotations

from .generator import generate_config, generate_config_validated, GenerationError
from .gemini import GeminiClient, GeminiError, default_model
from .openrouter import OpenRouterClient, OpenRouterError
from .llm_base import (
    LLMClient, LLMResponse,
    LLMError, LLMNetworkError, LLMQuotaError, LLMHttpError, LLMParseError,
)
from .usage_recorder import UsageRecorder, default_db_path
from .prices import compute_cost
from .validate import validate_built_config, ValidationReport

__all__ = [
    "generate_config", "generate_config_validated", "GenerationError",
    "GeminiClient", "GeminiError", "default_model",
    "OpenRouterClient", "OpenRouterError",
    "LLMClient", "LLMResponse",
    "LLMError", "LLMNetworkError", "LLMQuotaError", "LLMHttpError", "LLMParseError",
    "UsageRecorder", "default_db_path",
    "compute_cost",
    "validate_built_config", "ValidationReport",
]
