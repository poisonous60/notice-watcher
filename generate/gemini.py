"""Gemini REST 클라이언트 (httpx). `LLMClient` 구현.

- 모델: 기본 `gemini-2.5-flash`. `GEMINI_MODEL` env 로 override.
- API 키: 여러 개 지원. **호출마다 시작 키를 한 칸씩 굴려(라운드로빈)** 부하 분산. quota(429) 받은 키는
  소진 표시 후 다음 키로 자동 전환(한 호출 안에서 링을 한 바퀴까지). 순환 커서는
  `<repo>/output/state/gemini_key_cursor` 에 영구 저장 → 프로세스 재시작/매일 폴링마다 1번 키로 안 돌아감.
  키 소스(우선순위):
    1. env `GEMINI_API_KEYS` — 쉼표/줄바꿈 구분 여러 개
    2. env `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` — 한 개
    3. 파일 — env `GEMINI_API_KEY_FILE` 경로, 없으면 `<repo>/GEMINI_API_KEY.md` (한 줄에 키 하나, 빈 줄/`#` 무시)
- 출력: `responseMimeType=application/json` 으로 파싱 가능한 JSON 강제(스키마는 prompt + validate 로 커버).
- thinking: `thinkingConfig.thinkingBudget=0` 시도 → 모델이 거부(400)하면 옵션 빼고 1회 재시도.
- 호환: 구 `generate_text` / `generate_json` 메서드 유지 (PR2 까지 caller 점진 이전).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from .llm_base import (
    LLMClient, LLMResponse,
    LLMError, LLMNetworkError, LLMQuotaError, LLMHttpError, LLMParseError,
)


API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.5-flash"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_KEY_FILE = _REPO_ROOT / "GEMINI_API_KEY.md"
_CURSOR_FILE = _REPO_ROOT / "output" / "state" / "gemini_key_cursor"


class GeminiError(LLMError):
    """레거시 alias. 새 코드는 LLMError 계열 catch."""


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
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _read_cursor() -> int:
    try:
        return int((_CURSOR_FILE.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        return 0


def _write_cursor(n: int) -> None:
    try:
        _CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CURSOR_FILE.write_text(str(n % 1_000_000_000), encoding="utf-8")
    except OSError:
        pass


class _KeyRing:
    """프로세스 전역 키 링."""

    def __init__(self) -> None:
        self._keys: Optional[list[str]] = None
        self._exhausted: set[int] = set()
        self._start: int = 0

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

    def rotate_start(self) -> None:
        n = self.count()
        if n <= 1:
            self._start = 0
            return
        c = _read_cursor()
        self._start = c % n
        _write_cursor(c + 1)

    def current_index(self) -> int:
        keys = self._ensure()
        n = len(keys)
        for off in range(n):
            i = (self._start + off) % n
            if i not in self._exhausted:
                return i
        raise LLMQuotaError(f"모든 Gemini API 키({n}개) quota 소진. 잠시 후 재시도하거나 키를 추가하세요.")

    def current(self) -> tuple[int, str]:
        i = self.current_index()
        return i, self._ensure()[i]

    def mark_exhausted(self, idx: int) -> None:
        self._exhausted.add(idx)

    def reset(self) -> None:
        self._exhausted.clear()


_KEYRING = _KeyRing()


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, *, model: Optional[str] = None, timeout: float = 120.0,
                 recorder=None, cost_fn=None) -> None:
        super().__init__(model=model or default_model(), recorder=recorder, cost_fn=cost_fn)
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

    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        self._keyring.rotate_start()
        n_keys = self._keyring.count()
        with_tb0 = True
        attempts_left = n_keys + 1
        last_key_idx = None
        while attempts_left > 0:
            attempts_left -= 1
            idx, key = self._keyring.current()
            last_key_idx = idx
            body = self._build_body(system_instruction=system_instruction, user_text=user_text,
                                    temperature=temperature, json_mode=json_mode,
                                    with_thinking_budget0=with_tb0)
            try:
                with httpx.Client(timeout=self.timeout) as c:
                    r = c.post(self._url(key), json=body, headers={"Content-Type": "application/json"})
            except httpx.HTTPError as e:
                raise LLMNetworkError(f"Gemini 요청 실패(네트워크): {e}") from e

            if r.status_code == 200:
                return _parse_response(r.json(), key_idx=idx, fallback_model=self.model)

            txt = r.text
            if r.status_code == 429 or ("RESOURCE_EXHAUSTED" in txt) or ("exceeded your current quota" in txt.lower()):
                if n_keys > 1:
                    print(f"  [gemini] 키 #{idx + 1}/{n_keys} quota 소진(429) → 다음 키로 전환")
                self._keyring.mark_exhausted(idx)
                attempts_left = max(attempts_left, n_keys)
                continue
            if r.status_code == 400 and "thinking" in txt.lower() and with_tb0:
                with_tb0 = False
                attempts_left += 1
                continue
            raise LLMHttpError(f"Gemini API {r.status_code}: {txt[:600]}", status_code=r.status_code)
        raise LLMQuotaError(f"Gemini 호출 실패(키 소진 또는 재시도 한도) last_key_idx={last_key_idx}")

    # ---- 레거시 호환: 기존 caller 가 점진 이전될 때까지 유지 ---- #
    def generate_text(self, *, system_instruction: str, user_text: str,
                      temperature: float = 0.2, json_mode: bool = True) -> str:
        resp = self.generate(system_instruction=system_instruction, user_text=user_text,
                             temperature=temperature, json_mode=json_mode,
                             call_site="legacy")
        return resp.text

    def generate_json(self, *, system_instruction: str, user_text: str, temperature: float = 0.2) -> Any:
        txt = self.generate_text(system_instruction=system_instruction, user_text=user_text,
                                 temperature=temperature, json_mode=True)
        return _parse_json_loose(txt)


def _parse_response(data: dict, *, key_idx: Optional[int], fallback_model: str) -> LLMResponse:
    cands = data.get("candidates") or []
    if not cands:
        raise LLMParseError(f"응답에 candidates 없음 (promptFeedback={data.get('promptFeedback')})")
    c0 = cands[0]
    finish = c0.get("finishReason")
    parts = ((c0.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text:
        raise LLMParseError(f"빈 응답 (finishReason={finish})")
    um = data.get("usageMetadata") or {}
    pt = int(um.get("promptTokenCount") or 0)
    ct = int(um.get("candidatesTokenCount") or 0)
    tt = int(um.get("totalTokenCount") or (pt + ct))
    raw_model = str(data.get("modelVersion") or fallback_model)
    return LLMResponse(
        text=text,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        raw_model=raw_model,
        key_idx=key_idx,
    )


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
    except json.JSONDecodeError as first_err:
        # 1차 fallback: outer braces 만 잘라 재시도 (prose 둘러싸인 케이스).
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                pass
        # 2차 fallback: json_repair — 빠진 `,` / 닫히지 않은 `"`/`{`/`[` / trailing comma 등
        # 1~몇 글자 누락 복구. codex(gpt-5.4-mini) 가 큰 응답에서 자주 깨는 케이스 회수용
        # (2026-05-24 govinfo job#1702: line 1 col 2556 `,` 누락 같은 사례).
        # 위험: 복구 결과가 모델 의도와 미세하게 다를 수 있음 — `[json_repair]` print 로 surface
        # 해서 운영자가 확인 가능. validate 단계가 schema 위반 잡으면 retry round 로 회복.
        try:
            import json_repair  # 지연 import — 의존성 없는 환경에서도 1차 path 살림.
        except ImportError:
            json_repair = None
        if json_repair is not None:
            try:
                repaired = json_repair.loads(t)
            except Exception:  # noqa: BLE001 — repair 자체 예외도 그냥 fall through
                repaired = None
            # repair 가 garbage 받으면 `""` 반환 — dict/list 그리고 비어있지 않은 것만 채택.
            if isinstance(repaired, (dict, list)) and repaired:
                print(f"  [json_repair] 모델 응답 JSON 복구 성공 (orig err: {first_err.msg} @ char {first_err.pos})")
                return repaired
        raise LLMParseError(f"모델 응답을 JSON 으로 파싱 실패: {first_err}\n--- 응답 앞부분 ---\n{text[:800]}")
