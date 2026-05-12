"""Gemini 프롬프트 텍스트(repo 루트 `prompts/*.txt`) 로더.

프롬프트 *본문* 은 코드와 분리해 `prompts/` 의 `.txt` 파일에 둔다. 이 모듈이 읽어서
`{{placeholder}}` 를 런타임 값으로 채워 반환한다.

- placeholder 문법: `{{이름}}` (공백 허용: `{{ 이름 }}`). 프롬프트 본문에 나오는 JSON 예시는
  중괄호가 한 겹(`{from:"css", ...}`, `value:"...{post_id}..."`) 뿐이라 충돌하지 않는다 —
  두 겹 `{{...}}` 은 오직 이 로더의 치환자.
- render_prompt() 는 텍스트에 있는데 안 넘어온 placeholder 가 있으면 KeyError —
  텍스트와 호출부의 키가 어긋나면 조용히 새지 않고 바로 터진다.
- 치환은 텍스트(스켈레톤)에 대해 *한 번만* 수행하며, 채워 넣은 값은 다시 스캔하지 않는다
  (값 안에 우연히 `{{...}}` 가 있어도 재치환 안 됨 — build_retry_prompt 가 `{{base}}` 에
  build_user_prompt 결과를 통째로 끼우는 케이스 안전).

파일 끝의 개행은 무시한다(`prompts/*.txt` 가 trailing newline 으로 끝나든 말든 동일).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """prompts/<name>.txt 를 그대로 읽어 반환(치환 없음). 끝의 개행은 떼어냄."""
    p = PROMPTS_DIR / f"{name}.txt"
    if not p.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {p}")
    return p.read_text(encoding="utf-8").rstrip("\n")


def render_prompt(name: str, **values: object) -> str:
    """prompts/<name>.txt 의 {{key}} 를 values[key] 로 치환해 반환. 안 채워진 키가 있으면 KeyError."""
    text = load_prompt(name)
    missing: list[str] = []

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return str(values[key])

    out = _PLACEHOLDER_RE.sub(_sub, text)
    if missing:
        raise KeyError(f"프롬프트 {name!r}: 안 채워진 placeholder {sorted(set(missing))}")
    return out
