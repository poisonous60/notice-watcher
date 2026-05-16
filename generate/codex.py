"""Codex CLI (subprocess) 클라이언트. `LLMClient` 구현.

ChatGPT Plus/Pro 구독 OAuth 쿼터 사용. `codex` 명령이 PATH 에 있어야 하고 `codex login` 으로
ChatGPT 인증이 끝나 있어야 한다 (`~/.codex/auth.json`).

호출 방식:
    echo "<system>\n\n---\n\n<user>" | codex exec --cd <tmpdir> --ephemeral
               --skip-git-repo-check -c model="<model>"
               -c model_reasoning_effort="<low|medium|high>"
               --output-last-message <file> --color never

- prompt **stdin 으로** 전달 (인자 X). Windows `codex.CMD` 가 prompt 인자에서 newline 이후를
  잘라먹는 batch 버그 회피. codex exec 는 PROMPT 인자 없으면 stdin 에서 읽음 (`codex exec --help`).
- `--cd <tmpdir>` : 빈 dir 강제 → codex 가 repo 컨텍스트 / AGENTS.md / git log 안 읽음 → system prompt
  overhead 4K~ 으로 감소 (repo 안에서 호출하면 25K+).
- `--ephemeral`   : 세션 파일 안 만듦.
- `--output-last-message` : 모델의 마지막 메시지를 파일로. stdout 의 헤더/reasoning trace 파싱 X.

reasoning effort 매핑:
- 모델명에 `-mini` / `-nano` 포함 → "low"
- 그 외 (`gpt-5.4`, `gpt-5.4-codex` 등) → "high"

비용/토큰:
- Plus 구독은 메시지 가중치 한도 (5h 윈도우). raw token 청구 X.
- stdout 의 `tokens used\nN` 라인에서 total_tokens 만 best-effort 추출.
- prompt/completion 분리 정보 없음 → 둘 다 0.

에러 매핑:
- subprocess timeout → LLMNetworkError
- exit != 0 → stderr 에 "rate" / "quota" / "429" / "limit" 매칭 → LLMQuotaError, 아니면 LLMHttpError
- 빈 output 파일 → LLMParseError
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

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


def _reasoning_effort_for(model: str) -> str:
    m = model.lower()
    if "-mini" in m or "-nano" in m:
        return "low"
    return "high"


def _classify_error(stderr: str, stdout: str, returncode: int) -> LLMError:
    blob = (stderr + "\n" + stdout).lower()
    if any(t in blob for t in ("rate limit", "quota", "exceeded", "429", "too many requests")):
        return LLMQuotaError(f"codex quota/rate limit (rc={returncode}): {stderr[:400]}")
    return LLMHttpError(f"codex exec failed (rc={returncode}): {stderr[:600]}", status_code=returncode or 1)


class CodexClient(LLMClient):
    provider = "codex"

    def __init__(self, *, model: str = "gpt-5.4-mini", timeout: float = _DEFAULT_TIMEOUT,
                 recorder=None, cost_fn=None) -> None:
        super().__init__(model=model, recorder=recorder, cost_fn=cost_fn)
        self.timeout = timeout

    def _do_request(self, *, system_instruction: str, user_text: str,
                    temperature: float, json_mode: bool) -> LLMResponse:
        # temperature 는 codex 가 직접 받지 않음 (model_reasoning_effort 로 대체). 무시.
        # json_mode: 호출 측 prompt 가 "JSON 만 출력" 명시한다는 전제로 별도 schema 강제 X.
        bin_path = _codex_bin()
        reasoning = _reasoning_effort_for(self.model)
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

            try:
                text = out_path.read_text(encoding="utf-8").strip()
            except OSError as e:
                raise LLMParseError(f"codex output-last-message 파일 읽기 실패: {e}") from e
            if not text:
                raise LLMParseError(
                    f"codex 응답이 비어있음 (rc={proc.returncode}, stderr 마지막: {proc.stderr[-300:]!r})"
                )

            total_tokens = 0
            m = _TOKEN_LINE_RE.search(proc.stderr) or _TOKEN_LINE_RE.search(proc.stdout)
            if m:
                try:
                    total_tokens = int(m.group(1).replace(",", ""))
                except ValueError:
                    total_tokens = 0
            else:
                # regex 안 잡히면 codex 버전마다 포맷 다를 수 있음 — 추후 조정용 경고.
                tail = (proc.stderr[-200:] or proc.stdout[-200:]).replace("\n", " | ")
                print(f"  [codex] WARN: token line not parsed — tail={tail!r}")

            return LLMResponse(
                text=text,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=total_tokens,
                raw_model=self.model,
                key_idx=None,
            )


__all__ = ["CodexClient"]
