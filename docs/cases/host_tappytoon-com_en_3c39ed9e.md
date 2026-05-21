---
slug: host_tappytoon-com_en_3c39ed9e
url: https://www.tappytoon.com/en/notice
status: ✅ remap 후 손 config 등록 (Freshdesk Notices & News, baseline 10건)
outcome: handcrafted
date: 2026-05-22
requested_by: batch
failure_keys: [probe_timeout, target_not_found, url_remap]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [tappytoon, freshdesk, remap, hand-config, url-dead]
---

## 무엇이 일어났나

초기 실패는 `register probe timeout: probe timeout (120s)` 였다.

`preflight: b-hit-but-no-recovery — host_tappytoon-com_en_3c39ed9e [27ed350, 5665fa8]`.
실패 이후 영향 영역 commit 이 있어 `register.py --reuse-probe "https://www.tappytoon.com/en/notice"` 를
재실행했지만, 원 URL 은 static/headless/captured-header 진입 모두 404 로 판정됐다. 루트와 robots 는
200 이라 사이트 차단이 아니라 입력 URL 자체가 죽은 상태다.

URL remap 확인 결과 `https://www.tappytoon.com/en/notices` 와 `https://www.tappytoon.com/notices` 는
`https://support.tappytoon.com/en/support/solutions/47000495287` 로 리다이렉트된다. 해당 Freshdesk
category 의 `Notices & News` folder 는 `47000726735` 이고, 글 106개가 정적 HTML 목록으로 노출된다.

screen-out: P2 유사 — 원 URL 은 soft-404 가 아니라 HTTP 404/TARGET_NOT_FOUND 로 이미 거부된다. remap 이
확인되어 죽은 URL 에 config 를 쓰지 않고 live folder URL 로 등록했다.

## 무엇을 바꿨나

`configs/host_tappytoon-com_en_3c39ed9e.json` 을 추가했다.

- 원 URL 기록: `_source_url` / `_remapped_from` = `https://www.tappytoon.com/en/notice`
- 실제 목록: `https://support.tappytoon.com/en/support/solutions/folders/47000726735`
- row: `a[href*='/en/support/solutions/articles/'].row`
- post_id: Freshdesk article id (`/articles/<id>`)
- title: `.line-clamp-2`
- published_at: 미추출. Freshdesk folder 의 `Modified on Fri, 15 May...` 표기는 연도가 없어 ISO 로 안전하게
  정규화하지 않는다.
- article body: `.fw-content--single-article`
- polite_sleep: robots 에 Crawl-delay 없음. 기존 운영 기본보다 느린 5~6초로 설정.

## Track B 검토

- 2a 인식기: 보류 — Freshdesk 플랫폼 recognizer 로 넓힐 수는 있지만 이번 지시의 hard-stop 범위와 현재 dirty
  tree 를 고려해 단건 config 만 추가했다. 같은 Freshdesk support 사례가 반복되면 `engine/recognizers/freshdesk.py`
  한 파일로 일반화하는 것이 적절하다.
- 2b first_article_url 교정: X — 원 URL 이 404 라 article URL 힌트로 회복할 문제가 아니다.
- 2c/2d probe/schema/prompt: X — probe 는 재실행 후 TARGET_NOT_FOUND 를 올바르게 잡았다.
- 2e 수동 config: 적용 — remapped Freshdesk folder 는 기존 `httpx_html` 어휘로 충분하다.

일반화 안 되는 이유: 이번 핵심은 `/en/notice` 에서 `/en/notices`/Freshdesk support 로의 사이트별 remap 이다.
공통 Freshdesk recognizer 후보는 남지만, 단건 처리에는 config 추가가 가장 작은 변경이다.

## 회귀 검증

- `python scripts/register.py --reuse-probe "https://www.tappytoon.com/en/notice"` → 원 URL `TARGET_NOT_FOUND`
  거부 확인.
- `python scripts/register.py --config configs/host_tappytoon-com_en_3c39ed9e.json` → PASS, baseline 10건,
  `body_empty_at_baseline=false`.
- `python scripts/demo_config.py configs/host_tappytoon-com_en_3c39ed9e.json --page-size 5 --articles 1` → PASS,
  list 5건, 첫 글 body 5512 chars.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS, 1074 PASS / 0 FAIL.
- 영향 범위: 새 엔진/프롬프트/recognizer 변경 없음. 단일 config 1건과 case 문서만 추가.
