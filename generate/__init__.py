"""probe digest → config(JSON) 자동 생성.

- gemini.py    : Gemini REST 호출(httpx) + responseMimeType=application/json
- prompt.py    : 시스템 지침 + few-shot + digest → 프롬프트
- generator.py : digest → gemini → JSON 파싱 → validate_config (M3: 1-shot. M5 에서 재시도/partial-regen 추가)
"""
from __future__ import annotations

from .generator import generate_config, generate_config_validated, GenerationError
from .gemini import GeminiClient, GeminiError, default_model
from .validate import validate_built_config, ValidationReport

__all__ = [
    "generate_config", "generate_config_validated", "GenerationError",
    "GeminiClient", "GeminiError", "default_model",
    "validate_built_config", "ValidationReport",
]
