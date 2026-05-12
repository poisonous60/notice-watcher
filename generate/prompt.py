"""Gemini 프롬프트 구성: 시스템 지침(포맷 스펙) + few-shot 예제 + digest → 프롬프트.

프롬프트 *본문* 은 repo 루트 `prompts/config_writer.*.txt` 에 산다 — 이 모듈은 거기에
런타임 값(transforms 목록, digest, HTML, 예제 config 등)을 채워 넣는 *조립 로직* 만 담는다.
(.prompts.render_prompt 가 `{{placeholder}}` 치환. notify 쪽 프롬프트도 같은 prompts/ 디렉터리.)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from engine import transform_names

from .prompts import render_prompt

_ROOT = Path(__file__).resolve().parent.parent
_CONFIGS_DIR = _ROOT / "configs"

# few-shot 으로 쓸 예제 config 들 (M1 에서 손으로 작성, 원본 어댑터와 결과 일치 검증됨).
_EXAMPLE_CONFIG_FILES = [
    "skku_cse_1582.json",      # httpx_html, concat, pick:first_matching, 페이지네이션 offset
    "dcinside_endfield.json",  # httpx_html, fallback chain, template, attr+match, notice 처리, polite_sleep 하한
    "endfield_official.json",  # httpx_json, list_path, success_when, unixtime_to_iso, article re_extract
]


def _transforms_doc() -> str:
    return ", ".join(transform_names())


# 시스템 지침(포맷 스펙) — 본문은 prompts/config_writer.system.txt, {{transforms_doc}} 만 여기서 채움.
SYSTEM_INSTRUCTION = render_prompt("config_writer.system", transforms_doc=_transforms_doc())


def _load_examples() -> str:
    blocks = []
    for fn in _EXAMPLE_CONFIG_FILES:
        p = _CONFIGS_DIR / fn
        if not p.exists():
            continue
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        blocks.append(f"### 예제: {cfg.get('site')} ({cfg.get('strategy')})\n```json\n{json.dumps(cfg, ensure_ascii=False, indent=2)}\n```")
    return "\n\n".join(blocks)


def build_user_prompt(digest: dict, *, max_html_chars: int = 120_000) -> str:
    """digest → 사용자 턴 텍스트. 큰 HTML 은 JSON-escape 대신 코드블록으로 따로 제시."""
    d = dict(digest)
    list_html = ((d.pop("list_html", {}) or {}))
    article = ((d.pop("article_sample", {}) or {}))
    api_cands = article.get("api_candidates") or []
    eh = d.pop("escalation_hint", None)  # 위 ⚠ 블록으로만 보여줌(meta JSON 중복 X)
    if eh:
        d["escalation_hint"] = "(위 '⚠ 중요 지침' 블록 참고)"
    lh = (list_html.get("html") or "")[:max_html_chars]
    ah = (article.get("html") or "")[:max_html_chars]

    meta = json.dumps(d, ensure_ascii=False, indent=2)
    examples = _load_examples()

    # probe 분석으로 미리 준 전략 hint(register.py preflight / --article-url). 재시도 시(build_retry_prompt)에도
    # 같은 hint 가 유지되고, "직전 시도가 무엇을 FAIL 했나" 는 build_retry_prompt 가 별도 블록(feedback)으로 붙인다.
    eh_block = f"\n## ⚠ 중요 지침 (probe 분석 — 반드시 따를 것)\n{eh}\n" if eh else ""
    api_block = ""
    if api_cands:
        api_block = (
            "\n## ⚡ 글 본문 JSON API 후보 (글 페이지가 SPA 라서 정적 HTML 본문이 비어있음 — 이 API 로 본문을 받아라)\n"
            "```json\n" + json.dumps(api_cands, ensure_ascii=False, indent=2) + "\n```\n"
            "→ article.url_template = 후보 url 의 글 ID 숫자를 {{post_id}} 로 치환한 것, article.fetch_kind=\"json\", "
            "article.content=[{{from:\"json\", path:<후보의 body_field_path 그대로>}}]. 필요하면 후보의 request_headers 중 "
            "X-Requested-With/Referer 를 config 최상위 headers 에 추가. 여러 개면 url_id_match=true·body_looks_html=true 우선.\n"
        )

    return render_prompt(
        "config_writer.user_skeleton",
        eh_block=eh_block,
        meta=meta,
        list_truncated_note=(", 잘림" if list_html.get("truncated") else ""),
        list_source=list_html.get("source"),
        list_html_text=lh,
        article_truncated_note=(", 잘림" if article.get("truncated") else ""),
        article_url=article.get("url"),
        article_html_text=ah,
        api_block=api_block,
        examples=examples,
    )


def build_retry_prompt(digest: dict, prev_config: dict, feedback_text: str, *, max_html_chars: int = 120_000) -> str:
    """재시도용: 원래 digest/HTML + 이전 config + 검증 실패 내역 → *수정된* config 요청."""
    base = build_user_prompt(digest, max_html_chars=max_html_chars)
    return render_prompt(
        "config_writer.retry_skeleton",
        base=base,
        prev_config=json.dumps(prev_config, ensure_ascii=False, indent=2),
        feedback=feedback_text,
    )
