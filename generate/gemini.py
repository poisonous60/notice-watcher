"""Gemini REST 클라이언트 (httpx). 별도 SDK 의존성 없이.

- 모델: 기본 `gemini-2.5-flash`. `GEMINI_MODEL` env 로 override (예: `gemini-3-flash-preview`, `gemini-flash-latest`).
- API 키: 여러 개 지원 + quota(429) 나면 다음 키로 자동 전환. 키 소스(우선순위):
    1. env `GEMINI_API_KEYS` — 쉼표/줄바꿈 구분 여러 개
    2. env `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` — 한 개
    3. 파일 — env `GEMINI_API_KEY_FILE` 경로, 없으면 `<repo>/GEMINI_API_KEY.md` (한 줄에 키 하나, 빈 줄/`#` 무시)
  한 프로세스 안에서 429 받은 키는 "소진"으로 표시해 이후 건너뜀. 전부 소진되면 명확히 에러.
- 출력: `responseMimeType=application/json` 으로 파싱 가능한 JSON 강제(우리 config 포맷은 동적 키/재귀라
  Gemini responseSchema 로 깔끔히 표현 못 함 → 프롬프트 + few-shot + 우리 validate_config 로 커버).
- thinking: `thinkingConfig.thinkingBudget=0` 시도 → 모델이 거부(400)하면 그 옵션 빼고 1회 재시도.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx


API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.5-flash"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_KEY_FILE = _REPO_ROOT / "GEMINI_API_KEY.md"


class GeminiError(RuntimeError):
    pass


def default_model() -> str:
    return os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)


def _split_keys(blob: str) -> list[str]:
    return [k.strip() for k in re.split(r"[,\n\r]+", blob) if k.strip() and not k.strip().startswith("#")]


def _load_keys() -> list[str]:
    keys: list[str] = []
    if os.environ.get("GEMINI_API_KEYS"):
        keys += _split_keys(os.environ["GEMINI_API_KEYS"])
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(env)
        if v and v.strip():
            keys.append(v.strip())
    if not keys:
        kf = os.environ.get("GEMINI_API_KEY_FILE")
        path = Path(kf) if kf else _DEFAULT_KEY_FILE
        if path.exists():
            keys += _split_keys(path.read_text(encoding="utf-8"))
    # dedupe, 순서 보존
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


class _KeyRing:
    """프로세스 전역 키 링 — 429 받은 키는 소진 표시 후 건너뜀."""

    def __init__(self) -> None:
        self._keys: Optional[list[str]] = None
        self._exhausted: set[int] = set()

    def _ensure(self) -> list[str]:
        if self._keys is None:
            self._keys = _load_keys()
            if not self._keys:
                raise GeminiError(
                    "Gemini API 키가 없습니다. 다음 중 하나로 설정하세요:\n"
                    "  - 환경변수 GEMINI_API_KEYS=키1,키2,... (여러 개)\n"
                    "  - 환경변수 GEMINI_API_KEY=키 (한 개)\n"
                    f"  - 파일 {_DEFAULT_KEY_FILE} 에 한 줄에 키 하나씩\n"
                    "키 발급: https://aistudio.google.com/apikey"
                )
        return self._keys

    def count(self) -> int:
        return len(self._ensure())

    def current_index(self) -> int:
        keys = self._ensure()
        for i in range(len(keys)):
            if i not in self._exhausted:
                return i
        raise GeminiError(f"모든 Gemini API 키({len(keys)}개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.")

    def current(self) -> tuple[int, str]:
        i = self.current_index()
        return i, self._ensure()[i]

    def mark_exhausted(self, idx: int) -> None:
        self._exhausted.add(idx)

    def reset(self) -> None:
        self._exhausted.clear()


_KEYRING = _KeyRing()


class GeminiClient:
    def __init__(self, *, model: Optional[str] = None, timeout: float = 120.0):
        self.model = model or default_model()
        self.timeout = timeout
        self._keyring = _KEYRING

    def _url(self, key: str) -> str:
        return f"{API_BASE}/models/{self.model}:generateContent?key={key}"

    @staticmethod
    def _build_body(*, system_instruction: str, user_text: str, temperature: float,
                    json_mode: bool, with_thinking_budget0: bool) -> dict:
        gen_cfg: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        if with_thinking_budget0:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
        return {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": gen_cfg,
        }

    def generate_text(self, *, system_instruction: str, user_text: str,
                      temperature: float = 0.2, json_mode: bool = True) -> str:
        n_keys = self._keyring.count()
        with_tb0 = True
        attempts_left = n_keys + 1  # 각 키 1회 + thinkingConfig 거부 시 한 번 더
        while attempts_left > 0:
            attempts_left -= 1
            idx, key = self._keyring.current()  # 전부 소진이면 여기서 GeminiError
            body = self._build_body(system_instruction=system_instruction, user_text=user_text,
                                    temperature=temperature, json_mode=json_mode, with_thinking_budget0=with_tb0)
            try:
                with httpx.Client(timeout=self.timeout) as c:
                    r = c.post(self._url(key), json=body, headers={"Content-Type": "application/json"})
            except httpx.HTTPError as e:
                raise GeminiError(f"Gemini 요청 실패(네트워크): {e}") from e

            if r.status_code == 200:
                return _extract_text(r.json())

            txt = r.text
            if r.status_code == 429 or ("RESOURCE_EXHAUSTED" in txt) or ("exceeded your current quota" in txt.lower()):
                if n_keys > 1:
                    print(f"  [gemini] 키 #{idx + 1}/{n_keys} quota 소진(429) → 다음 키로 전환")
                self._keyring.mark_exhausted(idx)
                attempts_left = max(attempts_left, n_keys)  # 남은 키들 다 시도하도록 보장
                continue
            if r.status_code == 400 and "thinking" in txt.lower() and with_tb0:
                with_tb0 = False
                attempts_left += 1
                continue
            raise GeminiError(f"Gemini API {r.status_code}: {txt[:600]}")
        raise GeminiError("Gemini 호출 실패(키 소진 또는 재시도 한도)")

    def generate_json(self, *, system_instruction: str, user_text: str, temperature: float = 0.2) -> Any:
        txt = self.generate_text(system_instruction=system_instruction, user_text=user_text,
                                 temperature=temperature, json_mode=True)
        return _parse_json_loose(txt)


def _extract_text(data: dict) -> str:
    cands = data.get("candidates") or []
    if not cands:
        raise GeminiError(f"응답에 candidates 없음 (promptFeedback={data.get('promptFeedback')})")
    c0 = cands[0]
    finish = c0.get("finishReason")
    parts = ((c0.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text:
        raise GeminiError(f"빈 응답 (finishReason={finish})")
    return text


def _parse_json_loose(text: str) -> Any:
    t = text.strip()
    if t.startswith("```"):
        seg = t.split("```")
        body = seg[1] if len(seg) >= 2 else text
        if body.lstrip().lower().startswith("json"):
            body = body.lstrip()[4:]
        t = body.strip().rstrip("`").strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                pass
        raise GeminiError(f"모델 응답을 JSON 으로 파싱 실패: {e}\n--- 응답 앞부분 ---\n{text[:800]}")
