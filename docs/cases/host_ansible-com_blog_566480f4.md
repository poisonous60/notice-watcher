---
slug: host_ansible-com_blog_566480f4
url: https://www.ansible.com/blog
status: 🧩 수동 config — Red Hat blog channel teaser rows 로 baseline 가능
outcome: handcrafted
date: 2026-05-22
failure_keys: [posts_nonempty, feed_candidate_unusable, first_article_misidentified]
fix_layer: none
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [ansible, redhat-blog, blog-channel, batch-2026-05-22]
requested_by: batch
---

## 무엇이 일어났나

`https://www.ansible.com/blog` 는 `https://www.redhat.com/en/blog/channel/open-source-communities` 로
리다이렉트되는 Red Hat blog channel 이다. 자동 생성은 `posts_nonempty: 0건` 으로 실패했다.

preflight: b-hit — host_ansible-com_blog_566480f4 [a9c5da5]

`--reuse-probe` 재시도도 동일하게 실패했다. probe 의 `first_article_url` 은 실제 글이 아니라
채널 네비게이션 링크 `https://www.ansible.com/en/blog/channel/artificial-intelligence` 를 잡았다.
자동 생성 config 는 `div.rhdc-search-listing--content ...` 를 row root 로 잡았지만 현재 렌더된 `list.html`
의 실제 글 행은 `div.pf-l-stack.pf-m-gutter > div.pf-l-stack__item` 아래에 있다. live httpx 응답은
`rhdc-search-listing` shell 과 JS bundle 중심이라 BeautifulSoup selector 로는 teaser 행이 0건이다.

`feed_candidates.json` 에 `https://www.ansible.com/rss/blog/channel/open-source-communities` 가 있었지만,
직접 GET 결과 `https://www.redhat.com/en/ansible-collaborative?...` HTML 로 리다이렉트되어 RSS/Atom
소스로 쓸 수 없었다.

## 픽스

`configs/host_ansible-com_blog_566480f4.json` 생성. `strategy=playwright_html`, list URL 은 Red Hat
channel URL, row 는 렌더된 article teaser stack item 을 사용한다. `post_id` 는 teaser anchor 의
`data-doc-id` 안 `node/<id>`, 제목/요약은 `data-title`/`data-description`, 날짜는
`span.rh-article-teaser-date` 를 `%B %d %Y` 로 파싱한다.

본문은 Red Hat article 페이지의 `article` 요소를 사용한다.

## Track B 검토

- **2a recognizer/engine — X.** 이번 요청은 host/path 1 slug fix surface 로 제한되어 있고,
  Red Hat blog channel 전체 recognizer 는 범위 밖이다.
- **2b article-url — X.** 실제 문제는 첫 글 re-probe 보정보다 목록 row root 선택 실패다.
- **2c/2d probe/generate — 보류.** feed candidate 가 usable feed 인지 검증하는 개선 후보는 있지만
  이번 slug 단건 처리에서는 broad probe/register 변경을 하지 않았다.
- **2e 수동 config — O.** 렌더 후 안정적인 teaser row 와 data-* 필드가 있어 config 로 해결된다.

일반화 안 되는 이유: Red Hat 계열 channel page 전체를 플랫폼 config 로 만들 수는 있지만, 이번 작업은
`www.ansible.com/blog` 한 slug 의 수동 config 로 충분하고 broad recognizer 추가는 요청 범위를 넘는다.

## 회귀 검증

- `configs/<slug>.json` 기존 없음, recognizer 매칭 없음.
- `register.py --reuse-probe "https://www.ansible.com/blog"` → FAIL, `posts_nonempty: 0건`.
- `validate_config` → OK.
- `make_adapter(...).fetch_list(page_size=5)` → 5건, first post `852411`.
- 첫 글 `fetch_article()` content_html length 39685.
