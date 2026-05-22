---
slug: host_codeberg-org_forgejo_11a2b6a8
url: https://codeberg.org/forgejo/forgejo/releases
status: ✅ 손작성 config (Codeberg release list-only)
outcome: handcrafted
date: 2026-05-22
fix_layer: none
failure_keys: [article_body_len, list_only, body_empty_acceptable]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [codeberg, forgejo, releases, list-only, batch-2026-05-22]
---

## 무엇이 일어났나

`/watch https://codeberg.org/forgejo/forgejo/releases` batch gen_fail. 마지막 실패는:

```text
[FAIL] article_body_len: post_id=4e40eede0352619b8ddb3070ed3005c1eb88bfcb 0자 (<100 — content selector 의심)
```

probe verdict 는 `정적 HTTP로 충분` 이고 `#release-list > li` 행은 정상 후보였다. 문제는 자동 config 가
release tag 링크(`/releases/tag/v15.0.2`) 대신 commit 링크(`/src/commit/<sha>`)를 `post_id`와 article URL로
골랐다는 점이다. 그 결과 article fetch 가 release 본문이 아니라 저장소 파일 목록 페이지를 열었고,
`div.page-content.repository.file.list` 계열 selector 는 알림 본문으로 쓸 수 있는 release 설명을 찾지 못했다.

preflight: b-hit 후 재시도했지만 `register.py --reuse-probe` 도 같은 `article_body_len` 으로 실패했다.

## 조치

`configs/host_codeberg-org_forgejo_11a2b6a8.json` 을 release list 기반 config 로 작성했다.

- `row_selector`: `#release-list > li`
- `post_id`: release tag href 의 `/releases/tag/<tag>`
- `url`: release tag href 자체
- `published_at`: row 안의 `relative-time[datetime]`
- `author`: `a.author`
- `category`: release label
- `summary`: row 안의 `div.markup.desc`
- `article.content: []`, `body_empty_acceptable: true`

직접 확인 결과 `https://codeberg.org/forgejo/forgejo/releases/tag/v15.0.2` 는 plain httpx 에
`Cookie monster!` JS challenge shell 을 반환한다. 차단 우회를 하지 않고 목록 row 에 이미 들어있는
release summary 를 쓰는 list-only 등록으로 고정했다.

## 검증

- config schema validation PASS.
- make_adapter 직접 스모크 PASS: 목록 10건, 첫 글 `v15.0.2`, URL `.../releases/tag/v15.0.2`, summary 93자.
- `register.py --config` 는 output/poll_state 및 triage marker 정리를 유발할 수 있어 이 Codex handoff 범위에서는 실행하지 않았다.
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS.

## 트랙 B 검토

- 2a recognizer: 보류. Codeberg/Gitea release 페이지는 플랫폼 recognizer 후보지만, 이번 요청은 단일
  `host:codeberg.org` slug 처리이고 기존 slug 파일명을 보존해야 한다. `_slug_board`가 들어간 recognizer로
  승급하면 같은 URL slug schema migration 검토가 필요하므로 이번 수정면에서 제외했다.
- 2b `--article-url`: 적용 X. 첫 글 URL 교정 문제가 아니라 release tag detail URL이 httpx 에 JS challenge shell 을 반환한다.
- 2c probe 휴리스틱: 적용 X. probe 산출물은 release list row와 feed 후보를 이미 보여줬다. 새 구조 신호를 추가할 자리가 아니다.
- 2d probe 수정: 적용 X. row 후보 추출 자체는 정상이다.

일반화 안 되는 이유: Gitea/Forgejo release recognizer로 넓힐 수는 있지만, 이번 case 하나만으로 host 범위와 slug schema를
확정하기엔 과하다. 같은 패턴이 추가로 누적되면 Codeberg/Gitea releases recognizer로 별도 승급한다.
