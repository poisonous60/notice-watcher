---
slug: host_bursamalaysia-c_about_bursa_216b55e3
url: https://www.bursamalaysia.com/about_bursa/media_centre
status: 🧩 수동 config — Bursa Malaysia media releases PDF 목록 10건 등록 가능
outcome: handcrafted
date: 2026-05-24
failure_keys: [posts_nonempty, cloudflare_challenge, static_stacktable_rows, pdf_only_articles]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [bursamalaysia, media-releases, pdf, playwright-html]
---

## 무엇이 일어났나

`/about_bursa/media_centre` 는 Bursa Malaysia 의 media centre landing 이고, 실제 media releases 목록은
같은 페이지 안의 `media-releases-table` 로 렌더된다. 자동 생성기는 반복 후보를 보긴 했지만
`DataTables_Table_0` 하위 `tr` 를 row 로 잡는 config 를 반복 생성했고, 현재 검증 경로에서는 0건이 나왔다.

`last_feedback`:

- `[FAIL] posts_nonempty: 0건`
- `[warn] matches_probe_first_article: probe first_article_url=...pdf?... 와 일치하는 글 URL 없음`
- `[warn] count_ballpark: 0건 (probe 후보 child_count≈21)`

`diagnosis.json` verdict 는 `CLOUDFLARE_PROTECTED_SITE / 정적 HTTP로 충분` 이었다. 다만 dev box 의 plain
`httpx` 는 같은 Chrome 계열 헤더로도 Cloudflare challenge 403 을 받았고, probe 의 browser entry 및
`playwright_html` 실행은 media release table 을 정상 렌더했다.

## 픽스

`configs/host_bursamalaysia-c_about_bursa_216b55e3.json` 을 `playwright_html` config 로 작성했다.

- 목록 URL: `https://www.bursamalaysia.com/about_bursa/media_centre`
- row: `div.cardTable-wrap table.media-releases-table.stacktable.small-only`
- 필드: 각 stacktable table 안의 PDF 링크에서 `post_id/title/url`, `td.st-val.text-center` 에서 날짜 추출
- 본문: 항목이 PDF 링크라 `article.content: []` + `body_empty_acceptable: true`

자동 config 가 잡은 `media_releases?year=all&subject=` URL 은 dev box 직접 `httpx` 에서 403 이었고,
probe artifact 의 HTML 후보는 submitted URL의 browser-rendered DOM 에서 확인됐다.

## 회귀 검증

- preflight
  - `configs/host_bursamalaysia-c_about_bursa_216b55e3.json` 기존 파일 없음
  - `recognize("https://www.bursamalaysia.com/about_bursa/media_centre")` -> `None`
  - FAILED 이후 `prompts/ engine/ probe/ generate/ engine/recognizers/` commit 0건
  - 같은 path uncommitted 변경 0건
- schema validation
  - `OK`
- `make_adapter` smoke
  - `fetch_list()` 10건
  - 첫 5개 post_id 예: `200526_MEDIA_NOTIFICATION_CLOSURE_OF_BURSA_MALAYSIA_IN_CONJUNCTION_WITH_THE_AIDILADHA__BIRTHDAY_OF_HIS_MAJESTY_YANG_DI-PERTUAN_AGONG___WESAK_PUBLIC_HOLIDAYS`, `180526_MEDIA_RELEASE_SC_AND_BURSA_MALAYSIA_PROPOSE_LEAP_MARKET_ENHANCEMENTS`
  - 첫 글 `fetch_article()` 는 PDF URL fetch 후 body length 0, config 에서 body empty 허용
- `python scripts/register.py --config ...`
  - 실행하지 않음. 이번 Codex handoff 제한이 `output/triage_queue.*` 와 `output/poll_state/` 변경 금지라서
    `.FAILED.json` 자동 정리 부작용을 피했다.
- `cases_index.py query/backfill` 및 `docs/cases/INDEX.md`
  - 실행하지 않음. 사용자 hard stop 이 `cases_index.py` 실행, `--backfill-db`, `INDEX.md` 변경을 금지했다.

## 트랙 B 검토

- **2a (플랫폼 config) — X.** Bursa Malaysia 단일 사이트의 media centre/PDF 목록 패턴이다. 재사용 가능한
  platform recognizer 로 보기 어렵다.
- **2b (`--article-url`) — X.** first article 은 실제 PDF 링크다. 문제는 첫 글 오인이 아니라 row selector root 와
  실행 strategy 선택이다.
- **2c (probe digest 신호) — 보류.** probe 는 `stacktable.small-only` 후보와 child_count 를 이미 노출했다.
  이번 실패는 그 신호를 config writer 가 선택하지 못한 단일 사이트 해석 문제라 새 휴리스틱을 추가하지 않았다.
- **2d (probe 오작동) — X.** browser probe 는 table/PDF 후보를 정상 산출했다.
- **2e (수동 config) — O.** `playwright_html` + stacktable row selector 로 바로 동작한다.

일반화 안 되는 이유: 이 config 는 Bursa Malaysia 의 특화 DOM 과 PDF-only 보도자료 구조에 묶여 있다. 같은
`posts_nonempty` 실패라도 generic probe/engine 변경으로 묶기에는 이번 slug 하나만으로 근거가 부족하다.

## 자가 점검 (§6)

1. **자리**: none/config only. 새 adapter/engine/probe/prompt/schema 변경 없음.
2. **이전 케이스**: 사용자 지시로 `cases_index.py query` 실행 금지. 누적 cross-check 는 생략했다.
3. **누구 깰까**: 새 config 파일 1개만 추가하므로 기존 config 영향 0.
4. **검증**: schema OK, make_adapter list 10건 및 PDF fetch 확인. `probe_smoke --stage 3 --stage 5` 는 별도 실행.
5. **outcome=handcrafted**: 단일 사이트 config 작성이며 generic 추론 개선이 아니다.
6. **fixture**: 새 strategy/heuristic 이 아니라 기존 `playwright_html` 사용이라 별도 fixture 추가 없음.
7. **트랙 B 사유**: 위 §트랙 B 검토 참조.
