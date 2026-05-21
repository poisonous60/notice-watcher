---
slug: host_eurocrypt-iacr-_2026_baea2078
url: https://eurocrypt.iacr.org/2026/
status: "✅ 인식기 추가 — IACR conference important-dates 페이지 자동 등록"
outcome: handcrafted
date: 2026-05-21
requested_by: academic batch
failure_keys: [post_id_stable_shape]
fix_layer: F
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/recognizers/iacr_conf.py]
tags: [iacr, conference, recognizer, important-dates, batch-2026-05-21]
---

## 무엇이 일어났나

academic batch 에서 `crypto.iacr.org/2026/` 는 등록 성공했지만 같은 IACR conference 계열인
`eurocrypt.iacr.org/2026/` 는 `[FAIL] post_id_stable_shape` 로 실패했고,
`asiacrypt.iacr.org/2026/` 는 gate_reject 로 떨어졌다.

이 worktree 에는 프롬프트에서 언급된 `output/` probe/template artifact 가 없어 원본
`diagnosis.json` 은 직접 재확인하지 못했다. 대신 라이브 HTML 로 세 사이트의 공통 DOM 을 확인했다.

## 진단

IACR conference microsite 는 `https://<conf>.iacr.org/<year>/` 형태이고, landing page 의
Important dates 영역이 공통으로 `article.customCard > div.customCardRow.row` 행을 사용한다.
각 행은 `h6.dateTitle` 날짜와 `p` 이벤트 설명으로 구성되고 별도 article 링크는 없다.

자동 생성 config 는 이 날짜/설명 행의 안정 ID 를 잘못 잡아 `post_id_stable_shape` 에 걸린 것으로
판단했다. `docs/config 자동생성 실패 케이스.md` 기준 §2d 필드 매핑 실수다.

## 처리

`engine/recognizers/iacr_conf.py` 를 추가했다. `crypto`, `eurocrypt`, `asiacrypt`, `tcc`,
`pkc`, `fse`, `ches`, `rwc` 의 `<year>/` root URL 만 매칭한다. 같은 host 의 `.php` 세부 페이지와
IACR 본 사이트 경로는 매칭하지 않는다.

발급 config 는 `httpx_html` 이며:
- `site=<conf>.iacr.org`, `board=<year>`, `_slug_board=<year>`
- `list.url_template=https://<conf>.iacr.org/<year>/`
- `row_selector=article.customCard > div.customCardRow.row`
- `post_id=h6.dateTitle` 를 공백 없는 날짜 키로 정규화
- `title=<date> - <event text>`
- `article.content=article.customCard`, `body_empty_acceptable=true`

## 트랙 B

- 2a 인식기: O. 동일 DOM/URL 구조를 conference host 들이 공유하므로 path-match recognizer 가 맞다.
- 2b `--article-url`: X. 목록 행에 별도 article URL 이 없는 important-dates feed 다.
- 2c/2d probe 휴리스틱: X. 새 구조 신호가 필요한 게 아니라 알려진 플랫폼 URL을 canonical config 로
  바로 발급하면 되는 케이스다.
- 2e 수동 config: X. 단일 config 로 제한하면 다음 IACR conference URL에서 같은 실패가 반복된다.

## 검증

- `python tests/probe_heuristics/test_iacr_conf_recognizer.py` -> 8 passed.
- `recognize("https://eurocrypt.iacr.org/2026/")` -> `_recognized_platform="iacr_conf"`.
- `recognize("https://crypto.iacr.org/2026/")` -> `_recognized_platform="iacr_conf"`.
- live `fetch_list`: eurocrypt 22건, crypto 10건, asiacrypt 10건.
- negative: `https://crypto.iacr.org/2026/callforpapers.php`, `https://crypto.iacr.org/`,
  `https://www.iacr.org/meetings/crypto/` 는 미매칭.
