---
slug: host_kyotoanimation-_information_8114f41d
url: https://www.kyotoanimation.co.jp/information/
status: ✅ 수동 config 등록 (httpx_html, baseline 10건) — 날짜+href post_id, list-only 알림
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [article_body_len, post_id_unique, post_id_stable_shape]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [kyoto-animation, hand-config, static-html, external-links, list-only]
---

## 무엇이 일어났나

`/information/` 의 최신 정보 목록은 정적 HTML 로 충분히 노출된다. 자동 생성 config 도
`#mainContentInfo > article.infoDataTop, #mainContentInfo > article.infoData` 행 자체는 맞췄다.

실패 원인은 필드 선택이었다.

- `article_body_len`: 첫 행 URL 이 `https://denkimokuroku.jp/` 같은 외부 작품 사이트라 본문 selector 로 통합 추출할 수 없었다.
- `post_id_unique`: href 단독 키를 쓰면 같은 외부 작품 사이트 URL 이 여러 공지에서 반복되어 중복된다.
- `post_id_stable_shape`: 재시도 중 제목을 포함한 조합 키가 만들어져 공백/문장부호 때문에 stable shape 검증을 통과하지 못했다.

## 무엇을 바꿨나

단일 사이트 수동 config 를 추가했다.

- 목록 URL: `https://www.kyotoanimation.co.jp/information/`
- 행 selector: `#mainContentInfo > article.infoDataTop, #mainContentInfo > article.infoData`
- `post_id`: `time[datetime]` 에서 `+` 를 제거한 값 + sanitized href
- `title`: `a.info`
- `url`: `a.info[href]` 를 원본 기준으로 `urljoin`
- `published_at`: `time[datetime]`
- `cover_image`: 썸네일 이미지
- `article`: `skip_status: [200]`, `body_empty_acceptable: true`

이 보드는 공지 row 가 외부 작품 사이트를 직접 가리키는 aggregator 성격이 강하다. 알림 품질은 목록의
제목/URL/시간만으로 충분하고, 본문을 임의로 외부 사이트별로 통합 추출하면 다시 깨질 가능성이 높다.

## 회귀 검증

- 스키마 OK.
- `make_adapter` 손 실행: list 10건, 첫 글 body 0 chars.
- `python scripts/register.py --config "configs/host_kyotoanimation-_information_8114f41d.json"` PASS
  - baseline 10건
  - `body_empty_at_baseline=true`
  - `.FAILED.json` 및 `triage_queue.jsonl` 항목 정리 확인

## 트랙 B 검토

- 2a 인식기: X — Kyoto Animation 단일 호스트의 고유 HTML 구조다. 플랫폼 recognizer 로 넓힐 반복 신호가 없다.
- 2b first_article_url 교정: X — probe 의 첫 글은 실제 목록 row였고, 문제는 글 샘플 오인이 아니라 외부/반복 href의 키 선택이다.
- 2c/2d probe/schema/prompt: 보류 — 누적 failure key 자체는 trigger 상태지만, 이번 건은 이미 register retry feedback 이 `body_empty_acceptable` 및 list-only 방향을 제시했다. user 지시상 새 휴리스틱/엔진 확장은 이번 slug 밖으로 넓히지 않는다.
- 2e 수동 config: 적용 — 기존 `httpx_html` 어휘와 list-only 설정으로 충분하다.

일반화 안 되는 이유: 외부 링크 aggregator + 날짜/href 조합 키는 사이트별 DOM과 운영 방식에 의존한다. 같은 CMS/플랫폼 반복 신호가 확인되기 전에는 단일 config가 가장 작다.
