---
slug: host_stackoverflow-c_questions_71c08aad
url: https://stackoverflow.com/questions
status: ✅ 자동 등록 경로 추가 (StackExchange /questions → official API)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [fetch_list_403, posts_nonempty, capability_blocked]
config_strategy: httpx_json
adapters_changed: []
engine_files_touched: [engine/recognizers/stackexchange.py]
tags: [stackexchange, stackoverflow, rss-blocked, api, recognizer, batch-2026-05-21-fedi]
---

## 무엇이 일어났나

2026-05-21 fedi batch 에서 StackExchange network 의 `/questions` 목록이 반복 실패했다.

- `https://stackoverflow.com/questions` / `https://superuser.com/questions` /
  `https://unix.stackexchange.com/questions`: HTML 목록 fetch 가 403.
- `https://askubuntu.com/questions` / `https://math.stackexchange.com/questions`: 목록 후보가 0건.
- `https://english.stackexchange.com/questions` / `https://security.stackexchange.com/questions`: anti-bot 차단으로 rc=5.

원인은 `/questions` HTML 이 Cloudflare/anti-bot 앞단에 걸리는 데 반해, 같은 최신 질문 스트림은 별도 공개
feed/API 로 제공되는 구조다.

## 무엇을 바꿨나

`engine/recognizers/stackexchange.py` 를 새로 추가했다.

- 매칭 범위: `stackoverflow.com`, `superuser.com`, `askubuntu.com`, `serverfault.com`,
  `mathoverflow.net`, `*.stackexchange.com` 의 literal `/questions` 경로만.
- 부정 범위: 개별 질문 URL(`/questions/<id>/...`), `/tags` 등 다른 경로, StackExchange network 밖의
  `/questions` 는 매칭하지 않는다.
- config: 기존 닫힌 어휘인 `httpx_json` 으로 StackExchange official API
  `/2.3/questions?order=desc&sort=creation&site=<site>&filter=withbody` 를 사용한다.
- 추출: `post_id=question_id`, `title`, `url=link`, `published_at=creation_date`,
  `summary/body=body`. article fetch 도 같은 API 의 `/questions/{post_id}` 로 본문을 가져온다.

## RSS 편차

초기 목표는 Atom `https://<host>/feeds` 를 `httpx_html` XML 경로로 쓰는 것이었다. 실제 확인 결과:

- `curl -A "Mozilla/5.0" https://stackoverflow.com/feeds` 는 200 + Atom entry 를 반환.
- 같은 URL을 엔진의 `httpx_html` 기반 `httpx` 로 요청하면 403 Cloudflare challenge 를 반환.

이번 HARD-STOP 은 새 strategy/adapter 추가와 `scripts/register.py` 수정이 금지되어 있어, `requests`/curl 기반
전략을 새로 만들지 않았다. 대신 StackExchange 공식 API가 기존 `httpx_json` 전략으로 통과하고 본문까지
제공하므로, 같은 플랫폼 recognizer의 F-layer 봉합으로 처리했다.

## 검증

수동 fetch 검증:

```text
https://stackoverflow.com/questions => posts 3, sample post_id=79944468, body=2580 chars
https://superuser.com/questions => posts 3, sample post_id=1937792, body=2136 chars
https://askubuntu.com/questions => posts 3, sample post_id=1567029, body=572 chars
https://unix.stackexchange.com/questions => posts 3, sample post_id=806090, body=633 chars
https://math.stackexchange.com/questions => posts 3, sample post_id=5137711, body=2703 chars
https://english.stackexchange.com/questions => posts 3, sample post_id=639787, body=1316 chars
https://security.stackexchange.com/questions => posts 3, sample post_id=286976, body=1956 chars
```

부정 매칭:

```text
https://example.com/questions => recognize None
https://stackoverflow.com/questions/79944460/x => recognize None
https://stackoverflow.com/tags => recognize None
```

## outcome = handcrafted

fix_layer F: 새 플랫폼 recognizer. 자동 솔버가 미지 구조를 더 잘 추론하게 한 것이 아니라,
알려진 StackExchange platform 의 게시판 URL을 공식 API config 로 결정적으로 매핑한 것이다.

## 트랙 B 검토

이 변경 자체가 재발 차단이다. StackExchange network 의 `/questions` 실패군을 한 recognizer로 흡수한다.
추가 probe 휴리스틱이나 prompt 변경은 필요하지 않고, 이번 HARD-STOP 허용 목록에도 없다.
