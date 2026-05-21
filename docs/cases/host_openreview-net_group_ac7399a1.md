---
slug: host_openreview-net_group_ac7399a1
url: https://openreview.net/group?id=NeurIPS.cc/2026/Conference
status: 🚫 거부 (API 열림이나 NeurIPS 2026 공개 notes 0건 — 미래 학회/blind review, 시기상조)
outcome: rejected
date: 2026-05-21
fix_layer: none
failure_keys: [schema_invalid_selector, posts_nonempty_via_empty_venue]
config_strategy: httpx_json (미적용 — 콘텐츠 0)
requested_by: batch
tags: [openreview, conference, spa-nextjs, cloudflare-turnstile, empty-board, premature]
---

# openreview.net/group NeurIPS.cc/2026/Conference

## 진단 (codex 위임 acad7 batch 외 — Claude 직접, 8번째 신규)

- **last_feedback**: `config 가 스키마 검증에 실패했다` — LLM 이 `list.row_required_selector: "href*='/forum?id='"` 박음 (`[ ]` 빠진 잘못된 CSS — `[href*='/forum?id=']` 여야 함).
- **probe verdict**: 정적 HTTP 충분이나 글 목록 컨테이너만 있고 첫 글 URL 추출 실패 — Next.js `<Link>` client-routing.
- **실패 케이스 §**: §2b(첫 글 오인) + 스키마 거부(E). 근본은 SPA + 빈 venue.
- **분기**: 2e → reject.

## 핵심 — API 는 열려 있다 (capability_blocked 아님)

웹앱(`openreview.net/group`)은 **Cloudflare Turnstile** + Next.js SPA 라 정적/headless 로 글 URL 못 뽑음. 그러나 OpenReview **public REST API 는 Turnstile 없이 200**:

```
https://api2.openreview.net/notes?content.venueid=NeurIPS.cc/2026/Conference&limit=25  → {"notes":[]}
https://api.openreview.net/notes?invitation=NeurIPS.cc/2026/Conference/-/Submission   → {"notes":[],"count":0}
https://api2.openreview.net/groups?id=NeurIPS.cc/2026/Conference                       → 200 (group meta + submission_id invitation)
```

즉 **API 접근은 가능** — 차단(능력 부족) 문제 아님. 진짜 사유 = **NeurIPS 2026 은 미래 학회라 공개 notes 0건** (submission blind review 중 또는 미오픈). watch 할 콘텐츠가 아직 없다 = 빈 board = 시기상조 등록.

## 결정: reject (premature/empty)

빈 board 는 register.py `posts_nonempty:0` 으로 어차피 거부됨. config 버그/능력한계 아니라 *콘텐츠 부재*. 정상 거부.

## 콘텐츠 생기면 재등록 recipe (httpx_json — 미래)

NeurIPS 2026 accepted/public notes 가 뜨면(논문 공개 ~2026 가을 예상) 아래로 즉시 등록 가능:

```json
{
  "version": 1, "site": "openreview.net", "board": "NeurIPS.cc/2026/Conference",
  "strategy": "httpx_json",
  "list": {
    "url_template": "https://api2.openreview.net/notes?content.venueid=NeurIPS.cc/2026/Conference&sort=cdate:desc&limit=50",
    "list_path": "notes",
    "fields": {
      "post_id": [{"from":"json","path":"id"}],
      "title":   [{"from":"json","path":"content.title.value"}],
      "url":     [{"from":"json","path":"id","transform":[["format","https://openreview.net/forum?id={}"]]}],
      "published_at":[{"from":"json","path":"cdate","transform":[["unixtime_to_iso","Z","ms"]]}]
    }
  },
  "article": {"fetch_kind":"json","body_empty_acceptable": true}
}
```
(field path 는 콘텐츠 뜬 뒤 실제 응답으로 재확인 필요 — venueid/invitation 중 어느 게 채워지는지 포함.)

## track B — 일반화 안 함

- OpenReview API recognizer(track B)는 *콘텐츠 있는* venue 가 큐에 다시 오면 그때 평가. 지금은 단일 빈-venue 1건 → recognizer 박을 근거 부족 (재발 데이터 0).
- 스키마 거부(`href*=` → `[href*=]`)는 LLM 셀렉터 오류 — 이미 schema validate 가 잡아 retry feedback 줌(E layer 동작 정상). 추가 게이트 불요.
