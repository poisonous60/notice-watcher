---
slug: host_developer-andro_studio_d78fec02
url: https://developer.android.com/studio/releases
status: "✅ 등록 (Android Studio latest release page, static Devsite HTML)"
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [gate_reject, meta_diverging, single_article_page, devsite_static_release_page]
config_strategy: httpx_html
adapters_changed:
engine_files_touched: []
tags: [manual-config, devsite, android-studio, release-notes, static-html]
requested_by: unknown
---

## 트리거

`https://developer.android.com/studio/releases` 자동 등록 실패 큐 처리.

사용자 제공 요약은 `rc=5 capability_blocked` 였으나, 이 worktree 에는 기존
`output/poll_state/host_developer-andro_studio_d78fec02.FAILED.json` 및 probe artifact 가 없었다.
직접 `register.py` 를 재현하니 현재 코드에서는 `.REJECTED.json` 이 생성됐다.

## 진단

preflight: `miss — host_developer-andro_studio_d78fec02`.

- `configs/host_developer-andro_studio_d78fec02.json` 없음.
- `engine.recognizers.recognize("https://developer.android.com/studio/releases")` 결과 `None`.
- 기존 `.FAILED.json`/probe artifact 부재. 직접 재현으로 새 artifact 를 만들었다.

직접 재현 결과:

- `diagnosis.verdict`: `JS 실행 필요 (Cloudflare 등)`
- `first_article_url`: `https://developer.android.com/gemini-in-android`
- `article_meta_signals.schema_article_types`: `["Article"]`
- `register.py`: `단일 article (meta 선언 + 발산 first_article)` 로 거부

실제 HTML 확인 결과, `developer.android.com/studio/releases` 는 Devsite 문서 페이지라
`schema.org/Article` 을 달고 있지만 사용자가 감시하려는 대상은 "현재 Android Studio 최신 릴리스"이다.
정적 HTML 안에 `article.devsite-article`, `h1.devsite-page-title`,
`/studio/releases/fixed-bugs/studio/2025.3.4` 링크가 모두 존재한다.

RSS 대안도 확인했지만 `/feeds`, `/feeds/android-release-notes.xml`,
`/feeds/android-studio-release-notes.xml`, `/studio/releases.xml`,
`/studio/releases/feed.xml` 은 모두 404였고 robots.txt 는 sitemap 만 노출했다.

## 픽스

수동 config 1개를 추가했다.

- `strategy: httpx_html`
- `row_selector: article.devsite-article`
- `post_id`: fixed-bugs 링크의 Studio 버전 (`2025.3.4`)
- `title`: `h1.devsite-page-title`
- `url`: `https://developer.android.com/studio/releases`
- `content`: `div.devsite-article-body`
- `polite_sleep`: 5~8초

이 config 는 페이지 전체를 한 행짜리 최신 릴리스 보드로 취급한다. 새 Android Studio 릴리스가 나오면
fixed-bugs 링크 버전과 제목이 바뀌어 새 post_id 로 감지된다.

## 트랙 B 후보

- **2a (인식기 PATTERNS 확장)**: X — Devsite 전체 플랫폼 일반화는 가능하지만, Firebase support releases 처럼 앵커-glob/본문 분할 문제가 있는 페이지도 있어 단일 사이트 config 로 제한했다.
- **2b (--article-url)**: X — first_article_url 오인이 원인 중 하나지만, Gemini 재시도보다 단일 최신 릴리스 페이지를 한 행으로 보는 config 가 더 단순하다.
- **2c/2d (probe/register 게이트 개선)**: 보류 — `single_article_page` 와 `meta.*Article` 누적은 많고 track-B trigger 는 켜져 있다. 다만 이번 페이지를 generic gate escape 로 풀면 진짜 단일 article false-negative 위험이 있어, 분류기/게이트 일반화는 별도 작업으로 남긴다.
- **2e (수동 config)**: O — 사이트 전용 정적 selector 로 해결.

## 회귀 검증

영향 범위는 새 config 파일 1개뿐이다. 공유 engine/probe/prompt/recognizer를 변경하지 않았으므로 기존 configs에 대한 구조적 영향은 없다.

실행 결과:

- `python scripts/register.py --config configs/host_developer-andro_studio_d78fec02.json` → baseline 1건, post_id `2025.3.4`, title `Android Studio Panda 4`
- 직접 adapter 실행 → `fetch_list` 1건, `fetch_article` content length 222,937

