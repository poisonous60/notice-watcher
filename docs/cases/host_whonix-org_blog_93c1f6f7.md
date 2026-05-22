---
slug: host_whonix-org_blog_93c1f6f7
url: https://www.whonix.org/blog/
status: ✅ 수동 config (Whonix Discourse News category — forums.whonix.org JSON API)
outcome: handcrafted
date: 2026-05-22
fix_layer: none
failure_keys: [posts_nonempty, article_body_len, discourse_alias_host_mismatch]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: []
tags: [discourse, whonix, category-json, host-alias]
requested_by: batch
---

## 무엇이 일어났나

`https://www.whonix.org/blog/` 는 Whonix News category의 alias다. HTML/probe는 Discourse generator meta와 `tbody.topic-list-body > tr.topic-list-item.category-news` 후보를 잡았지만, 글 클릭과 본문 JSON API는 `forums.whonix.org`로 이동한다.

preflight: b-hit — `a9c5da5` 이후 `register.py --reuse-probe "https://www.whonix.org/blog/"` 재시도. 자동 생성은 여전히 실패했다.

자동 생성 실패의 직접 원인:
- `DiscourseAdapter` probe dispatch가 `base=https://www.whonix.org`로 시도해 0건으로 폴백했다.
- LLM 생성 config는 list/article host를 섞거나 `/c/news/21?page=1`처럼 잘못된 category endpoint를 만들었다.
- 마지막 실패는 `posts_nonempty: 0건`; 이전 실패는 `article_body_len: post_id=15974 0자`.

## 픽스

`configs/host_whonix-org_blog_93c1f6f7.json` 추가.

기존 `DiscourseAdapter`를 그대로 사용하고, 실제 API host와 category를 명시했다.

- `base_url`: `https://forums.whonix.org`
- `category_slug`: `news`
- `category_id`: `21`
- list endpoint: `https://forums.whonix.org/c/news/21.json`
- article endpoint: `https://forums.whonix.org/t/{topic_id}.json`

## 검증

- `python scripts/register.py --config configs/host_whonix-org_blog_93c1f6f7.json`
  - PASS: baseline 30건
  - first posts: `22882`, `22644`, `22517`
- `make_adapter` 손 실행
  - PASS: list 30건
  - first article body lengths: `7185`, `1520`, `7581`

## 트랙 B 검토

- (2a) recognizer: 보류. `/blog/` alias에서 실제 Discourse API host가 `forums.whonix.org`로 바뀌는 Whonix 특이 케이스다. 일반 Discourse recognizer에 host rewrite를 넣으면 같은 도메인 alias가 아닌 사이트를 오인할 수 있다.
- (2b) article-url 재시도: probe가 실제 글 URL과 HAR JSON 후보를 이미 잡았다. 문제는 글 URL 자체가 아니라 list/category API host 선택이다.
- (2c) probe 휴리스틱: `discourse_platform`, `runtime_id_candidates`, `feed_candidates`, `article_candidates` 신호가 이미 충분했다.
- (2d) 산출물: 새 산출물 불필요.

일반화 안 되는 이유: Whonix의 `www` alias와 `forums` API host 분리 및 `/blog/` alias는 이 host에 국한된다. 기존 `DiscourseAdapter` 재사용 수동 config가 최소 변경이다.
