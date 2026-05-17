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
from engine.tracing import current_trace
from .gemini import GeminiClient, GeminiError, _parse_json_loose
from .llm_base import LLMClient, LLMError
from .prices import compute_cost
from .usage_recorder import get_default_recorder
from .routing import client_for
from .prompt import SYSTEM_INSTRUCTION, build_user_prompt, build_retry_prompt
from .validate import validate_built_config, ValidationReport


class GenerationError(RuntimeError):
    pass


def _enrich_retry_feedback(rep, prev_cfg: Optional[dict], digest: dict, attempt_history: list[dict]) -> str:
    """retry prompt 에 들어갈 풍부한 feedback. rep.feedback_text() 베이스 + 세 가지 보강.

    1. 직전 시도 cfg 의 핵심 selector/strategy echo — LLM 이 자기가 뭐 박았는지 잊지 않도록.
    2. probe 가 본 정적 HTML 의 top 3 repeating patterns 후보 재표시 — 125k digest 안에 묻혀 LLM
       이 못 찾는 selector 후보를 *눈에 띄게* 다시 제시.
    3. attempt history — 직전 시도들이 박은 strategy/row_selector 누적. 같은 방향 반복 차단.

    같은 모델(gpt-5.4-mini)이 같은 prompt 에 같은 실수 반복하던 문제(retry 회복률 ~17%) 완화.
    """
    base = rep.feedback_text() if rep is not None else ""
    parts: list[str] = [base] if base else []

    # (1) 직전 시도 cfg 핵심 필드 echo
    if isinstance(prev_cfg, dict) and prev_cfg:
        lst = prev_cfg.get("list") or {}
        art = prev_cfg.get("article") or {}
        strat = prev_cfg.get("strategy")
        rows = lst.get("row_selector") or lst.get("rows") or lst.get("list_path")
        art_content = art.get("content") or art.get("body_selector")
        parts.append(
            "\n### 직전 시도가 박은 핵심 필드 (똑같이 박지 마라)\n"
            f"  strategy: {strat!r}\n"
            f"  list.row_selector / list_path: {rows!r}\n"
            f"  list.url_template: {lst.get('url_template')!r}\n"
            f"  article.fetch_kind: {art.get('fetch_kind')!r}\n"
            f"  article.content selector: {art_content!r}\n"
            f"  article.url_template: {art.get('url_template')!r}\n"
            f"  → 위 selector/strategy 로 검증 실패했다. 같은 selector 살짝 변형은 똑같이 실패한다 — "
            "**방향 자체**(strategy 또는 selector 의 root 컨테이너)를 바꿔라."
        )

    # (2) probe 정적 HTML top 반복 패턴 후보 재표시 (LLM 이 못 찾던 selector 후보)
    lc = digest.get("list_candidates") or {}
    pats = lc.get("html_repeating_patterns") or []
    if pats:
        top = sorted(pats, key=lambda p: int(p.get("child_count") or 0), reverse=True)[:3]
        lines = ["\n### probe 정적 HTML 의 반복 패턴 후보 top 3 (selector 다시 검토)"]
        for p in top:
            lines.append(
                f"  - selector={p.get('selector')!r}  child_count={p.get('child_count')}  "
                f"href_pattern_guess={p.get('href_pattern_guess')!r}  sample_url={p.get('sample_url')!r}"
            )
        lines.append(
            "  → 같은 호스트 글 링크(`href_pattern_guess` / `sample_url`) 가진 게 진짜 보드 후보. "
            "nav/footer/sidebar 패턴은 건너뛰어라. 정적 HTML 에 없으면 strategy=playwright_html."
        )
        parts.append("\n".join(lines))

    # (3) attempt history — 누적 시도된 strategy/selector
    if len(attempt_history) >= 1:
        lines = [f"\n### 직전 {len(attempt_history)} 회 시도 누적 (같은 방향 X)"]
        for h in attempt_history:
            lines.append(
                f"  attempt {h['n']}: strategy={h.get('strategy')!r}  "
                f"row_selector/list_path={h.get('rows')!r}  fails={h.get('fails')!r}"
            )
        # 같은 hard fail 반복 감지
        all_fails = [tuple(sorted(h.get("fails") or [])) for h in attempt_history]
        if len(all_fails) >= 2 and len(set(all_fails)) == 1:
            lines.append(
                "  ⚠ 직전 시도들 모두 *같은 hard fail* 만 일으킴 — 같은 방향으론 절대 안 풀린다. "
                "selector 미세 조정 대신 strategy 자체 또는 selector root 를 바꿔라. "
                "본문 fail 반복이면 article.body_empty_acceptable:true 검토."
            )
        parts.append("\n".join(lines))

    return "\n".join(parts) if parts else ""


def _patch_minimal(cfg: dict, digest: dict) -> dict:
    if not isinstance(cfg, dict):
        raise GenerationError(f"모델이 JSON 객체가 아닌 걸 반환: {type(cfg).__name__}")
    if not cfg.get("site"):
        cfg["site"] = urlsplit(digest.get("url") or "").netloc or "unknown"
    cfg.setdefault("version", 1)
    if not cfg.get("board"):
        cfg["board"] = "default"
    return cfg


def _slug_from_digest(digest: dict) -> Optional[str]:
    """digest 에 slug 직접 키가 있으면 그걸, 없으면 url netloc 기반 fallback. usage 기록의 차원용."""
    s = digest.get("slug")
    if isinstance(s, str) and s:
        return s
    url = digest.get("url")
    if isinstance(url, str) and url:
        return urlsplit(url).netloc or None
    return None


def _generate_raw(digest: dict, *, client: LLMClient, prompt_text: str, temperature: float,
                  call_site: str, attempt: int) -> dict:
    try:
        resp = client.generate(system_instruction=SYSTEM_INSTRUCTION, user_text=prompt_text,
                               temperature=temperature, json_mode=True,
                               call_site=call_site, slug=_slug_from_digest(digest), attempt=attempt)
        cfg = _parse_json_loose(resp.text)
    except LLMError as e:
        raise GenerationError(f"gemini 호출/파싱 실패: {e}") from e
    return _patch_minimal(cfg, digest)


def generate_config(digest: dict, *, client: Optional[LLMClient] = None,
                    model: Optional[str] = None, temperature: float = 0.2) -> dict:
    """1-shot. 스키마 검증 통과한 config 반환. 실패 시 GenerationError. (실행 검증은 안 함 — generate_config_validated 사용.)

    `model` 인자는 CLI `--model` 호환용 — 지정 시 routing.json 무시하고 그 모델 사용 (provider=gemini 기본).
    """
    cli = client or client_for("config_generate", override=(f"gemini:{model}" if model else None))
    cfg = _generate_raw(digest, client=cli, prompt_text=build_user_prompt(digest),
                        temperature=temperature, call_site="config_generate", attempt=1)
    try:
        validate_config(cfg)
    except ConfigError as e:
        raise GenerationError(f"생성된 config 가 스키마 검증 실패:\n{e}") from e
    return cfg


async def generate_config_validated(
    digest: dict,
    *,
    client: Optional[LLMClient] = None,
    model: Optional[str] = None,
    temperature: float = 0.25,
    max_attempts: int = 4,
    fetch_articles: int = 1,
    inter_attempt_sleep: float = 2.0,
    on_attempt: Optional[Callable[[int, Optional[dict], Optional[ValidationReport], bool, str], None]] = None,
) -> tuple[dict, ValidationReport]:
    """생성 → 실행검증 → 실패 시 피드백 재생성, ≤max_attempts. 성공 (config, report) 반환. 전부 실패 시 GenerationError.

    on_attempt(i, cfg_or_None, report_or_None, ok, msg) — 진행 로깅용 콜백.

    `client` 가 None 이면 i==1 은 config_generate routing, i>=2 는 config_retry routing 사용 (routing.json).
    `model` 명시되면 모든 attempt 가 그 모델 사용 (CLI override).
    """
    override = f"gemini:{model}" if model else None
    prev_cfg: Optional[dict] = None
    prev_feedback: str = ""
    attempt_history: list[dict] = []  # _enrich_retry_feedback (3) — 누적 시도 strategy/selector/fails
    tr = current_trace()

    for i in range(1, max_attempts + 1):
        print(f"[PHASE] gemini_attempt {i}/{max_attempts}", flush=True)
        with tr.span("gemini_attempt", attrs={"attempt": i, "max_attempts": max_attempts}):
            if i == 1:
                prompt_text = build_user_prompt(digest)
            else:
                prompt_text = build_retry_prompt(digest, prev_cfg or {}, prev_feedback)

            # i==1 은 신규 생성, i>=2 는 retry 라운드 (다른 모델 라우팅 가능하도록 call_site 분리).
            call_site = "config_generate" if i == 1 else "config_retry"
            cli = client or client_for(call_site, override=override)
            try:
                with tr.span("gemini_call", attrs={"attempt": i, "call_site": call_site}):
                    cfg = _generate_raw(digest, client=cli, prompt_text=prompt_text, temperature=temperature,
                                        call_site=call_site, attempt=i)
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
                with tr.span("schema_validate", attrs={"attempt": i}):
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
                with tr.span("validate_built_config", attrs={"attempt": i, "fetch_articles": fetch_articles}):
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
            # history 누적 — 다음 attempt feedback 의 (3) 분기용
            _lst = cfg.get("list") or {}
            attempt_history.append({
                "n": i,
                "strategy": cfg.get("strategy"),
                "rows": _lst.get("row_selector") or _lst.get("list_path"),
                "fails": [c.name for c in rep.hard_failures()],
            })
            prev_cfg = cfg
            prev_feedback = _enrich_retry_feedback(rep, prev_cfg, digest, attempt_history)
            if i < max_attempts:
                await asyncio.sleep(inter_attempt_sleep)

    err = GenerationError(f"{max_attempts}회 시도 모두 실패. 마지막 피드백:\n{prev_feedback}")
    err.last_config = prev_cfg  # type: ignore[attr-defined]
    err.last_feedback = prev_feedback  # type: ignore[attr-defined]
    raise err
