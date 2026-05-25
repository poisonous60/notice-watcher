"""digest → config 생성 오케스트레이션.

- generate_config(digest)             : 1-shot — gemini → JSON → validate_config(스키마). M3 용.
- generate_config_validated(digest)   : M5 — 생성 → 실행검증(validate.py 3층위) → 실패면 피드백 재생성(≤max_attempts).
                                         2라운드부터는 "이전 config + 무엇이 실패했나 + 실제 추출 데이터" 를 주고 *수정* 요청(= 사실상 partial regen).
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
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
    def __init__(self, msg: str, *, stop_reason: str = "",
                 last_config=None, last_feedback: str = ""):
        super().__init__(msg)
        self.stop_reason = stop_reason
        self.last_config = last_config
        self.last_feedback = last_feedback


def _build_recipe_feedback_section(recipes: list[str], patched_candidate: Optional[dict]) -> str:
    """D-layer recipe text hint section — feedback text 뒤에 박힘.

    JSON snippet 은 여기서 안 박는다 — build_retry_prompt 의 별도 starting_candidate block 이 박음.
    여긴 *왜 inject 했는지* + *어떻게 따라가야 하는지* text hint 만.

    patched_candidate=None 도 OK — recipe selected 됐는데 patch 가 no-op 인 경우 (예: Recipe 2 가
    이미 playwright_html 인 cfg 에 trigger 됐을 때 strategy switch 가 의미 없음). text hint *는*
    여전히 박힘 — LLM 한테 진단 정보 + 휴리스틱 가이드 전달용 (plan §2a Recipe 2 "이미 playwright_html
    이면 text hint 만").
    recipes 자체가 빈 경우만 빈 string.
    """
    if not recipes:
        return ""
    lines = ["\n### D-layer recipe 발동 (반복 실패 봉합 룰 inject)"]
    if patched_candidate:
        lines.append(
            "같은 hard fail 이 2회+ 반복됨. 자연어 hint 만으로 봉합 안 돼 결정론 룰 강제 inject. "
            "아래 hint + prompt 의 `### 추천 수정 starting point` 블록 cfg 따라가라."
        )
    else:
        lines.append(
            "같은 hard fail 이 2회+ 반복됨. recipe 의 결정론 patch 적용할 자리는 없지만 "
            "(이미 권장 strategy/selector 박음), 아래 hint 의 진단 + 휴리스틱 가이드 따라 *방향* 을 바꿔라."
        )
    for r in recipes:
        hint = _RECIPE_TEXT_HINTS.get(r)
        if hint:
            lines.append("- " + hint)
    return "\n".join(lines)


def _enrich_retry_feedback(rep, prev_cfg: Optional[dict], digest: dict, attempt_history: list[dict],
                            *, recipe_section: str = "") -> str:
    """retry prompt 에 들어갈 풍부한 feedback. rep.feedback_text() 베이스 + 네 가지 보강.

    1. 직전 시도 cfg 의 list/article 전체 JSON echo — LLM 이 자기가 뭐 박았는지 잊지 않도록.
    2. probe 정적 HTML 의 top 7 repeating patterns 후보 재표시 — 125k digest 안에 묻혀 LLM 이
       못 찾는 selector 후보를 *눈에 띄게* 다시 제시.
    3. probe 가 본 *다른 list 전략 후보* 카운트 (traffic_json_api / inline_js_data /
       hydration_list / runtime_id / feed) — 지금 strategy 가 안 풀리면 다른 방향 검토 유도.
    4. attempt history — 직전 시도들이 박은 strategy/row_selector + 각 attempt 의 fail
       detail(첫 80자) 누적. 같은 hard fail 반복 시 명시 경고.

    같은 모델(gpt-5.4-mini)이 같은 prompt 에 같은 실수 반복하던 문제(retry 회복률 ~17%) 완화.
    """
    base = rep.feedback_text() if rep is not None else ""
    parts: list[str] = [base] if base else []

    # (1) 직전 시도 cfg — list/article 전체 echo (LLM 이 자기 박은 거 다시 보도록)
    if isinstance(prev_cfg, dict) and prev_cfg:
        lst = prev_cfg.get("list") or {}
        art = prev_cfg.get("article") or {}
        strat = prev_cfg.get("strategy")
        lst_dump = json.dumps(lst, ensure_ascii=False)
        art_dump = json.dumps(art, ensure_ascii=False)
        # 너무 길면 잘림 (개별 키 600자) — 보통 list/article 은 100-400자 수준
        if len(lst_dump) > 600:
            lst_dump = lst_dump[:600] + "…(잘림)"
        if len(art_dump) > 600:
            art_dump = art_dump[:600] + "…(잘림)"
        parts.append(
            "\n### 직전 시도가 박은 cfg (똑같이 박지 마라)\n"
            f"  strategy: {strat!r}\n"
            f"  list: {lst_dump}\n"
            f"  article: {art_dump}\n"
            f"  headers: {json.dumps(prev_cfg.get('headers') or {}, ensure_ascii=False)[:200]}\n"
            "  → 위 selector/strategy 로 검증 실패했다. 같은 selector 살짝 변형은 똑같이 실패한다 — "
            "**방향 자체**(strategy 또는 selector 의 root 컨테이너)를 바꿔라."
        )

    # (2) probe 정적 HTML top 반복 패턴 후보 재표시 (LLM 이 못 찾던 selector 후보)
    lc = digest.get("list_candidates") or {}
    pats = lc.get("html_repeating_patterns") or []
    if pats:
        top = sorted(pats, key=lambda p: int(p.get("child_count") or 0), reverse=True)[:7]
        lines = [f"\n### probe 정적 HTML 의 반복 패턴 후보 top {len(top)} (selector 다시 검토)"]
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

    # (3) probe 다른 list 전략 후보 카운트 — strategy 변경 옵션 LLM 한테 명시
    n_json_api = len(lc.get("traffic_json_api_candidates") or [])
    n_inline_js = len(lc.get("inline_js_data_candidates") or [])
    n_hyd = len(lc.get("hydration_list_candidates") or [])
    n_runtime = len(lc.get("runtime_id_candidates") or [])
    n_feed = len(digest.get("feed_candidates") or [])
    counts = []
    if n_json_api:
        counts.append(f"traffic_json_api_candidates={n_json_api}건 (httpx_json 검토)")
    if n_inline_js:
        counts.append(f"inline_js_data_candidates={n_inline_js}건 (정적 HTML 안 JSON island 파싱)")
    if n_hyd:
        counts.append(f"hydration_list_candidates={n_hyd}건 (Next/Nuxt SSR data)")
    if n_runtime:
        counts.append(f"runtime_id_candidates={n_runtime}건")
    if n_feed:
        counts.append(f"feed_candidates={n_feed}건 (RSS/Atom)")
    if counts:
        parts.append(
            "\n### probe 가 본 *다른* list 전략 후보 (지금 strategy 안 풀리면 검토)\n  "
            + "\n  ".join(counts)
            + "\n  → 후보가 있는데 못 풀고 있으면 strategy 자체를 바꿔라."
        )

    # (4) attempt history — 누적 시도된 strategy/selector + fail detail
    if len(attempt_history) >= 1:
        lines = [f"\n### 직전 {len(attempt_history)} 회 시도 누적 (같은 방향 X)"]
        for h in attempt_history:
            fails = h.get("fails_detail") or h.get("fails") or []
            lines.append(
                f"  attempt {h['n']}: strategy={h.get('strategy')!r}  "
                f"row_selector/list_path={h.get('rows')!r}\n"
                f"    fails: {fails!r}"
            )
        # 같은 hard fail 반복 감지 (name set 비교)
        all_fails = [tuple(sorted(h.get("fails") or [])) for h in attempt_history]
        if len(all_fails) >= 2 and len(set(all_fails)) == 1:
            lines.append(
                "  ⚠ 직전 시도들 모두 *같은 hard fail 종류* 만 일으킴 — 같은 방향으론 절대 안 풀린다. "
                "selector 미세 조정 대신 strategy 자체 또는 selector root 를 바꿔라. "
                "본문 fail 반복이면 article.body_empty_acceptable:true 검토."
            )
        parts.append("\n".join(lines))

    # (5) D-layer recipe hint — 호출부에서 계산해 주입
    if recipe_section:
        parts.append(recipe_section)

    return "\n".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────────────────────
# D-layer retry feedback dynamic injection (MVP recipes)
#
# 같은 hard-fail key 가 2회+ 반복되면, prompt 의 자연어 hint 만으로는 LLM 이 봉합 못 함.
# (RSS post_id 룰 / spa_rendered hint 가 prompts/config_writer.system.txt 에 박혀 있음에도
#  LLM 이 무시한 경험 — docs/cases/_session_retro_2026-05-24_podcast.md §7d/§7f).
#
# 룰: 결정론 봉합 룰을 *완성된 cfg snippet* 또는 *strategy switch* 로 retry prompt 에 inject.
# prev_cfg 자체는 안 덮어쓴다 (R-H3) — 별도 `### 추천 수정 starting point` block 으로 전달.
# 실제 patch 키는 engine 이 읽는 키만 (R-H10) — wait_selector / strategy 등.
# ─────────────────────────────────────────────────────────────────────────────

# RSS/Atom row selector 인지 판단 — Recipe 1 의 applies_to.
_RSS_ROW_SELECTOR_RE = re.compile(r"\b(channel\s*>\s*item|^item$|>\s*item\b|feed\s*>\s*entry|^entry$|>\s*entry\b)", re.IGNORECASE)


def _count_fail_key(attempt_history: list[dict], key: str) -> int:
    """attempt_history 의 fails (validation check name) 중 key 등장 횟수 (exact match)."""
    n = 0
    for h in attempt_history:
        fails = h.get("fails") or []
        if key in fails:
            n += 1
    return n


def _recipe_1_applies(cfg: dict, digest: dict) -> bool:
    """Recipe 1 applies_to — RSS post_id 불안정 봉합 대상.

    조건: strategy=httpx_html + row_selector 가 RSS/Atom pattern + (site_kind 가 rss/podcast/hybrid
    또는 validated XML feed 후보 1+).
    """
    if (cfg.get("strategy") or "") != "httpx_html":
        return False
    lst = cfg.get("list") or {}
    row_sel = str(lst.get("row_selector") or "")
    if not _RSS_ROW_SELECTOR_RE.search(row_sel):
        return False
    sk = (digest.get("site_kind") or {}).get("kind")
    if sk in ("rss", "podcast", "hybrid"):
        return True
    # site_kind 없거나 unknown 이어도 validated feed 후보 1+ 면 OK
    feeds = digest.get("feed_candidates") or []
    for f in feeds:
        if isinstance(f, dict) and f.get("validated") is True:
            return True
    lc = digest.get("list_candidates") or {}
    for f in lc.get("rss_feed_urls") or []:
        if isinstance(f, dict) and f.get("validated") is True:
            return True
    return False


def _recipe_2_applies(cfg: dict, digest: dict) -> bool:
    """Recipe 2 applies_to — SPA rendered 봉합 대상.

    조건: site_kind.kind=spa_rendered AND confidence=high.
    """
    sk = digest.get("site_kind") or {}
    return sk.get("kind") == "spa_rendered" and sk.get("confidence") == "high"


# Recipe 1 patch: fallback chain — guid 의 number prefix 우선, link 전체 URL fallback.
#
# 1순위 (guid number prefix): TAL 류 podcast 의 guid 가 `"46156 at https://..."` 형식 —
#   number 만 unique stable ID. regex_extract 매칭 X 면 None → fallback 으로 넘어감.
# 2순위 (link 전체): 대부분 RSS feed 에서 link 자체가 unique URL. path tail 추출 X (TAL 같이
#   일부 promo item 의 path tail 이 다른 episode 와 겹치는 경우 회피).
#
# 2026-05-25 N100 검증에서 link 전체만 박은 패치는 TAL RSS feed 의 *진짜 link 중복*
# (`lifepartners` 2번, root URL 2번 — promo item) 때문에 회복 X. guid number prefix 가 진짜 fix.
_RECIPE_1_POST_ID_PATCH = [
    {
        "from": "css",
        "selector": "guid",
        "text": True,
        "transform": [["regex_extract", r"^(\d+)"]],
    },
    {
        "from": "css",
        "selector": "link",
        "text": True,
        "transform": [["strip"], ["strip_query_fragment"]],
    },
]


# nav/header/footer/skeleton/loading 등 *chrome* selector 차단 — wait_selector 가 가짜 element
# 까지 대기하면 무한 wait + post 추출 0건. selector text token 단위 매칭 — word boundary 는
# `\w` 만 사용 (hyphen 은 separator 취급 → `.header-nav-item` 의 `nav` 도 reject).
# 단 `navigate`, `headerless` 같은 *어휘 일부* 는 reject 안 됨 (token 자체가 `navigate`/`headerless` 임).
_SPA_WAIT_SELECTOR_BLOCKLIST_RE = re.compile(
    r"(?<!\w)(nav|navbar|navigation|header|footer|sidebar|menu|menubar|"
    r"breadcrumb|breadcrumbs|skeleton|loading|placeholder|spinner|shimmer)(?!\w)",
    re.IGNORECASE,
)


def _pick_spa_wait_selector(digest: dict, host: Optional[str]) -> Optional[str]:
    """probe html_repeating_patterns 중 same-host 글 URL 패턴인 top 1 의 selector.

    nav/skeleton/footer 같은 chrome/loading 후보 회피용 보수 필터 (R-H10):
    1. sample_url same-host 또는 href_pattern_guess 가 relative path
    2. selector text 에 chrome/skeleton/loading token 없음

    못 찾으면 fallback — digest 의 `list_candidates.css_component_classes` 의 top 1 class
    (Radiolab 류 — 정적 HTML DOM 에 없지만 inline `<style>` rule 엔 박힌 hydrated row container).
    css class 도 없으면 None — patch 에서 wait_selector 안 박고 strategy switch 만 함.
    """
    lc = digest.get("list_candidates") or {}
    pats = lc.get("html_repeating_patterns") or []
    cands = []
    for p in pats:
        if not isinstance(p, dict):
            continue
        sel = p.get("selector")
        if not sel or not isinstance(sel, str):
            continue
        # chrome/loading token reject (R-H10) — selector 자체에 nav/skeleton 박힌 후보는 skip
        if _SPA_WAIT_SELECTOR_BLOCKLIST_RE.search(sel):
            continue
        # same-host 글 URL 패턴 신호 — sample_url 의 host 가 같거나, href_pattern_guess 가 relative path
        sample = p.get("sample_url") or ""
        href_guess = p.get("href_pattern_guess") or ""
        same_host = False
        if host and sample:
            try:
                if urlsplit(sample).netloc == host:
                    same_host = True
            except Exception:
                pass
        if not same_host and isinstance(href_guess, str) and href_guess.startswith("/"):
            same_host = True
        if not same_host:
            continue
        cands.append((int(p.get("child_count") or 0), sel))
    if cands:
        cands.sort(key=lambda t: t[0], reverse=True)
        return cands[0][1]
    # fallback — css_component_classes (SPA hydration row 단서)
    css_cands = lc.get("css_component_classes") or []
    for cc in css_cands:
        if not isinstance(cc, dict):
            continue
        cls = cc.get("class")
        if not cls or not isinstance(cls, str):
            continue
        # _is_blocked_css_class 가 이미 reject 했지만 _SPA_WAIT_SELECTOR_BLOCKLIST_RE 추가 한 번 더
        if _SPA_WAIT_SELECTOR_BLOCKLIST_RE.search(cls):
            continue
        return f".{cls}"
    return None


def _select_retry_recipes(cfg: dict, digest: dict, attempt_history: list[dict]) -> list[str]:
    """attempt_history + cfg + digest 보고 적용 가능한 recipe name list 반환."""
    selected: list[str] = []
    # Recipe 1: post_id_unique OR post_id_stable_shape 가 2회+ + applies_to
    n_pid = _count_fail_key(attempt_history, "post_id_unique") + _count_fail_key(attempt_history, "post_id_stable_shape")
    if n_pid >= 2 and _recipe_1_applies(cfg, digest):
        selected.append("rss_post_id_from_link")
    # Recipe 2: posts_nonempty OR title_nonempty 가 2회+ + applies_to
    n_spa = _count_fail_key(attempt_history, "posts_nonempty") + _count_fail_key(attempt_history, "title_nonempty")
    if n_spa >= 2 and _recipe_2_applies(cfg, digest):
        selected.append("spa_rendered_retry")
    return selected


def _apply_recipe_patch(prev_cfg: dict, recipes: list[str], digest: dict) -> Optional[dict]:
    """선택된 recipe 들 prev_cfg 의 deepcopy 에 적용 → patched candidate.

    prev_cfg 자체 절대 안 건드림 (R-H3). recipe 가 비어있거나 patch 적용할 게 없으면 None.
    """
    if not recipes or not isinstance(prev_cfg, dict):
        return None
    patched = copy.deepcopy(prev_cfg)
    changed = False

    if "rss_post_id_from_link" in recipes:
        lst = patched.setdefault("list", {})
        fields = lst.setdefault("fields", {})
        fields["post_id"] = copy.deepcopy(_RECIPE_1_POST_ID_PATCH)
        changed = True

    if "spa_rendered_retry" in recipes:
        # strategy=httpx_html → playwright_html. 이미 playwright_html 이면 patch 없음 (text hint 만).
        if (patched.get("strategy") or "") == "httpx_html":
            patched["strategy"] = "playwright_html"
            host = None
            try:
                host = urlsplit(digest.get("url") or "").netloc or None
            except Exception:
                host = None
            wait_sel = _pick_spa_wait_selector(digest, host)
            if wait_sel:
                lst = patched.setdefault("list", {})
                lst["wait_selector"] = wait_sel
            changed = True

    return patched if changed else None


_RECIPE_TEXT_HINTS = {
    "rss_post_id_from_link": (
        "**Recipe rss_post_id_from_link** — `post_id_unique`/`post_id_stable_shape` 반복 실패. "
        "RSS guid 가 `'<number> at <url>'` 류 불안정 형식이고, link 자체에도 promo 항목 중복이 있을 수 있음. "
        "fallback chain 으로 박아라: 1순위 = guid 의 number prefix (`regex_extract \"^(\\d+)\"`), "
        "2순위 = link 전체 URL (strip + strip_query_fragment). 위 starting point 의 `list.fields.post_id` "
        "*두 source 다* 정확히 그 transform 으로 박아라 — 한 source 만 박지 마라."
    ),
    "spa_rendered_retry": (
        "**Recipe spa_rendered_retry** — `posts_nonempty`/`title_nonempty` 반복 실패 + SPA. "
        "server-rendered HTML 에 skeleton/loading row 만 박혀있고 진짜 row 는 hydration 후. "
        "starting point 의 `strategy=playwright_html` + `list.wait_selector` 그대로 시도. "
        "wait_selector 가 비어있으면 list_html (정적) 의 진짜 row container selector "
        "(h2/h3/.card-title/.post 류 — *실제 title element*) 를 직접 박아라. "
        "`a[href]` 단순 wait 는 nav/menu 까지 잡혀 부족하다."
    ),
}


_SELF_VETO_STOP_REASONS = {"non_board", "non_existent", "login_required"}


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
    # API/네트워크/엔벨로프 단 실패 vs *응답 본문* JSON 파싱 실패 를 분리해 surface.
    # - API 실패 시 `client.provider` — FallbackClient 면 primary+fallback 둘 다 실패한 케이스라
    #   "(fallback)" 라벨이 의미 있음 ("둘 다 실패").
    # - parse 실패 시 `resp.provider` — primary 가 200 응답 줬는데 본문이 malformed JSON 인 케이스.
    #   FallbackClient 라도 실제로 응답 준 provider (codex/gemini) 가 박힘.
    try:
        resp = client.generate(system_instruction=SYSTEM_INSTRUCTION, user_text=prompt_text,
                               temperature=temperature, json_mode=True,
                               call_site=call_site, slug=_slug_from_digest(digest), attempt=attempt)
    except LLMError as e:
        raise GenerationError(f"LLM 호출 실패 ({client.provider}): {e}") from e
    try:
        cfg = _parse_json_loose(resp.text)
    except LLMError as e:
        raise GenerationError(f"LLM 응답 JSON 파싱 실패 ({resp.provider or client.provider}): {e}") from e
    if isinstance(cfg, dict) and cfg.get("ok") is False:
        sr = str(cfg.get("stop_reason") or "")
        if sr in _SELF_VETO_STOP_REASONS:
            reason = str(cfg.get("reason") or "")
            raise GenerationError(
                f"agent self-veto: {sr} — {reason[:200]}",
                stop_reason=sr,
                last_config=None,
                last_feedback=reason,
            )
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
    cfg_post_processor: Optional[Callable[[dict], dict]] = None,
) -> tuple[dict, ValidationReport]:
    """생성 → 실행검증 → 실패 시 피드백 재생성, ≤max_attempts. 성공 (config, report) 반환. 전부 실패 시 GenerationError.

    on_attempt(i, cfg_or_None, report_or_None, ok, msg) — 진행 로깅용 콜백.
    cfg_post_processor(cfg) — LLM 이 만든 cfg 를 스키마/실행 검증 전에 확정 보정.

    `client` 가 None 이면 i==1 은 config_generate routing, i>=2 는 config_retry routing 사용 (routing.json).
    `model` 명시되면 모든 attempt 가 그 모델 사용 (CLI override).
    """
    override = f"gemini:{model}" if model else None
    prev_cfg: Optional[dict] = None
    prev_feedback: str = ""
    prev_starting_candidate: Optional[dict] = None  # D-layer recipe — retry round 별도 인자 (R-H3: prev_cfg 안 덮어씀)
    attempt_history: list[dict] = []  # _enrich_retry_feedback (3) — 누적 시도 strategy/selector/fails
    tr = current_trace()

    for i in range(1, max_attempts + 1):
        print(f"[PHASE] gemini_attempt {i}/{max_attempts}", flush=True)
        with tr.span("gemini_attempt", attrs={"attempt": i, "max_attempts": max_attempts}):
            if i == 1:
                prompt_text = build_user_prompt(digest)
            else:
                prompt_text = build_retry_prompt(
                    digest, prev_cfg or {}, prev_feedback,
                    starting_candidate=prev_starting_candidate,
                )

            # i==1 은 신규 생성, i>=2 는 retry 라운드 (다른 모델 라우팅 가능하도록 call_site 분리).
            call_site = "config_generate" if i == 1 else "config_retry"
            cli = client or client_for(call_site, override=override)
            try:
                with tr.span("gemini_call", attrs={"attempt": i, "call_site": call_site}):
                    cfg = _generate_raw(digest, client=cli, prompt_text=prompt_text, temperature=temperature,
                                        call_site=call_site, attempt=i)
            except GenerationError as e:
                if getattr(e, "stop_reason", "") in _SELF_VETO_STOP_REASONS:
                    raise
                msg = f"생성 실패: {e}"
                if on_attempt:
                    on_attempt(i, None, None, False, msg)
                prev_cfg, prev_feedback = (prev_cfg or {}), (prev_feedback + f"\n(직전 시도 생성 실패: {e})")
                if i < max_attempts:
                    await asyncio.sleep(inter_attempt_sleep)
                continue

            if cfg_post_processor:
                cfg = cfg_post_processor(cfg)

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
            # history 누적 — 다음 attempt feedback 의 (4) 분기용
            _lst = cfg.get("list") or {}
            attempt_history.append({
                "n": i,
                "strategy": cfg.get("strategy"),
                "rows": _lst.get("row_selector") or _lst.get("list_path"),
                "fails": [c.name for c in rep.hard_failures()],
                "fails_detail": [f"{c.name}: {(c.detail or '')[:80]}" for c in rep.hard_failures()],
            })
            prev_cfg = cfg
            # D-layer recipe 계산 — 같은 fail key 2회+ 반복 시 결정론 봉합 룰 inject (R-H3: prev_cfg 안 덮어씀)
            recipes = _select_retry_recipes(cfg, digest, attempt_history)
            prev_starting_candidate = _apply_recipe_patch(cfg, recipes, digest) if recipes else None
            recipe_section = _build_recipe_feedback_section(recipes, prev_starting_candidate)
            prev_feedback = _enrich_retry_feedback(rep, prev_cfg, digest, attempt_history, recipe_section=recipe_section)
            if i < max_attempts:
                await asyncio.sleep(inter_attempt_sleep)

    err = GenerationError(f"{max_attempts}회 시도 모두 실패. 마지막 피드백:\n{prev_feedback}")
    err.last_config = prev_cfg  # type: ignore[attr-defined]
    err.last_feedback = prev_feedback  # type: ignore[attr-defined]
    raise err
