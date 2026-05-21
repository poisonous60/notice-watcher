"""Codex CLI (subprocess) 클라이언트. `LLMClient` 구현.

ChatGPT Plus/Pro 구독 OAuth 쿼터 사용. `codex` 명령이 PATH 에 있어야 하고 `codex login` 으로
ChatGPT 인증이 끝나 있어야 한다 (`~/.codex/auth.json`).

호출 방식:
    echo "<system>\n\n---\n\n<user>" | codex exec --cd <tmpdir> --ephemeral
               --skip-git-repo-check -c model=<model>
               -c model_reasoning_effort=<low|medium|high>
               --output-last-message <file> --color never --json

- prompt **stdin 으로** 전달 (인자 X). Windows `codex.CMD` 가 prompt 인자에서 newline 이후를
  잘라먹는 batch 버그 회피. codex exec 는 PROMPT 인자 없으면 stdin 에서 읽음 (`codex exec --help`).
- `--cd <tmpdir>` : 빈 dir 강제 → codex 가 repo 컨텍스트 / AGENTS.md / git log 안 읽음 → system prompt
  overhead 4K~ 으로 감소 (repo 안에서 호출하면 25K+).
- `--ephemeral`   : 세션 파일 안 만듦.
- `--output-last-message` : 모델의 마지막 메시지를 파일로 — robust 본문 추출 (--json 깨져도 fallback).
- `--json`        : stdout 에 JSONL event stream. `turn.completed.usage` 에서 input/output 토큰 분리 추출.

reasoning effort 매핑:
- 모델명에 `-mini` / `-nano` 포함 → "low"
- 그 외 (`gpt-5.4`, `gpt-5.4-codex` 등) → "high"

비용/토큰:
- Plus 구독은 메시지 가중치 한도 (5h 윈도우). raw token 청구 X.
- `--json` event stream 의 `turn.completed.usage` 에서 input/output 분리 추출:
  · prompt_tokens   = input_tokens
  · completion_tokens = output_tokens
  · total_tokens    = input + output
- 추출 실패 시 stderr 의 `tokens used\nN` 라인에서 total_tokens 만 fallback.

에러 매핑:
- subprocess timeout → LLMNetworkError
- exit != 0 → stderr 에 "rate" / "quota" / "429" / "limit" 매칭 → LLMQuotaError, 아니면 LLMHttpError
- 빈 output 파일 → LLMParseError
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from .llm_base import (
    LLMClient, LLMResponse,
    LLMError, LLMNetworkError, LLMQuotaError, LLMHttpError, LLMParseError,
)


_CODEX_BIN_ENV = "CODEX_BIN"
_DEFAULT_TIMEOUT = 240.0  # config_generate reasoning 길어질 수 있어 4분
_TOKEN_LINE_RE = re.compile(r"tokens used\s*\n\s*([\d,]+)", re.IGNORECASE)


def _codex_bin() -> str:
    """codex 실행 파일 경로. CODEX_BIN env > PATH 검색."""
    bin_path = os.environ.get(_CODEX_BIN_ENV)
    if bin_path and Path(bin_path).exists():
        return bin_path
    found = shutil.which("codex")
    if not found:
        raise LLMError(
            "codex CLI 를 찾을 수 없습니다. `npm install -g @openai/codex` 로 설치하고 "
            "`codex login` 인증을 마치세요. (또는 CODEX_BIN 환경변수에 경로 지정.)"
        )
    return found


_VALID_EFFORTS = ("low", "medium", "high")


def _reasoning_effort_for(model: str) -> str:
    m = model.lower()
    if "-mini" in m or "-nano" in m:
        return "low"
    return "high"


def _extract_usage_from_jsonl(stdout: str) -> Optional[Tuple[int, int]]:
    """`--json` event stream 의 `turn.completed.usage` 에서 (input_tokens, output_tokens) 추출.

    형식 예: {"type": "turn.completed", "usage": {"input_tokens": N, "output_tokens": M, ...}}
    여러 turn 있을 수 있음 — 마지막 것 사용.
    """
    last: Optional[Tuple[int, int]] = None
    for line in stdout.splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "turn.completed":
            usage = ev.get("usage") or {}
            try:
                last = (int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
            except (TypeError, ValueError):
                continue
    return last


def _extract_last_message_from_jsonl(stdout: str) -> Optional[str]:
    """`item.completed` 중 `type=agent_message` 의 마지막 `text`. --output-last-message 파일 보조."""
    last_text: Optional[str] = None
    for line in stdout.splitlines():
        s = line.strip()
        if not s or not s.startswith("{"):
            continue
        try:
            ev = json.loads(s)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message":
                last_text = item.get("text") or last_text
    return last_text


def _classify_error(stderr: str, stdout: str, returncode: int) -> LLMError:
    blob = (stderr + "\n" + stdout).lower()
    if any(t in blob for t in ("rate limit", "quota", "exceeded", "429", "too many requests")):
        return LLMQuotaError(f"codex quota/rate limit (rc={returncode}): {stderr[:400]}")
    return LLMHttpError(f"codex exec failed (rc={returncode}): {stderr[:600]}", status_code=returncode or 1)


class CodexClient(LLMClient):
    provider = "codex"

    def __init__(self, *, model: str = "gpt-5.4-mini",
                 reasoning_effort: Optional[str] = None, timeout: float = _DEFAULT_TIMEOUT,
                 recorder=None, cost_fn=None) -> None:
        super().__init__(model=model, recorder=recorder, cost_fn=cost_fn)
        self.timeout = timeout
        # 명시 effort 가 valid 면 모델명 기반 자동 추론(_reasoning_effort_for)을 override.
        eff = (reasoning_effort or "").strip().lower()
        self.reasoning_effort = eff if eff in _VALID_EFFORTS else None

    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        # temperature 는 codex 가 직접 받지 않음 (model_reasoning_effort 로 대체). 무시.
        # json_mode: 호출 측 prompt 가 "JSON 만 출력" 명시한다는 전제로 별도 schema 강제 X.
        bin_path = _codex_bin()
        reasoning = self.reasoning_effort or _reasoning_effort_for(self.model)
        prompt = f"{system_instruction}\n\n---\n\n{user_text}"

        with tempfile.TemporaryDirectory(prefix="codex_workdir_") as workdir:
            # out file 을 workdir 안에 두면 TemporaryDirectory cleanup 이 한 번에 처리 →
            # Windows 의 unlink race 회피.
            out_path = Path(workdir) / "last_message.txt"
            args = [
                bin_path, "exec",
                "--cd", workdir,
                "--ephemeral",
                "--skip-git-repo-check",
                "--color", "never",
                "-c", f"model={self.model}",
                "-c", f"model_reasoning_effort={reasoning}",
                "--output-last-message", str(out_path),
                "--json",
            ]
            try:
                proc = subprocess.run(
                    args,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise LLMNetworkError(f"codex exec timeout after {self.timeout}s") from e
            except OSError as e:
                raise LLMNetworkError(f"codex exec OSError: {e}") from e

            if proc.returncode != 0:
                raise _classify_error(proc.stderr, proc.stdout, proc.returncode)

            # 본문 추출 — output-last-message 파일 우선, 빈 경우 JSONL event stream 에서.
            text = ""
            try:
                text = out_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            if not text:
                jsonl_text = _extract_last_message_from_jsonl(proc.stdout)
                if jsonl_text:
                    text = jsonl_text.strip()
            if not text:
                raise LLMParseError(
                    f"codex 응답이 비어있음 (rc={proc.returncode}, stderr 마지막: {proc.stderr[-300:]!r})"
                )

            # 토큰 추출 — JSONL event 의 turn.completed.usage 우선 (input/output 분리).
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            usage = _extract_usage_from_jsonl(proc.stdout)
            if usage is not None:
                prompt_tokens, completion_tokens = usage
                total_tokens = prompt_tokens + completion_tokens
            else:
                # fallback: stderr 의 "tokens used\nN" 라인만 — total 만 잡힘.
                m = _TOKEN_LINE_RE.search(proc.stderr) or _TOKEN_LINE_RE.search(proc.stdout)
                if m:
                    try:
                        total_tokens = int(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
                else:
                    tail = (proc.stderr[-200:] or proc.stdout[-200:]).replace("\n", " | ")
                    print(f"  [codex] WARN: token usage not parsed — tail={tail!r}")

            return LLMResponse(
                text=text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                raw_model=self.model,
                key_idx=None,
            )


__all__ = ["CodexClient"]
