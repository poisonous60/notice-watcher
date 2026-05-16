"""Discord 봇 사용자 향 메시지 텍스트(repo 루트 `messages/*.txt`) 로더.

메시지 *본문* 은 코드와 분리해 `messages/` 의 `.txt` 파일에 둔다. 이 모듈이 읽어서
`{{placeholder}}` 를 런타임 값으로 채워 반환한다.

설계는 `generate/prompts.py` 와 동형 — 같은 `{{key}}` 문법, lru 캐시, missing → KeyError.
LLM 프롬프트(prompts/) 와 사용자 향 메시지(messages/) 를 디렉터리로 분리해 두 도메인이
서로 영향 없게 한다.

- placeholder 문법: `{{이름}}` (공백 허용: `{{ 이름 }}`).
- render() 는 텍스트에 있는데 안 넘어온 placeholder 가 있으면 KeyError — 조용히 새지 않음.
- 치환은 텍스트에 대해 *한 번만* — 값 안에 우연히 `{{...}}` 가 있어도 재치환 안 됨.

파일 끝의 개행은 무시한다(`messages/*.txt` 가 trailing newline 으로 끝나든 말든 동일).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

MESSAGES_DIR = Path(__file__).resolve().parent.parent / "messages"
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """messages/<name>.txt 를 읽어 반환(치환 없음). CRLF→LF 정규화 + 끝의 개행 제거."""
    p = MESSAGES_DIR / f"{name}.txt"
    if not p.exists():
        raise FileNotFoundError(f"메시지 파일 없음: {p}")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")


def render(name: str, **values: object) -> str:
    """messages/<name>.txt 의 {{key}} 를 values[key] 로 치환해 반환. 안 채워진 키가 있으면 KeyError."""
    text = load(name)
    missing: list[str] = []

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return str(values[key])

    out = _PLACEHOLDER_RE.sub(_sub, text)
    if missing:
        raise KeyError(f"메시지 {name!r}: 안 채워진 placeholder {sorted(set(missing))}")
    return out
