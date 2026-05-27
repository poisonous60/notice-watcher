"""D-layer retry recipe selection + patch generation + prompt rendering.

generator.py 의 `_RECIPE_TEXT_HINTS` / `_RECIPE_1_POST_ID_PATCH` / `_select_retry_recipes` /
`_apply_recipe_patch` / `_build_recipe_feedback_section` / `_pick_spa_wait_selector` +
prompt.py 의 `build_retry_prompt(starting_candidate=...)` 검증.

probe/* 의 @heuristic 휴리스틱이 아니므로 covers 는 빈 list. probe_smoke stage 5 coverage 검증은
@heuristic 데코레이터 기준이라 이 파일은 coverage 차집합에 안 잡힘.
"""
from __future__ import annotations


covers: list[str] = []


def _feed_validated(url: str) -> dict:
    return {"url": url, "validated": True, "item_count": 5, "root_tag": "rss", "title": "Test"}


def _attempt(n: int, fails: list[str], *, strategy: str = "httpx_html", rows: str = "channel > item") -> dict:
    return {
        "n": n,
        "strategy": strategy,
        "rows": rows,
        "fails": fails,
        "fails_detail": [f"{f}: detail" for f in fails],
    }


def run() -> list[tuple[str, bool, str]]:
    from generate.generator import (
        _count_fail_key,
        _select_retry_recipes,
        _apply_recipe_patch,
        _build_recipe_feedback_section,
        _recipe_1_applies,
        _recipe_2_applies,
        _pick_spa_wait_selector,
    )
    from generate.prompt import build_retry_prompt

    cases: list[tuple[str, bool, str]] = []

    # ── _count_fail_key ────────────────────────────────────────────────────
    hist = [_attempt(1, ["post_id_unique"]), _attempt(2, ["post_id_unique", "title_nonempty"])]
    cases.append(("count_fail_key_2x", _count_fail_key(hist, "post_id_unique") == 2,
                  f"got {_count_fail_key(hist, 'post_id_unique')}"))
    cases.append(("count_fail_key_0", _count_fail_key(hist, "nonexistent_key") == 0, ""))

    # ── Recipe 1 applies_to ────────────────────────────────────────────────
    cfg_rss = {"strategy": "httpx_html", "list": {"row_selector": "channel > item"}}
    digest_rss_kind = {"site_kind": {"kind": "rss", "confidence": "high"}, "feed_candidates": []}
    cases.append(("r1_applies_rss_kind", _recipe_1_applies(cfg_rss, digest_rss_kind), ""))

    digest_validated_feed = {"site_kind": {"kind": "unknown"},
                             "feed_candidates": [_feed_validated("https://x/feed")]}
    cases.append(("r1_applies_validated_feed", _recipe_1_applies(cfg_rss, digest_validated_feed), ""))

    cfg_non_rss_row = {"strategy": "httpx_html", "list": {"row_selector": "div.post"}}
    cases.append(("r1_skip_non_rss_row", not _recipe_1_applies(cfg_non_rss_row, digest_rss_kind),
                  "RSS row selector 아닌데 matched"))

    cfg_pw = {"strategy": "playwright_html", "list": {"row_selector": "channel > item"}}
    cases.append(("r1_skip_playwright_strategy", not _recipe_1_applies(cfg_pw, digest_rss_kind),
                  "playwright_html 인데 matched"))

    cases.append(("r1_skip_no_feed_no_rss_kind",
                  not _recipe_1_applies(cfg_rss, {"site_kind": {"kind": "static_html"}, "feed_candidates": []}),
                  ""))

    cfg_atom = {"strategy": "httpx_html", "list": {"row_selector": "feed > entry"}}
    cases.append(("r1_applies_atom_entry", _recipe_1_applies(cfg_atom, digest_rss_kind), ""))

    # ── Recipe 2 applies_to ────────────────────────────────────────────────
    digest_spa = {"site_kind": {"kind": "spa_rendered", "confidence": "high"}}
    cases.append(("r2_applies_spa_high", _recipe_2_applies({"strategy": "httpx_html"}, digest_spa), ""))

    digest_spa_med = {"site_kind": {"kind": "spa_rendered", "confidence": "med"}}
    cases.append(("r2_skip_spa_med",
                  not _recipe_2_applies({"strategy": "httpx_html"}, digest_spa_med),
                  "med confidence 인데 matched"))

    digest_static = {"site_kind": {"kind": "static_html", "confidence": "high"}}
    cases.append(("r2_skip_static", not _recipe_2_applies({"strategy": "httpx_html"}, digest_static), ""))

    # ── _select_retry_recipes ──────────────────────────────────────────────
    sel = _select_retry_recipes(cfg_rss, digest_rss_kind, hist)
    cases.append(("select_r1_post_id_2x", "rss_post_id_from_link" in sel, f"got {sel!r}"))

    hist_1x = [_attempt(1, ["post_id_unique"])]
    sel_1x = _select_retry_recipes(cfg_rss, digest_rss_kind, hist_1x)
    cases.append(("select_skip_1x_only", "rss_post_id_from_link" not in sel_1x,
                  f"got {sel_1x!r} (1회만인데 selected)"))

    hist_stable = [_attempt(1, ["post_id_stable_shape"]), _attempt(2, ["post_id_stable_shape"])]
    sel_stable = _select_retry_recipes(cfg_rss, digest_rss_kind, hist_stable)
    cases.append(("select_r1_stable_shape_2x", "rss_post_id_from_link" in sel_stable, f"got {sel_stable!r}"))

    hist_spa = [_attempt(1, ["posts_nonempty"]), _attempt(2, ["title_nonempty"])]
    sel_spa = _select_retry_recipes({"strategy": "httpx_html"}, digest_spa, hist_spa)
    cases.append(("select_r2_spa_mixed_2x", "spa_rendered_retry" in sel_spa, f"got {sel_spa!r}"))

    hist_dns = [
        {
            "n": 1,
            "strategy": "playwright_html",
            "rows": ".post-card",
            "fails": ["fetch_list"],
            "fails_detail": ["Page.goto: net::ERR_NAME_NOT_RESOLVED at https://example.com/news"],
        },
        {
            "n": 2,
            "strategy": "playwright_html",
            "rows": ".post-card",
            "fails": ["fetch_list"],
            "fails_detail": ["Temporary failure in name resolution"],
        },
    ]
    sel_dns = _select_retry_recipes({"strategy": "playwright_html"}, {"url": "https://example.com/news"}, hist_dns)
    cases.append(("select_stealth_dns_disable_on_repeated_nav_dns",
                  "stealth_dns_disable" in sel_dns,
                  f"got {sel_dns!r}"))

    # ── _apply_recipe_patch — Recipe 1 ─────────────────────────────────────
    prev_cfg = {
        "strategy": "httpx_html",
        "list": {
            "row_selector": "channel > item",
            "fields": {"post_id": [{"from": "css", "selector": "guid", "text": True}], "title": [{}]},
        },
        "article": {},
    }
    patched_1 = _apply_recipe_patch(prev_cfg, ["rss_post_id_from_link"], digest_rss_kind)
    cases.append(("patch_r1_returns_dict", isinstance(patched_1, dict), ""))
    new_pid = (patched_1 or {}).get("list", {}).get("fields", {}).get("post_id", [])
    # fallback chain (guid number prefix + link 전체) — 두 source 모두 박혀야
    cases.append(("patch_r1_post_id_has_link_source",
                  isinstance(new_pid, list)
                  and any(s.get("selector") == "link" for s in new_pid if isinstance(s, dict)),
                  f"got {new_pid!r}"))
    # Recipe 1 patch = fallback chain: 1순위 guid number prefix + 2순위 link 전체 URL.
    # 2026-05-25 N100 검증에서 link 만 박은 패치는 TAL RSS feed 의 진짜 link 중복
    # (promo item 의 lifepartners/root URL) 때문에 회복 X. guid number 가 진짜 fix.
    cases.append(("patch_r1_post_id_fallback_chain_len",
                  isinstance(new_pid, list) and len(new_pid) == 2,
                  f"got len={len(new_pid) if isinstance(new_pid, list) else 'N/A'}, expect 2"))
    cases.append(("patch_r1_post_id_first_is_guid_number",
                  isinstance(new_pid, list) and len(new_pid) >= 1
                  and new_pid[0].get("selector") == "guid"
                  and any(isinstance(t, list) and t and t[0] == "regex_extract"
                          and (t[1].startswith("^") if len(t) >= 2 and isinstance(t[1], str) else False)
                          for t in new_pid[0].get("transform", [])),
                  f"got first source: {new_pid[0] if new_pid else 'N/A'}"))
    cases.append(("patch_r1_post_id_second_is_link",
                  isinstance(new_pid, list) and len(new_pid) >= 2
                  and new_pid[1].get("selector") == "link"
                  and any(isinstance(t, list) and t and t[0] == "strip_query_fragment"
                          for t in new_pid[1].get("transform", [])),
                  f"got second source: {new_pid[1] if isinstance(new_pid, list) and len(new_pid) >= 2 else 'N/A'}"))

    # R-H3 critical — prev_cfg 안 덮어씀
    cases.append(("patch_r1_prev_cfg_not_mutated",
                  prev_cfg["list"]["fields"]["post_id"][0].get("selector") == "guid",
                  f"prev_cfg mutated: {prev_cfg['list']['fields']['post_id']!r}"))

    # 다른 fields 보존 (title)
    cases.append(("patch_r1_other_fields_preserved",
                  "title" in (patched_1 or {}).get("list", {}).get("fields", {}),
                  ""))

    # ── _apply_recipe_patch — Recipe 2 ─────────────────────────────────────
    prev_cfg_spa = {"strategy": "httpx_html", "list": {"row_selector": "div"}, "article": {}}
    digest_spa_with_pat = {
        "url": "https://radiolab.org/podcast",
        "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {
            "html_repeating_patterns": [
                {"selector": ".radiolab-card", "child_count": 12,
                 "sample_url": "https://radiolab.org/podcast/episode-1",
                 "href_pattern_guess": "/podcast/{slug}"},
                {"selector": "nav ul li", "child_count": 30,
                 "sample_url": "https://other.com/x", "href_pattern_guess": ""},
            ],
        },
    }
    patched_2 = _apply_recipe_patch(prev_cfg_spa, ["spa_rendered_retry"], digest_spa_with_pat)
    cases.append(("patch_r2_strategy_switch",
                  (patched_2 or {}).get("strategy") == "playwright_html",
                  f"got strategy={(patched_2 or {}).get('strategy')!r}"))
    cases.append(("patch_r2_wait_selector_same_host",
                  (patched_2 or {}).get("list", {}).get("wait_selector") == ".radiolab-card",
                  f"got wait_selector={(patched_2 or {}).get('list', {}).get('wait_selector')!r} (nav 후보 잡힘?)"))
    cases.append(("patch_r2_prev_cfg_not_mutated",
                  prev_cfg_spa["strategy"] == "httpx_html",
                  f"prev_cfg mutated: strategy={prev_cfg_spa['strategy']!r}"))

    # Recipe 2 — 이미 playwright_html: patch 없음 (None)
    prev_cfg_pw = {"strategy": "playwright_html", "list": {"row_selector": "div"}, "article": {}}
    patched_2b = _apply_recipe_patch(prev_cfg_pw, ["spa_rendered_retry"], digest_spa_with_pat)
    cases.append(("patch_r2_no_change_if_already_pw", patched_2b is None,
                  f"got {patched_2b!r}"))

    # Recipe 2 — 진짜 selector 후보 없음: strategy switch 만, wait_selector 없음
    digest_spa_no_cand = {
        "url": "https://x/", "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {"html_repeating_patterns": [
            {"selector": ".loading", "child_count": 5,
             "sample_url": "https://external.cdn.com/asset", "href_pattern_guess": "https://external/x"},
        ]},
    }
    patched_2c = _apply_recipe_patch(prev_cfg_spa, ["spa_rendered_retry"], digest_spa_no_cand)
    cases.append(("patch_r2_no_wait_when_no_samehost_cand",
                  (patched_2c or {}).get("strategy") == "playwright_html"
                  and "wait_selector" not in ((patched_2c or {}).get("list") or {}),
                  f"got {patched_2c!r}"))

    prev_cfg_dns = {"strategy": "playwright_html", "list": {"row_selector": ".post-card"}, "article": {}}
    patched_dns = _apply_recipe_patch(prev_cfg_dns, ["stealth_dns_disable"], {"url": "https://example.com/news"})
    cases.append(("patch_stealth_dns_sets_disable_stealth",
                  (patched_dns or {}).get("disable_stealth") is True,
                  f"got {patched_dns!r}"))
    cases.append(("patch_stealth_dns_prev_cfg_not_mutated",
                  "disable_stealth" not in prev_cfg_dns,
                  f"prev_cfg mutated: {prev_cfg_dns!r}"))

    # _pick_spa_wait_selector — 직접 검증
    sel_pick = _pick_spa_wait_selector(digest_spa_with_pat, "radiolab.org")
    cases.append(("pick_wait_selector_same_host", sel_pick == ".radiolab-card", f"got {sel_pick!r}"))
    sel_pick_none = _pick_spa_wait_selector(digest_spa_no_cand, "x")
    cases.append(("pick_wait_selector_none_when_no_samehost", sel_pick_none is None, f"got {sel_pick_none!r}"))

    # css_component_classes fallback (2026-05-25 Radiolab plan) — html_repeating_patterns
    # 비어있을 때 css_component_classes 의 top 1 class 를 wait_selector 후보로.
    digest_css_fallback = {
        "url": "https://radiolab.org/podcast",
        "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {
            "html_repeating_patterns": [],  # empty
            "css_component_classes": [
                {"class": "radiolab-card", "rule_count": 12, "co_classes": ["v-card", "card-title-link"]},
                {"class": "card-title-link", "rule_count": 8, "co_classes": ["h2"]},
            ],
        },
    }
    sel_css = _pick_spa_wait_selector(digest_css_fallback, "radiolab.org")
    cases.append(("pick_css_fallback_uses_top",
                  sel_css == ".radiolab-card",
                  f"got {sel_css!r}"))

    # css_component_classes 에 nav/skeleton 박힌 게 잘못 들어왔다면 reject + 다음 후보
    digest_css_chrome_first = {
        "url": "https://x.com/",
        "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {
            "html_repeating_patterns": [],
            "css_component_classes": [
                {"class": "nav", "rule_count": 10, "co_classes": []},
                {"class": "post-card", "rule_count": 5, "co_classes": []},
            ],
        },
    }
    cases.append(("pick_css_skips_chrome_class",
                  _pick_spa_wait_selector(digest_css_chrome_first, "x.com") == ".post-card",
                  f"got {_pick_spa_wait_selector(digest_css_chrome_first, 'x.com')!r}"))

    # html_repeating_patterns 후보 있으면 css fallback 안 사용 (우선순위)
    digest_both = {
        "url": "https://x.com/",
        "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {
            "html_repeating_patterns": [
                {"selector": ".real-row", "child_count": 5,
                 "sample_url": "https://x.com/a", "href_pattern_guess": "/a"},
            ],
            "css_component_classes": [
                {"class": "css-class-name", "rule_count": 10, "co_classes": []},
            ],
        },
    }
    cases.append(("pick_html_repeating_priority_over_css",
                  _pick_spa_wait_selector(digest_both, "x.com") == ".real-row",
                  ""))

    # 둘 다 없으면 None
    digest_empty = {
        "url": "https://x.com/",
        "site_kind": {"kind": "spa_rendered", "confidence": "high"},
        "list_candidates": {"html_repeating_patterns": [], "css_component_classes": []},
    }
    cases.append(("pick_none_when_both_empty",
                  _pick_spa_wait_selector(digest_empty, "x.com") is None, ""))

    # R-H10 — nav/skeleton/loading chrome selector blocklist
    digest_nav_top = {
        "url": "https://x.com/",
        "list_candidates": {"html_repeating_patterns": [
            {"selector": "nav ul li", "child_count": 30,
             "sample_url": "https://x.com/menu/about", "href_pattern_guess": "/menu/{x}"},
            {"selector": ".header-nav-item", "child_count": 20,
             "sample_url": "https://x.com/h", "href_pattern_guess": "/h"},
            {"selector": ".post-card", "child_count": 8,
             "sample_url": "https://x.com/post/1", "href_pattern_guess": "/post/{id}"},
        ]},
    }
    sel_skip_nav = _pick_spa_wait_selector(digest_nav_top, "x.com")
    cases.append(("pick_wait_selector_skips_nav_chrome",
                  sel_skip_nav == ".post-card",
                  f"got {sel_skip_nav!r} (nav/header 가 selected?)"))

    digest_skeleton_only = {
        "url": "https://x.com/",
        "list_candidates": {"html_repeating_patterns": [
            {"selector": ".skeleton-row", "child_count": 12,
             "sample_url": "https://x.com/loading", "href_pattern_guess": "/loading"},
            {"selector": ".loading-placeholder", "child_count": 5,
             "sample_url": "https://x.com/x", "href_pattern_guess": "/x"},
        ]},
    }
    cases.append(("pick_wait_selector_all_skeleton_returns_none",
                  _pick_spa_wait_selector(digest_skeleton_only, "x.com") is None, ""))

    # 정상 selector 안에 nav 가 substring 으로 들어도 token boundary 면 PASS
    # (e.g., `.navigate-list` 의 nav 는 word token X — 부분 매칭이지만 boundary 가 깸)
    # 보수적으로 — `navigation` 은 reject, `.navigate-list` 는 substring `nav` 가 있지만
    # blocklist 가 `(nav|navbar|navigation|...)` 정확 token 매칭이라 `navigate` 는 PASS.
    digest_word_boundary = {
        "url": "https://x.com/",
        "list_candidates": {"html_repeating_patterns": [
            {"selector": ".navigate-item", "child_count": 10,
             "sample_url": "https://x.com/a", "href_pattern_guess": "/a"},
        ]},
    }
    cases.append(("pick_wait_selector_token_boundary_allows_navigate",
                  _pick_spa_wait_selector(digest_word_boundary, "x.com") == ".navigate-item",
                  "`.navigate-item` 가 `nav` substring 으로 잘못 reject?"))

    # 빈 recipe 리스트 → None
    cases.append(("patch_empty_recipes_returns_none",
                  _apply_recipe_patch(prev_cfg, [], digest_rss_kind) is None, ""))

    # ── _build_recipe_feedback_section ─────────────────────────────────────
    sec = _build_recipe_feedback_section(["rss_post_id_from_link"], patched_1)
    cases.append(("section_has_recipe_name", "rss_post_id_from_link" in sec, ""))
    cases.append(("section_has_inject_warning", "결정론" in sec or "recipe" in sec.lower(), ""))
    # JSON snippet 은 build_retry_prompt 가 박음 — section 엔 없어야 (중복 방지)
    cases.append(("section_no_json_snippet", "```json" not in sec,
                  "feedback section 에 JSON snippet 박힘 — build_retry_prompt 와 중복"))
    cases.append(("section_empty_when_no_recipe",
                  _build_recipe_feedback_section([], None) == "", ""))

    # patched=None 이어도 recipes 있으면 text hint 박힘 (Radiolab 류 — 이미 playwright_html 인 cfg
    # 에 Recipe 2 trigger 되면 strategy switch 가 no-op → patched None. 그래도 진단 + 가이드 text 는
    # LLM 한테 전달돼야 함. 2026-05-25 N100 검증에서 발견된 bug 의 회귀 가드.)
    sec_no_patch = _build_recipe_feedback_section(["spa_rendered_retry"], None)
    cases.append(("section_text_hint_when_patched_none",
                  "spa_rendered_retry" in sec_no_patch and "발동" in sec_no_patch,
                  f"got {sec_no_patch[:200]!r}"))
    cases.append(("section_no_patch_uses_no_op_phrasing",
                  "patch 적용할 자리는 없" in sec_no_patch,
                  f"got {sec_no_patch[:200]!r}"))

    sec_dns = _build_recipe_feedback_section(["stealth_dns_disable"], patched_dns)
    cases.append(("section_stealth_dns_mentions_disable_stealth",
                  "disable_stealth" in sec_dns and "ERR_NAME_NOT_RESOLVED" in sec_dns,
                  f"got {sec_dns[:300]!r}"))

    # ── build_retry_prompt with starting_candidate ─────────────────────────
    # 최소 digest — build_user_prompt 가 안 깨질 정도
    min_digest = {
        "url": "https://example.com/feed",
        "list_html": {"html": "<html></html>", "source": "list.html"},
        "article_sample": {"html": "<html></html>", "url": "https://example.com/post/1"},
        "list_candidates": {},
        "feed_candidates": [],
    }
    prev_failed = {"strategy": "httpx_html", "list": {"row_selector": "channel > item"}}

    # starting_candidate 없으면 기존 동작 — `### 추천 수정 starting point` 블록 X
    p_no_cand = build_retry_prompt(min_digest, prev_failed, "feedback text")
    cases.append(("prompt_no_starting_block_when_none",
                  "### 추천 수정 starting point (D-layer recipe" not in p_no_cand, ""))

    # starting_candidate 있으면 별도 block 박힘 + JSON snippet 포함
    # prev_cfg 에 guid selector 박아 — patched_1 (link selector) 과 구분
    prev_with_guid = {
        "strategy": "httpx_html",
        "list": {"row_selector": "channel > item",
                 "fields": {"post_id": [{"from": "css", "selector": "guid", "text": True}]}},
    }
    p_with_cand = build_retry_prompt(min_digest, prev_with_guid, "feedback text",
                                     starting_candidate=patched_1)
    cases.append(("prompt_has_starting_block",
                  "### 추천 수정 starting point (D-layer recipe" in p_with_cand, ""))
    cases.append(("prompt_starting_block_has_strip_query_fragment",
                  "strip_query_fragment" in p_with_cand, ""))
    # R-H3 critical — "이전 config" block 에 prev_cfg 그대로(guid), patched 으로 덮어쓰지 X
    cases.append(("prompt_prev_config_keeps_guid",
                  '"selector": "guid"' in p_with_cand,
                  "prev_config block 에서 guid 사라짐 — patched 로 덮어쓰임?"))
    # starting block 은 link selector 박혀야
    cases.append(("prompt_starting_block_has_link_selector",
                  '"selector": "link"' in p_with_cand, ""))

    return cases
