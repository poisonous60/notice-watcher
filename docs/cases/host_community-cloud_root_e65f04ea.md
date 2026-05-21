---
slug: host_community-cloud_root_e65f04ea
url: https://community.cloudflare.com/
status: ✅ 수동 config (Playwright /latest 목록, 본문은 challenge-gated라 제목·URL 알림)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [article_body_len, fetch_list_403, discourse_json_challenge]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [cloudflare, discourse, cloudflare-challenge, playwright-html, list-only]
---

## 무엇이 일어났나

Cloudflare Community 는 Discourse 포럼이고 probe 의 정적 HTML 에도
`<meta name="generator" content="Discourse ...">` 가 잡힌다. 기존 root-form Discourse 휴리스틱
(`detect_discourse_platform`)도 이 신호를 보고 `DiscourseAdapter` dispatch 까지는 성공했다.

하지만 이 사이트는 일반 Discourse 와 다르게 `/latest.json` 과 `/t/{id}.json` 이 현재 dev box 환경에서
Cloudflare challenge 403 을 반환했다. `DiscourseAdapter` 는 목록 0건으로 폴백했고, LLM 재시도는
Playwright 목록 추출까지는 성공했지만 본문을 JSON API 로 읽으려다 `article_body_len` 에서 실패했다.

원 큐의 첫 실패:

```text
[FAIL] article_body_len: post_id=928513 0자 (<100 — content selector 의심)
```

`register.py --reuse-probe "https://community.cloudflare.com/"` 재확인 결과도 회복 실패:

```text
DiscourseAdapter 등록 시도 (base=https://community.cloudflare.com)
알려진 플랫폼으로 인식했지만 글 0건 — 일반 파이프라인으로 폴백
[FAIL] fetch_list: ... 403 Forbidden ... /latest?page=1
```

## 해결 (fix_layer: none)

`configs/host_community-cloud_root_e65f04ea.json` 손작성.

- `strategy: playwright_html`
- 목록 URL: `https://community.cloudflare.com/latest`
- 행 selector: `tr.topic-list-item`
- post_id: `data-topic-id`
- title/url/category/summary/published_at: 렌더된 topic row 에서 추출
- `polite_sleep: 5~7s`
- 본문: 직접 topic URL 과 JSON API 가 Cloudflare challenge 로 막혀 `body_empty_acceptable: true`

이 config 는 새 글 감지는 정상 동작하지만 본문 HTML 은 저장하지 못한다. 등록 state 에
`body_empty_at_baseline=true` 가 박혀 봇 사용자에게 "본문 추출 안 됨" 경고가 표시된다.

## 검증

스키마:

```text
OK
```

손 실행:

```text
list 5
8 'Welcome to Community@Cloudflare' 2026-02-23T08:00:00+00:00 Meta
928641 'How to use read replicas with http for database per user?' 2026-05-21T04:14:04+00:00 D1
928841 'Connection issue with a hosting site' 2026-05-21T03:31:07+00:00 Getting Started
928815 'Cant access account and no contact from Cloudflare' 2026-05-21T02:38:09+00:00 Dashboard
928843 'Godaddy transfers' 2026-05-21T02:01:12+00:00 Registrar
body chars 0
```

등록:

```text
[register --config] ✅ 등록 완료 — baseline 30건
[register --config] ⚠️ 본문 추출 안 됨 (등급/로그인 필요 가능) — 알림은 제목·URL 만 옵니다.
```

회귀 검증:

```text
python scripts/probe_smoke.py --stage 3 --stage 5
[stage 3] configs validate + make_adapter: 103 / 103 OK
[stage 5] heuristic units: 60 파일 · 667 케이스 · 0 FAIL · coverage 30/30
summary PASS
```

## 트랙 B 검토

- (2a) 기존 Discourse recognizer/adapter: 적용됐지만 `/latest.json` 이 403 이라 실패.
- (2b) `--article-url`: 무관. 첫 글 URL 문제가 아니라 직접 topic/API 접근이 challenge-gated.
- (2c) probe 휴리스틱: Discourse generator-meta 검출은 이미 `infra_discourse_root_form_2026-05-21` 에서 박힘.
- (2d) probe 오작동: 아님. probe 는 Discourse 와 Cloudflare challenge 를 모두 드러냈다.
- (2e) 수동 config: 단일 사이트 예외로 채택. 일반화 안 되는 이유: Discourse 공개 JSON API 가 막힌 Cloudflare Community 전용 정책/보호 조합이며, 본문 클릭/직접 접근도 안정적으로 통과하지 않는다.
