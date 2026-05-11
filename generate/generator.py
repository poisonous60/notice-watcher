"""digest → config 생성 오케스트레이션.

- generate_config(digest)             : 1-shot — gemini → JSON → validate_config(스키마). M3 용.
- generate_config_validated(digest)   : M5 — 생성 → 실행검증(validate.py 3층위) → 실패면 피드백 재생성(≤max_attempts).
                                         2라운드부터는 "이전 config + 무엇이 실패했나 + 실제 추출 데이터" 를 주고 *수정* 요청(= 사실상 partial regen).
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional
from urllib.parse import urlsplit

from engine import validate_config, ConfigError
from .gemini import GeminiClient, GeminiError
from .prompt import SYSTEM_INSTRUCTION, build_user_prompt, build_retry_prompt
from .validate import validate_built_config, ValidationReport


class GenerationError(RuntimeError):
    pass


def _patch_minimal(cfg: dict, digest: dict) -> dict:
    if not isinstance(cfg, dict):
        raise GenerationError(f"모델이 JSON 객체가 아닌 걸 반환: {type(cfg).__name__}")
    if not cfg.get("site"):
        cfg["site"] = urlsplit(digest.get("url") or "").netloc or "unknown"
    cfg.setdefault("version", 1)
    if not cfg.get("board"):
        cfg["board"] = "default"
    return cfg


def _generate_raw(digest: dict, *, client: GeminiClient, prompt_text: str, temperature: float) -> dict:
    try:
        cfg = client.generate_json(system_instruction=SYSTEM_INSTRUCTION, user_text=prompt_text, temperature=temperature)
    except GeminiError as e:
        raise GenerationError(f"gemini 호출/파싱 실패: {e}") from e
    return _patch_minimal(cfg, digest)


def generate_config(digest: dict, *, client: Optional[GeminiClient] = None,
                    model: Optional[str] = None, temperature: float = 0.2) -> dict:
    """1-shot. 스키마 검증 통과한 config 반환. 실패 시 GenerationError. (실행 검증은 안 함 — generate_config_validated 사용.)"""
    cli = client or GeminiClient(model=model)
    cfg = _generate_raw(digest, client=cli, prompt_text=build_user_prompt(digest), temperature=temperature)
    try:
        validate_config(cfg)
    except ConfigError as e:
        raise GenerationError(f"생성된 config 가 스키마 검증 실패:\n{e}") from e
    return cfg


async def generate_config_validated(
    digest: dict,
    *,
    client: Optional[GeminiClient] = None,
    model: Optional[str] = None,
    temperature: float = 0.25,
    max_attempts: int = 4,
    fetch_articles: int = 1,
    inter_attempt_sleep: float = 2.0,
    on_attempt: Optional[Callable[[int, Optional[dict], Optional[ValidationReport], bool, str], None]] = None,
) -> tuple[dict, ValidationReport]:
    """생성 → 실행검증 → 실패 시 피드백 재생성, ≤max_attempts. 성공 (config, report) 반환. 전부 실패 시 GenerationError.

    on_attempt(i, cfg_or_None, report_or_None, ok, msg) — 진행 로깅용 콜백.
    """
    cli = client or GeminiClient(model=model)
    prev_cfg: Optional[dict] = None
    prev_feedback: str = ""

    for i in range(1, max_attempts + 1):
        if i == 1:
            prompt_text = build_user_prompt(digest)
        else:
            prompt_text = build_retry_prompt(digest, prev_cfg or {}, prev_feedback)

        try:
            cfg = _generate_raw(digest, client=cli, prompt_text=prompt_text, temperature=temperature)
        except GenerationError as e:
            msg = f"생성 실패: {e}"
            if on_attempt:
                on_attempt(i, None, None, False, msg)
            prev_cfg, prev_feedback = (prev_cfg or {}), (prev_feedback + f"\n(직전 시도 생성 실패: {e})")
            if i < max_attempts:
                await asyncio.sleep(inter_attempt_sleep)
            continue

        # 스키마 검증
        try:
            validate_config(cfg)
        except ConfigError as e:
            msg = f"스키마 검증 실패: {e}"
            if on_attempt:
                on_attempt(i, cfg, None, False, msg)
            prev_cfg = cfg
            prev_feedback = f"config 가 스키마 검증에 실패했다. 반드시 고쳐라:\n{e}"
            if i < max_attempts:
                await asyncio.sleep(inter_attempt_sleep)
            continue

        # 실행 검증 (3층위)
        try:
            rep = await validate_built_config(cfg, digest=digest, fetch_articles=fetch_articles)
        except Exception as e:  # validate 자체 예외(드뭄)
            msg = f"검증 중 예외: {type(e).__name__}: {e}"
            if on_attempt:
                on_attempt(i, cfg, None, False, msg)
            prev_cfg = cfg
            prev_feedback = f"이 config 를 실행하다 예외가 났다: {type(e).__name__}: {e}"
            if i < max_attempts:
                await asyncio.sleep(inter_attempt_sleep)
            continue

        if rep.ok:
            warn = rep.soft_failures()
            msg = f"통과 ({rep.n_posts}건" + (f", 경고 {len(warn)}" if warn else "") + ")"
            if on_attempt:
                on_attempt(i, cfg, rep, True, msg)
            return cfg, rep

        msg = "하드 실패: " + "; ".join(f"{c.name}({c.detail})" for c in rep.hard_failures())
        if on_attempt:
            on_attempt(i, cfg, rep, False, msg)
        prev_cfg = cfg
        prev_feedback = rep.feedback_text()
        if i < max_attempts:
            await asyncio.sleep(inter_attempt_sleep)

    err = GenerationError(f"{max_attempts}회 시도 모두 실패. 마지막 피드백:\n{prev_feedback}")
    err.last_config = prev_cfg  # type: ignore[attr-defined]
    err.last_feedback = prev_feedback  # type: ignore[attr-defined]
    raise err
