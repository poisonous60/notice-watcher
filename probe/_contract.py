"""probe 산출물 single source of truth.

목적:
- `output/probe/<slug>/*.json` 의 키 이름·필수 여부를 한 곳에 모아 silent fail 차단.
- write 측 (probe/extract.py, probe/discover.py, probe/report.py, probe/fetch_headless.py, scripts/register.py)
  → 산출물 dict 빌드 후 `validate_payload(file_name, payload)` 호출
- read 측 (engine/digest.py, scripts/probe_smoke.py) → 키 상수 import 로 drift 차단
- LLM 프롬프트 (prompts/config_writer.system.txt) → smoke stage1c 가 _PROMPT_REQUIRED_KEY_PATHS
  명시 키들의 워드바운더리 등장 여부 검사 (WARN — rename 잊었나 신호)

확장 워크플로:
1. 새 산출물 파일 = `_ARTIFACTS` 에 새 `ArtifactContract` 추가
2. 기존 산출물에 새 키 = 해당 contract.fields 에 `_ContractField(...)` 한 줄 추가
3. write 측 함수가 그 키를 산출물 dict 에 넣고, validate 가 통과하면 끝
4. 프롬프트에 등장해야 하는 키 = `_PROMPT_REQUIRED_KEY_PATHS` 에 (file, key) 추가
   - 키가 자연어 별명으로 등장하면 해당 `_ContractField` 에 `prompt_aliases=(...)` 명시

내부 단순화 — Pydantic/TypedDict 의존 X. dataclass + 작은 검증 헬퍼만.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ContractError(ValueError):
    """contract 위반 — 누락 필수 키 / 모르는 키 / payload 타입 불일치."""


@dataclass(frozen=True)
class _ContractField:
    """산출물 dict 의 한 키 메타데이터.

    name: 산출물 dict 안 키 이름
    required: True 면 산출물에 반드시 있어야 함 (None 값은 허용)
    type_hint: 자유서식 문서 — "str|null" / "list[dict]" 등 (런타임 검증 X)
    note: 키 의미 한 줄
    prompt_aliases: 프롬프트에서 자연어 별명으로 부르는 경우 — `recommended_headers`
        프롬프트는 `static_ok_request_headers`/`captured_headers` 로 칭함 등.
        stage1c 가 이 alias 도 워드바운더리 매칭에 인정.
    """
    name: str
    required: bool = True
    type_hint: str = "any"
    note: str = ""
    prompt_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactContract:
    """산출물 파일 1종의 스키마.

    file_name: 산출물 파일명 (디스크 경로 X, 파일명만)
    payload_kind: "object" = top-level dict, "object_list" = top-level list of dicts
    fields: top-level dict 의 필드 (payload_kind="object" 면 직접 사용 / "object_list" 면 비워두고 item_fields 사용)
    item_fields: payload_kind="object_list" 일 때 각 item dict 의 필드
    list_item_fields: top-level dict 안 *특정 list-typed 필드* 의 item 키들
                     예: diagnosis.json 의 results[*] 안 키들 → {"results": (Result.to_dict 키들,)}
    optional_on_disk: True 면 산출물 자체가 디스크에 안 있어도 정상 (smoke 가 FAIL X)
    """
    file_name: str
    payload_kind: str = "object"
    fields: tuple[_ContractField, ...] = ()
    item_fields: tuple[_ContractField, ...] = ()
    list_item_fields: dict[str, tuple[_ContractField, ...]] = field(default_factory=dict)
    optional_on_disk: bool = False


# --------------------------------------------------------------------------- #
# Diagnosis.results[*] 항목 — diagnosis.json 의 results 리스트 안 item 키.
# (probe/types.py:Result.to_dict() 가 만드는 키들.)
# --------------------------------------------------------------------------- #
_DIAGNOSIS_RESULT_FIELDS: tuple[_ContractField, ...] = (
    _ContractField("strategy", note="전략 명. S1.H1~H4 / S4 / S4.click / Jina / Crawl4AI / Zyte 등"),
    _ContractField("target", note="'list' | 'article' | 'baseline' | 'replay'"),
    _ContractField("url"),
    _ContractField("status", type_hint="int|null"),
    _ContractField("duration_ms", type_hint="int"),
    _ContractField("body_path", type_hint="str|null", note="응답 본문이 저장된 디스크 경로"),
    _ContractField("headers", type_hint="dict[str,str]"),
    _ContractField("classification",
                   note="OK / BLOCKED_BOT / BLOCKED_IP / BLOCKED_GEO / LOGIN_REQUIRED / NOT_FOUND / METHOD_INCOMPATIBLE / UNKNOWN_ERROR / SKIPPED"),
    _ContractField("notable", type_hint="list[str]"),
    _ContractField("error", type_hint="str|null"),
)


_ARTIFACTS: dict[str, ArtifactContract] = {
    # ----------------------------------------------------------------- #
    # diagnosis.json — probe/report.py:write_summary 가 씀
    # ----------------------------------------------------------------- #
    "diagnosis.json": ArtifactContract(
        file_name="diagnosis.json",
        payload_kind="object",
        fields=(
            _ContractField("slug"),
            _ContractField("url"),
            _ContractField("verdict", note="전체 진단 한 줄 — 'BASELINE_BLOCKED / 정적 HTTP로 충분' 같은"),
            _ContractField("recommended_strategy",
                           note="권장 진입 전략 — 'httpx (S1.H2)' / 'playwright (S4)' 등"),
            # 프롬프트는 static_ok_request_headers/captured_headers 로 참조 — alias
            _ContractField("recommended_headers", type_hint="dict[str,str]",
                           note="권장 헤더 — 통과한 정적 프리셋의 request 헤더",
                           prompt_aliases=("static_ok_request_headers", "captured_headers")),
            # 프롬프트는 polite_sleep / crawl_delay 로 참조 — alias
            _ContractField("recommended_polling_interval_sec", type_hint="int",
                           note="권장 폴링 간격 (robots crawl-delay 반영)",
                           prompt_aliases=("polite_sleep", "crawl_delay")),
            _ContractField("list_candidates_summary",
                           note="글 목록 후보 요약 (사람용)"),
            _ContractField("article_entry_ok", type_hint="bool",
                           note="글 페이지 진입 성공 여부"),
            _ContractField("notes", type_hint="list[str]",
                           note="probe 가 감지한 특이사항 / LLM 에게 보내는 hint"),
            _ContractField("results", type_hint="list[dict]",
                           note="진입 시도 결과 매트릭스 (각 strategy×target)"),
            _ContractField("baseline", type_hint="dict[str,dict]",
                           note="phase 1 baseline ping 결과"),
        ),
        list_item_fields={"results": _DIAGNOSIS_RESULT_FIELDS,
                          "baseline": _DIAGNOSIS_RESULT_FIELDS},
    ),

    # ----------------------------------------------------------------- #
    # list_candidates.json — probe/extract.py:write_list_candidates
    # ----------------------------------------------------------------- #
    "list_candidates.json": ArtifactContract(
        file_name="list_candidates.json",
        payload_kind="object",
        fields=(
            _ContractField("first_article_url", type_hint="str|null",
                           note="HTML 후보 중 '진짜 글 페이지' 같은 URL 1개 — pick_first_article_url 산출"),
            _ContractField("html_repeating_patterns", type_hint="list[dict]",
                           note="같은 시그니처 자식 ≥5 인 반복 패턴 — selector / sample_url / href_pattern_guess / row_data_attrs / href_is_js / child_count"),
            _ContractField("traffic_json_api_candidates", type_hint="list[dict]",
                           note="HAR 의 JSON 응답 중 글 목록 같은 것 — relevance_score 내림차순 정렬, list_hits 포함"),
            _ContractField("hydration_list_candidates", type_hint="list[dict]",
                           note="__NEXT_DATA__/__NUXT__/__INITIAL_STATE__ 안 글 목록 배열 — sample_first 안 키 보고 LLM 이 path/fields 추론",
                           prompt_aliases=("hydration",)),
            _ContractField("inline_js_data_candidates", type_hint="list[dict]",
                           note="<script type=application/json> JSON island / var X=[...] / X.push({...}) — kind=json_island/js_array/js_push"),
            _ContractField("runtime_id_candidates", type_hint="list[dict]",
                           note="HTML 안 *런타임 ID/슬러그* 후보 — URL path 에 없지만 사이트가 페이지에 명시한 cafe_id/board_id/community_id 등. "
                                "각 dict: {name, value, source: 'js_var'|'next_data'|'meta_og_url', context}. config 작성자가 이 값을 "
                                "kwargs / url_template / handwritten adapter 매개변수에 *고정값* 으로 박을 수 있음."),
            _ContractField("row_external_host", type_hint="dict|null", required=False,
                           note="list row 후보들의 sample_url host 가 base_url host 와 다른 비율 — 검색결과/aggregator 검출 신호. "
                                "None=의미 있는 row 후보 0건. dict={base_host, total_count, external_count, external_ratio, sample_external_urls}. "
                                "external_ratio≥0.8 이면 검색결과/aggregator 일 가능성 — article body 통합 추출 불가, "
                                "config 작성자는 article 섹션 생략 또는 article.skip_status:[200] 박아 본문 fetch 시도 짧게 끊을 것."),
            _ContractField("row_interactive_action", type_hint="dict|null", required=False,
                           note="list row 의 first_text 안 *액션 UI* 키워드 매칭 — 게임 디렉토리/투표/SPA 검출 신호. "
                                "None=매칭 0건. dict={matched_row_count, matched_keyword_set, sample_row_first_text, is_interactive_action}. "
                                "is_interactive_action=true 면 본문 없는 사이트일 가능성 — article.body_empty_acceptable:true 박을 것."),
            _ContractField("body_empty_likely", type_hint="bool", required=False,
                           note="본문 없는 사이트 summary — row_external_host(external_ratio≥0.8) OR row_interactive_action(is_interactive_action=true) 둘 중 하나면 true. "
                                "true 면 article.body_empty_acceptable:true 박고 article.content selector 시도 안 해도 됨 (retry 단축)."),
            _ContractField("nav_only_same_host", type_hint="dict|null", required=False,
                           note="같은-host repeating pattern 의 DOM ancestor 가 *전부* nav/aside/header/footer (또는 role=navigation/complementary/banner/contentinfo) 안인가 — single-article 페이지 신호. "
                                "None=의미 있는 same-host pattern 0건. dict={base_host, total_same_host, in_nav, outside_nav, nav_only_same_host, sample_nav_ancestors}. "
                                "nav_only_same_host=true 면 사이드바/topic-nav 메뉴만 잡혀 main content 의 board list 없음 → 폴링 의미 X. "
                                "scripts/register.py `_single_article_nav_only_check` 가 board_shape 게이트 *전* 에 이 신호로 거부."),
            _ContractField("article_meta_signals", type_hint="dict|null", required=False,
                           note="페이지가 *단일 article* 임을 선언한 명시 meta 신호 — og:type=article + schema.org JSON-LD `@type` (NewsArticle/Article/BlogPosting/...) + microdata itemtype. "
                                "None=신호 0건. dict={has_og_article, schema_article_types, has_microdata_article, is_article_page, signals}. "
                                "is_article_page=true AND first_article_url 의 path-prefix 가 input URL 과 *다르면* `_meta_article_diverging_check` 가 거부 — "
                                "보드 페이지가 우연히 article 마크업 박은 경우(omate 등)는 first_article 이 같은 path-prefix 라 통과 (false-positive 차단)."),
            _ContractField("root_marketing_homepage", type_hint="dict|null", required=False,
                           note="root 도메인 URL 의 마케팅 랜딩/허브 페이지 검출 — board 정의 자체 X. "
                                "None=조건 미충족. dict={is_root_marketing_homepage, marketing_hits, marketing_selectors, total_same_host, body_empty_likely}. "
                                "트리거: path='/' AND html_repeating_patterns top7 중 nav/footer/dropdown/carousel/swiper/menu 키워드 ≥ 2 AND same-host article rows ≤ 15. "
                                "register.py `_root_marketing_homepage_check` 가 이 신호 보고 LLM 호출 *전* REJECTED 마커 + 카테고리/섹션 URL 권장 메시지. "
                                "learn=False — root 만 차단, 카테고리 path 는 진짜 board 가능성 있어 path_prefix 차단 X."),
            _ContractField("wordpress_platform", type_hint="dict|null", required=False,
                           note="WordPress REST API discovery marker(`<link rel=https://api.w.org/>`, generator meta, wp-content/wp-json asset) — "
                                "detect_wordpress_platform 산출. None=WordPress 아님. dict={is_wordpress, api_base, posts_endpoint}. "
                                "scripts/register.py 가 is_wordpress=true 면 LLM 호출 *전* `engine/recognizers/wordpress.build_config` 로 "
                                "`<api_base>/wp/v2/<post_type>` httpx_json config 등록을 시도한다."),
            _ContractField("discourse_platform", type_hint="dict|null", required=False,
                           note="정적 HTML 의 `<meta name=generator content=Discourse>` 로 Discourse 포럼 판정 — detect_discourse_platform 산출. "
                                "None=Discourse 아님. dict={is_discourse, base_url, version}. "
                                "Discourse 는 Ember.js shell 이라 정적에 topic rows 없어 LLM 이 posts_nonempty:0 으로 실패하지만 generator meta 는 항상 있음. "
                                "scripts/register.py 가 is_discourse=true 면 LLM 호출 *전* DiscourseAdapter config 만들어 등록 시도 (fetch_list 빈 목록이면 일반 파이프라인 폴백). "
                                "recognizer(`engine/recognizers/discourse.py`)는 URL `/latest` 폼만 매칭 — root 도메인은 이 휴리스틱이 봉합."),
            _ContractField("common_platform", type_hint="dict|null", required=False,
                           note="Common/Commonwealth SPA shell marker(`<title>Common</title>`, `/assets/index-*`, `/brand_assets/common`, `/api/internal/trpc`) "
                                "로 Common governance forum 판정 — detect_common_platform 산출. None=Common 아님. "
                                "dict={is_common, base_url, community_id_hint}. scripts/register.py 가 is_common=true 면 LLM 호출 전 "
                                "`engine/recognizers/commonwealth.build_config` + CommonwealthAdapter 로 tRPC thread.getThreads 등록을 시도한다."),
            _ContractField("xenforo_platform", type_hint="dict|null", required=False,
                           note="렌더된 HTML 의 `<html id=XF>` / `XF.config` 마커로 XenForo 포럼 판정 — detect_xenforo_platform 산출. "
                                "None=XenForo 아님. dict={is_xenforo, base_url}. "
                                "scripts/register.py 가 is_xenforo=true 면 LLM 호출 *전* `engine/recognizers/xenforo.build_config` 로 "
                                "`<base>/forums/-/index.rss` 전역 RSS httpx_html config 만들어 등록 시도 (fetch_list 빈 목록=RSS 404/빈/차단이면 일반 파이프라인 폴백)."),
            _ContractField("medium_custom_domain", type_hint="dict|null", required=False,
                           note="Medium custom domain marker(app link meta, medium.com/p canonical, RSS alternate) — "
                                "detect_medium_custom_domain 산출. None=Medium custom domain 아님. "
                                "dict={is_medium_custom, base_url, feed_url}. scripts/register.py 가 Medium RSS XML config 등록을 시도한다."),
            _ContractField("lemmy_platform", type_hint="dict|null", required=False,
                           note="Lemmy SSR/app-shell marker(`window.isoData`, `site_res.local_site`, join-lemmy 링크 등) 로 Lemmy instance 판정 — "
                                "detect_lemmy_platform 산출. None=Lemmy 아님. dict={is_lemmy, base_url, community_name?}. "
                                "scripts/register.py 가 is_lemmy=true 면 LLM 호출 *전* `engine/recognizers/lemmy.build_config` 로 "
                                "LemmyAdapter config 를 만들어 `/api/v3/post/list?sort=New&type_=Local` 공개 JSON API 등록을 시도."),
            _ContractField("mastodon_platform", type_hint="dict|null", required=False,
                           note="Mastodon app-shell marker(`<div id=mastodon>`, initial-state streaming_api, generator meta 등) 로 social instance 판정 — "
                                "detect_mastodon_platform 산출. None=Mastodon 아님. dict={is_mastodon, base_url}. "
                                "Mastodon root/about 는 notice board 가 아니라 social firehose/client shell 이므로 scripts/register.py 가 LLM 호출 전 REJECTED 처리한다."),
            _ContractField("misskey_platform", type_hint="dict|null", required=False,
                           note="Misskey app-shell marker(`_misskey_`, `window.__misskey`, og/title Misskey 등) 로 social instance 판정 — "
                                "detect_misskey_platform 산출. None=Misskey 아님. dict={is_misskey, base_url}. "
                                "notice board 가 아니라 social timeline/client shell 이므로 scripts/register.py 가 LLM 호출 전 REJECTED 처리한다."),
            _ContractField("pixelfed_platform", type_hint="dict|null", required=False,
                           note="Pixelfed app-shell marker(Pixelfed meta/generator, window.App.config 등) 로 social instance 판정 — "
                                "detect_pixelfed_platform 산출. None=Pixelfed 아님. dict={is_pixelfed, base_url}. "
                                "notice board 가 아니라 social media client shell 이므로 scripts/register.py 가 LLM 호출 전 REJECTED 처리한다."),
            _ContractField("peertube_platform", type_hint="dict|null", required=False,
                           note="PeerTube app-shell marker(`og:platform=PeerTube`, `window.PeerTubeServerConfig`, `/api/v1/config`) 로 PeerTube instance 판정 — "
                                "detect_peertube_platform 산출. None=PeerTube 아님. dict={is_peertube, base_url}. "
                                "scripts/register.py 가 is_peertube=true 면 LLM 호출 *전* `engine/recognizers/peertube.build_config` 로 "
                                "PeerTubeAdapter config 를 만들어 `/api/v1/videos?sort=-publishedAt` 공개 JSON API 등록을 시도."),
            _ContractField("mbin_platform", type_hint="dict|null", required=False,
                           note="Mbin/kbin marker(`data-controller=mbin`, mbin/kbin+fediverse meta, threads/microblog/magazines nav) 로 aggregator instance 판정 — "
                                "detect_mbin_platform 산출. None=Mbin 아님. dict={is_mbin, base_url, magazine_name?}. "
                                "scripts/register.py 가 is_mbin=true 면 LLM 호출 *전* `engine/recognizers/mbin.build_config` 로 "
                                "`/api/entries?sort=newest` httpx_json config 등록을 시도한다. API 401/anti-bot instance 는 폴백."),
        ),
    ),

    # ----------------------------------------------------------------- #
    # robots.json — probe/discover.py:read_robots
    # ----------------------------------------------------------------- #
    "robots.json": ArtifactContract(
        file_name="robots.json",
        payload_kind="object",
        fields=(
            _ContractField("url", note="robots.txt URL"),
            _ContractField("status", type_hint="int|null", note="robots.txt HTTP status"),
            _ContractField("crawl_delay", type_hint="float|null",
                           note="robots.txt 의 Crawl-Delay (config 의 polite_sleep 에 반영)"),
            _ContractField("disallow", type_hint="list[str]",
                           note="robots.txt 의 Disallow 패턴 (config 등록 거부 판단)"),
            _ContractField("sitemaps", type_hint="list[str]",
                           note="robots.txt 의 Sitemap: 라인 (RFC 9309). fetch_sitemaps 의 seed."),
            _ContractField("raw_path", type_hint="str|null", required=False,
                           note="robots.txt 원본을 디스크에 저장한 경로"),
            _ContractField("error", type_hint="str", required=False,
                           note="요청 실패 시 에러 메시지"),
        ),
        optional_on_disk=True,
    ),

    # ----------------------------------------------------------------- #
    # sitemap.json — probe/discover.py:fetch_sitemaps
    # ----------------------------------------------------------------- #
    "sitemap.json": ArtifactContract(
        file_name="sitemap.json",
        payload_kind="object",
        fields=(
            _ContractField("page_url", note="probe seed URL"),
            _ContractField("sitemap_urls_tried", type_hint="list[str]",
                           note="실제 fetch 시도한 sitemap.xml URL 들 (robots 의 Sitemap: + 표준 경로 폴백)"),
            _ContractField("candidates", type_hint="list[dict]",
                           note="발견한 board page 후보 URL — board-like 점수 내림차순. cap 100. "
                                "config_writer 가 사용자 URL 이 board 아닐 때 list.url_template 후보로 사용."),
            _ContractField("stats", type_hint="dict",
                           note="{sitemap_count, fetched, errors, out_total} — 디버깅용."),
            _ContractField("error", type_hint="str|null", required=False,
                           note="실패 시 에러 메시지 (전체 실패 — fail-soft 라 candidates=[])"),
        ),
        list_item_fields={"candidates": (
            _ContractField("url"),
            _ContractField("score", type_hint="int",
                           note="board-like 점수 — keyword(notice/bbs/board/news/공지/게시판) + ID query + 숫자 path + depth"),
        )},
        optional_on_disk=True,
    ),

    # ----------------------------------------------------------------- #
    # feed_candidates.json — probe/discover.py:discover_feeds
    # ----------------------------------------------------------------- #
    "feed_candidates.json": ArtifactContract(
        file_name="feed_candidates.json",
        payload_kind="object",
        fields=(
            _ContractField("page_url"),
            _ContractField("candidates", type_hint="list[dict]",
                           note="RSS/Atom feed 후보 — head <link rel=alternate> + well-known paths"),
        ),
        list_item_fields={"candidates": (
            _ContractField("source", note="'head-alternate' | 'well-known-path' | 'page-feed-link' | 'page-path-fallback'"),
            _ContractField("url"),
            _ContractField("type", required=False, type_hint="str|null"),
            _ContractField("title", required=False, type_hint="str|null"),
            _ContractField("status", required=False, type_hint="int"),
            _ContractField("content_type", required=False, type_hint="str"),
            _ContractField("size", required=False, type_hint="int"),
        )},
        optional_on_disk=True,
    ),

    # ----------------------------------------------------------------- #
    # article_click.json — probe/fetch_headless.py:fetch_article_by_click (phase 9b)
    # ----------------------------------------------------------------- #
    "article_click.json": ArtifactContract(
        file_name="article_click.json",
        payload_kind="object",
        fields=(
            _ContractField("requested_url", note="클릭 시작 URL (목록 페이지)"),
            _ContractField("resolved_url", type_hint="str|null",
                           note="실제로 클릭해 도달한 최종 URL — 클라이언트 라우트 검출 핵심",
                           prompt_aliases=("clicked_resolved_url",)),
            _ContractField("status", type_hint="int|null"),
            _ContractField("clicked_text", type_hint="str|null"),
            _ContractField("clicked_href", type_hint="str|null",
                           note="클릭한 <a> 의 href 원본 ('' 면 JS 핸들러)"),
            _ContractField("note", type_hint="str|null",
                           note="클릭 실패 등 상태 메모"),
        ),
        optional_on_disk=True,
    ),

    # ----------------------------------------------------------------- #
    # article_candidates.json — scripts/register.py:_reprobe_article
    #   (probe/extract.py:traffic_article_body_candidates 결과를 그대로 dump)
    # ----------------------------------------------------------------- #
    "article_candidates.json": ArtifactContract(
        file_name="article_candidates.json",
        payload_kind="object_list",
        item_fields=(
            _ContractField("method"),
            _ContractField("url"),
            _ContractField("status", type_hint="int|null"),
            _ContractField("content_type"),
            _ContractField("request_headers", type_hint="dict[str,str]"),
            _ContractField("request_body_text", required=False, type_hint="str|null"),
            _ContractField("body_field_path", type_hint="list[str|int]",
                           note="엔진 from:json path 형식 — 본문 문자열의 JSON 안 경로"),
            _ContractField("body_len", type_hint="int"),
            _ContractField("body_looks_html", type_hint="bool",
                           note="본문 문자열이 HTML 태그를 포함하는가"),
            _ContractField("body_key"),
            _ContractField("url_id_match", type_hint="bool",
                           note="URL 에 글 ID 가 들어있는가 — score 가산 신호"),
            _ContractField("sample", required=False, type_hint="str",
                           note="본문 첫 300자 샘플"),
        ),
        optional_on_disk=True,
    ),
}


# --------------------------------------------------------------------------- #
# 프롬프트(prompts/config_writer.system.txt)에 워드바운더리로 등장해야 하는 키.
# 명시적 whitelist — must_appear_in_prompt 필드 메타 제거 후 단일 진실원.
# stage1c 는 각 entry 의 키 이름 자체 + 해당 _ContractField.prompt_aliases 를 매칭.
# 누락은 WARN (rename 잊었나 신호 — FAIL 차단은 안 함).
# --------------------------------------------------------------------------- #
_PROMPT_REQUIRED_KEY_PATHS: tuple[tuple[str, str], ...] = (
    # diagnosis.json
    ("diagnosis.json", "url"),
    ("diagnosis.json", "verdict"),
    ("diagnosis.json", "recommended_strategy"),
    ("diagnosis.json", "recommended_headers"),
    ("diagnosis.json", "recommended_polling_interval_sec"),
    ("diagnosis.json", "notes"),
    # list_candidates.json — 3번 (글 url 후보) 핵심
    ("list_candidates.json", "first_article_url"),
    ("list_candidates.json", "html_repeating_patterns"),
    ("list_candidates.json", "traffic_json_api_candidates"),
    ("list_candidates.json", "hydration_list_candidates"),
    ("list_candidates.json", "inline_js_data_candidates"),
    ("list_candidates.json", "runtime_id_candidates"),
    ("list_candidates.json", "body_empty_likely"),
    # robots.json
    ("robots.json", "crawl_delay"),
    # article_click.json
    ("article_click.json", "resolved_url"),
    # article_candidates.json (item)
    ("article_candidates.json", "url"),
    ("article_candidates.json", "body_field_path"),
    ("article_candidates.json", "body_looks_html"),
    ("article_candidates.json", "url_id_match"),
)


# --------------------------------------------------------------------------- #
# 공개 API
# --------------------------------------------------------------------------- #
OUTPUT_SCHEMA: dict[str, ArtifactContract] = _ARTIFACTS


def get_contract(file_name: str) -> ArtifactContract:
    """파일명 → ArtifactContract. 모르는 파일명이면 KeyError."""
    try:
        return _ARTIFACTS[file_name]
    except KeyError:
        raise KeyError(
            f"unknown artifact: {file_name!r}. "
            f"known: {sorted(_ARTIFACTS)}"
        )


def required_keys(file_name: str, *, list_key: Optional[str] = None) -> tuple[str, ...]:
    """필수 키 튜플. list_key 가 주어지면 그 list 안 item 의 필수 키 (top-level X)."""
    c = get_contract(file_name)
    if list_key is not None:
        items = c.list_item_fields.get(list_key) or c.item_fields
        return tuple(f.name for f in items if f.required)
    if c.payload_kind == "object_list":
        return tuple(f.name for f in c.item_fields if f.required)
    return tuple(f.name for f in c.fields if f.required)


def optional_keys(file_name: str, *, list_key: Optional[str] = None) -> tuple[str, ...]:
    c = get_contract(file_name)
    if list_key is not None:
        items = c.list_item_fields.get(list_key) or c.item_fields
        return tuple(f.name for f in items if not f.required)
    if c.payload_kind == "object_list":
        return tuple(f.name for f in c.item_fields if not f.required)
    return tuple(f.name for f in c.fields if not f.required)


def all_keys(file_name: str, *, list_key: Optional[str] = None) -> tuple[str, ...]:
    return required_keys(file_name, list_key=list_key) + optional_keys(file_name, list_key=list_key)


def validate_payload(
    file_name: str,
    payload: Any,
    *,
    strict: bool = True,
    allow_extra: bool = True,
) -> Optional[list[str]]:
    """write 직전 호출. payload 의 필수 키 누락 / 모르는 키 / 타입 불일치 검사.

    strict=True (기본): 위반 발견 시 ContractError raise.
    strict=False: 위반 메시지 list 반환 (없으면 빈 list). digest.py 의 silent-tolerant 읽기에 적합.
    allow_extra=False: 모르는 키 발견 시 ContractError (write 측 보호 — 오타 차단).

    payload_kind="object" 인 contract 에 list payload 등 타입 mismatch 면 ContractError.
    """
    c = get_contract(file_name)
    violations: list[str] = []

    # payload type 검증
    if c.payload_kind == "object_list":
        if not isinstance(payload, list):
            violations.append(f"{file_name}: payload type — expected list, got {type(payload).__name__}")
        else:
            for i, item in enumerate(payload):
                if not isinstance(item, dict):
                    violations.append(f"{file_name}[{i}]: item type — expected dict, got {type(item).__name__}")
                    continue
                _check_dict(item, c.item_fields, where=f"{file_name}[{i}]",
                            allow_extra=allow_extra, violations=violations)
    elif c.payload_kind == "object":
        if not isinstance(payload, dict):
            violations.append(f"{file_name}: payload type — expected dict, got {type(payload).__name__}")
        else:
            _check_dict(payload, c.fields, where=file_name,
                        allow_extra=allow_extra, violations=violations)
            # 안의 list-typed 필드 item 검증
            for list_key, item_fields in c.list_item_fields.items():
                lst = payload.get(list_key)
                if isinstance(lst, list):
                    for i, item in enumerate(lst):
                        if not isinstance(item, dict):
                            violations.append(
                                f"{file_name}.{list_key}[{i}]: item type — expected dict, got {type(item).__name__}"
                            )
                            continue
                        _check_dict(item, item_fields, where=f"{file_name}.{list_key}[{i}]",
                                    allow_extra=allow_extra, violations=violations)
                # baseline 같은 dict[str, Result] 형태는 dict 일 수도
                elif isinstance(lst, dict):
                    for k, v in lst.items():
                        if not isinstance(v, dict):
                            violations.append(
                                f"{file_name}.{list_key}[{k!r}]: item type — expected dict, got {type(v).__name__}"
                            )
                            continue
                        _check_dict(v, item_fields, where=f"{file_name}.{list_key}[{k!r}]",
                                    allow_extra=allow_extra, violations=violations)
    else:
        violations.append(f"{file_name}: unknown payload_kind {c.payload_kind!r}")

    if strict and violations:
        raise ContractError("\n  - ".join(["contract violation:", *violations]))
    return violations if not strict else None


def _check_dict(
    d: dict,
    fields: tuple[_ContractField, ...],
    *,
    where: str,
    allow_extra: bool,
    violations: list[str],
) -> None:
    field_names = {f.name for f in fields}
    for f in fields:
        if f.required and f.name not in d:
            violations.append(f"{where}: missing required key {f.name!r}")
    if not allow_extra:
        extra = set(d) - field_names
        if extra:
            violations.append(f"{where}: unknown keys {sorted(extra)!r}")


def _find_field(c: ArtifactContract, name: str) -> Optional[_ContractField]:
    """contract 안에서 주어진 name 의 _ContractField 찾기 — top-level fields / item_fields / list_item_fields 순회."""
    for f in c.fields:
        if f.name == name:
            return f
    for f in c.item_fields:
        if f.name == name:
            return f
    for items in c.list_item_fields.values():
        for f in items:
            if f.name == name:
                return f
    return None


def prompt_required_keys() -> dict[str, tuple[str, ...]]:
    """프롬프트 워드바운더리 검사 대상.

    key_id (= '<file>:<key>') → (키 이름,) + 해당 _ContractField.prompt_aliases
    smoke stage1c 가 prompts/config_writer.system.txt 에서 하나라도 매칭되면 OK.
    """
    out: dict[str, tuple[str, ...]] = {}
    for fname, kname in _PROMPT_REQUIRED_KEY_PATHS:
        c = get_contract(fname)
        f = _find_field(c, kname)
        aliases = tuple(f.prompt_aliases) if f else ()
        out[f"{fname}:{kname}"] = (kname,) + aliases
    return out


# --------------------------------------------------------------------------- #
# 상수 alias (smoke / engine.digest 가 import 해서 쓰는 키 목록)
# 이 alias 들은 단순 편의 — 실제 검증은 OUTPUT_SCHEMA 기준.
# --------------------------------------------------------------------------- #
LIST_CANDIDATES_KEYS: tuple[str, ...] = required_keys("list_candidates.json")
DIAGNOSIS_TOP_KEYS: tuple[str, ...] = required_keys("diagnosis.json")
DIAGNOSIS_RESULT_KEYS: tuple[str, ...] = required_keys("diagnosis.json", list_key="results")
ROBOTS_KEYS: tuple[str, ...] = required_keys("robots.json")
FEED_CANDIDATES_KEYS: tuple[str, ...] = required_keys("feed_candidates.json")
ARTICLE_CLICK_KEYS: tuple[str, ...] = required_keys("article_click.json")
ARTICLE_CANDIDATES_ITEM_KEYS: tuple[str, ...] = required_keys("article_candidates.json")


__all__ = [
    "ContractError",
    "ArtifactContract",
    "OUTPUT_SCHEMA",
    "get_contract",
    "required_keys",
    "optional_keys",
    "all_keys",
    "validate_payload",
    "prompt_required_keys",
    "LIST_CANDIDATES_KEYS",
    "DIAGNOSIS_TOP_KEYS",
    "DIAGNOSIS_RESULT_KEYS",
    "ROBOTS_KEYS",
    "FEED_CANDIDATES_KEYS",
    "ARTICLE_CLICK_KEYS",
    "ARTICLE_CANDIDATES_ITEM_KEYS",
]
