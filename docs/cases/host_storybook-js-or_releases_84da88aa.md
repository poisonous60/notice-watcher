---
slug: host_storybook-js-or_releases_84da88aa
url: https://storybook.js.org/releases/
status: "✅ 손작성 config (작동중, baseline 10, GitHub Releases Atom feed)"
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, board_shape, redirect_to_release_detail]
config_strategy: httpx_html
tags: [storybook, github-releases, rss-feed, atom, manual-config]
---

## 트리거

사용자 제공 큐: `host_storybook-js-or_releases_84da88aa`, URL `https://storybook.js.org/releases/`.
원 실패는 rc=1 `gen_fail` 계열의 selector 실패로 전달됐다. 로컬에는 원본 `.FAILED.json`과 probe artifact가 없어 새로
`register.py "https://storybook.js.org/releases/"` 를 실행해 재현했다.

새 재현 결과는 config 생성까지 가지 않고 board-shape 거부:

```text
Verdict: 정적 HTTP로 충분
글 목록 후보: HTML 4건, JSON API 0건, hydration 0건. 첫 글: (none)
[register] 게시판 형식이 아닌 것 같다 ... html_same_host=0 first_article_same_host=False clicked_same_host=False
```

## 원인

`https://storybook.js.org/releases/` 는 현재 목록 페이지가 아니라 Next.js redirect shell 이다.
HTML 안에 `NEXT_REDIRECT;replace;/releases/10.4;307` 이 들어 있고, 실제 최신 상세 페이지는
`https://storybook.js.org/releases/10.4` 로 열린다. 따라서 Storybook 호스트의 `/releases/` 자체에서는 반복 글 링크가
없어 자동 selector 생성이 실패하거나 board-shape 게이트에 걸린다.

반면 릴리스의 원천 데이터는 `storybookjs/storybook` GitHub Releases에 있고,
`https://github.com/storybookjs/storybook/releases.atom` 이 공개 Atom feed로 정상 응답한다.

## 해결

`configs/host_storybook-js-or_releases_84da88aa.json` 을 손작성했다.

- 사용자-facing `_source_url` 은 원래 URL인 `https://storybook.js.org/releases/` 로 유지해 기존 slug와 봇 등록 의미를 보존.
- 실제 polling source는 GitHub Atom feed:
  `https://github.com/storybookjs/storybook/releases.atom`
- `row_selector`: `feed > entry`
- `post_id`: release tag URL의 `/releases/tag/<tag>`
- `title`: Atom `<title>`
- `url`: Atom `<link href>`
- `published_at`: Atom `<updated>` (`%Y-%m-%dT%H:%M:%SZ`)
- `author`: `author > name`
- `article.content`: GitHub release page의 `div.markdown-body[data-test-selector='body-content']` fallback `div.markdown-body`

## robots / polite_sleep

자동 경로의 기본 호출 수칙을 따른다. config에는 `polite_sleep: {min: 3, max: 6}` 을 명시했다.
GitHub release feed 1회와 신규 글 본문 fetch만 수행하므로 호스트당 호출 수가 작고, 차단 우회나 로그인 자동화는 없다.

## 회귀 검증

```text
$ python scripts/register.py --config configs/host_storybook-js-or_releases_84da88aa.json
[register --config] ✅ 등록 완료 — baseline 10건
    v10.5.0-alpha.0  2026-05-14T08:36:16  v10.5.0-alpha.0
    v10.4.0  2026-05-14T08:14:09  v10.4.0
    v10.4.0-beta.0  2026-05-14T06:17:12  v10.4.0-beta.0
```

`output/poll_state/host_storybook-js-or_releases_84da88aa.json` 기준:
- `last_status=registered`
- `n_baseline=10`
- `body_empty_at_baseline=false`
- `.FAILED.json` / `.REJECTED.json` 잔여 마커 없음

## 트랙 B 검토

- 2a recognizer 확장: 보류. GitHub Releases recognizer는 이미 `github.com/<owner>/<repo>/releases` 를 처리한다. 이번 URL은 Storybook의 브랜드 URL을 특정 GitHub repo feed에 매핑하는 one-off라 범용 recognizer로 승급하기 어렵다.
- 2b `--article-url`: 해당 없음. 입력 URL이 목록이 아니라 redirect shell이라 첫 글 URL 교정으로 해결되지 않는다.
- 2c probe 휴리스틱: 보류. probe가 Storybook URL에서 feed 후보를 놓친 것이 아니라, 같은 HTML에 feed 링크가 없다. sitemap 후보를 GitHub repo로 연결하는 일반 규칙은 과추론 위험이 크다.
- 2d probe artifact 수정: 해당 없음.

일반화 안 되는 이유: Storybook 브랜드 URL과 GitHub repo feed의 대응 관계는 사이트별 지식이며, 현재 probe 산출물만으로 안전하게 추론할 수 없다.
