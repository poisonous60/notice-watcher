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
# ※ config rename/제거 시 갱신 필수 — _load_examples 가 missing file 발견 시 raise 함 (silent skip X).
_EXAMPLE_CONFIG_FILES = [
    "skku_cse_1582.json",                          # httpx_html, concat, pick:first_matching, 페이지네이션 offset
    "dcinside_endfield.json",                      # httpx_html, fallback chain, template, attr+match, notice 처리, polite_sleep 하한
    "host_web-news-gryphl_api_53675aad.json",      # httpx_json, list_path, success_when, unixtime_to_iso, article re_extract (구 endfield_official.json — commit 9de6977 slug schema rename)
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
            # silent skip 금지 — few-shot 누락은 LLM 한테 silent rot.
            # rename/제거 됐으면 _EXAMPLE_CONFIG_FILES 갱신 필수.
            raise FileNotFoundError(
                f"few-shot config 누락: {p}. _EXAMPLE_CONFIG_FILES 갱신 필요 "
                f"(config 가 rename/제거됐을 가능성)."
            )
        cfg = json.loads(p.read_text(encoding="utf-8"))
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
        d["escalation_hint"] = "(위 '⚠ probe 분석 힌트' 블록 참고)"
    lh = (list_html.get("html") or "")[:max_html_chars]
    ah = (article.get("html") or "")[:max_html_chars]

    meta = json.dumps(d, ensure_ascii=False, indent=2)
    examples = _load_examples()

    # register.py preflight / --article-url 가 넣은 힌트. probe 휴리스틱(목록 전략 추정·후보 relevance 순위·"첫 글" 자동 픽)은
    # 자주 틀리므로 — 아래 list_html / article_sample.html / traffic_json_api_candidates / HAR 후보와 대조해 *확인한 뒤* 반영할 것.
    # 사용자가 직접 준 정보(--article-url 의 글 URL)는 신뢰. (재시도 시 build_retry_prompt 도 이 블록을 그대로 쓰고, "직전 시도가 뭘 FAIL 했나" 는 별도 feedback 블록.)
    eh_block = f"\n## ⚠ probe 분석 힌트 (휴리스틱이라 틀릴 수 있음 — HTML/HAR 와 대조해 확인 후 반영. 어긋나면 실제 데이터를 따라 네가 골라라)\n{eh}\n" if eh else ""
    api_block = ""
    if api_cands:
        api_block = (
            "\n## ⚡ 글 본문 JSON API 후보 (글 페이지가 SPA 면 정적 HTML 에 본문이 없으니 이걸로 — 단 *진짜 본문을 주는 후보인지 확인*하고 써라)\n"
            "```json\n" + json.dumps(api_cands, ensure_ascii=False, indent=2) + "\n```\n"
            "→ 진짜 본문 후보(url_id_match=true·body_looks_html=true)를 골라: article.url_template = 그 후보 url 의 글 ID 숫자를 {{post_id}} 로 치환한 것, article.fetch_kind=\"json\", "
            "article.content=[{{from:\"json\", path:<후보의 body_field_path 그대로>}}]. 필요하면 후보의 request_headers 중 X-Requested-With/Referer 를 config 최상위 headers 에 추가. "
            "**body_field_path 가 ['ads',...] 류이거나 url 이 ad/banner/sdk/collect/gtm 류면 광고 SDK** — 무시하고, 그러면 아래 '글 본문 페이지 HTML 샘플' 의 본문 컨테이너 selector 로 article.content 를 잡아라(fetch_kind 도 html 로).\n"
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
