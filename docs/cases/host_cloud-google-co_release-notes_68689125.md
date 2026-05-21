---
slug: host_cloud-google-co_release-notes_68689125
url: https://cloud.google.com/release-notes
status: ✅ 해결 (Google Cloud release notes 공식 Atom feed recognizer + adapter)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [probe_timeout, static_docs_changelog, official_feed_available]
config_strategy: handwritten
adapters_changed: [adapters/google_cloud_release_notes.py]
engine_files_touched: [engine/recognizers/google_cloud_release_notes.py]
tags: [google-cloud, release-notes, atom-feed, recognizer, slug-stable]
requested_by: unknown
---

## 무엇이 일어났나

대상 URL:

```
https://cloud.google.com/release-notes
```

preflight 결과 기존 config와 recognizer는 없었다. 로컬 재현:

```
[FAIL] probe_timeout: probe timeout (120s)
```

timeout 전에 남은 `list_candidates.json`에는 정적 row 신호가 잡혔다.

- `section.releases > div.devsite-release-note` 2368건
- `section.releases > h2` 날짜 heading 57건
- `first_article_url=https://cloud.google.com/docs/ai-ml` 로 제품 문서 링크를 첫 글로 오인

공식 문서 페이지는 feed 구독을 안내하며, 실제 feed URL은 다음 Atom feed로 200 응답한다.

```
https://cloud.google.com/feeds/gcp-release-notes.xml
```

## 원인

HTML 페이지가 매우 크고 release note 행 안의 첫 링크가 CVE/제품문서 등 외부·내부 참고 링크라,
generic probe가 글 URL을 안정적으로 고르기 어렵다. 이번 재현에서는 config 생성 단계까지 가지 못하고
probe 120초 timeout으로 `.FAILED.json`이 생성됐다.

## 해결

`GoogleCloudReleaseNotesAdapter`와 exact recognizer를 추가했다.

- recognizer는 `cloud.google.com/release-notes`와 `docs.cloud.google.com/release-notes`만 매칭한다.
- slug migration을 피하려고 `NAME="host_cloud-google-co"`, `_slug_board="release-notes"`로 기존 fallback slug를 유지했다.
- adapter는 공식 Atom feed를 가져온다.
- Atom entry 1개는 날짜 단위라 그대로 쓰면 같은 날짜에 새 release note가 추가돼도 새 글로 감지하기 어렵다.
- 그래서 entry의 HTML content를 `h2` product + `h3` kind + following body 단위로 쪼개고,
  `entry_id + product + kind + text` SHA1 앞 20자를 stable `post_id`로 쓴다.

config는 recognizer가 자동 발급하며 `strategy=handwritten`,
`adapter=GoogleCloudReleaseNotesAdapter` 경로를 사용한다.

## robots / polite_sleep

Google Cloud가 공개 Atom feed를 제공한다. adapter는 feed 1회 fetch 후 3~6초 `polite_sleep`를 적용한다.
HTML probe 반복보다 호출 수가 적고, 구독용 feed를 직접 사용하는 경로라 `docs/크롤링 지침.md`의 우회 금지 원칙에도 맞는다.

## 일반화 검토

- 2a platform recognizer: O. Google Cloud 전체 release notes URL은 이후 probe/LLM 없이 등록된다.
- 2b `--article-url`: X. 첫 글 URL 교정은 probe timeout과 Atom feed 존재를 해결하지 못한다.
- 2c probe heuristic: X. generic static docs changelog 개선 여지는 있지만, 이 URL은 공식 feed가 있어 전용 recognizer가 더 작다.
- 2d probe bug: X. timeout 증상은 있으나 이번 사이트의 안정 경로는 feed다.
- 2e single config: X. 재발 가능한 Google Cloud release notes URL 클래스라 recognizer가 단일 config보다 낫다.

영향 범위는 exact Google Cloud release notes URL에 한정했다. 제품별 release notes(`/run/docs/release-notes` 등)는 매칭하지 않는다.
