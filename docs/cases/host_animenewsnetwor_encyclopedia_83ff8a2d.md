---
slug: host_animenewsnetwor_encyclopedia_83ff8a2d
url: https://www.animenewsnetwork.com/encyclopedia/releases.php
status: ✅ preflight 회복 + config 등록 (작동중, baseline 30, httpx_html)
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [fetch_list, posts_nonempty]
fix_layer: none
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [animenewsnetwork, preview-guide, stale-queue, preflight-b-hit]
---

## 무엇이 일어났나
`[FAIL] fetch_list`: 자동 생성 config 가 `https://www.animenewsnetwork.com/preview-guide/2026/spring/` 를 목록 URL 로 잡았고, 실제 사이트는 그 경로를 404 로 응답했다. 직전 시도에는 `tbody > tr` 로 release table 을 잡아 `posts_nonempty: 0건` 도 발생했다.

probe 자체는 정적 HTTP로 충분하다고 봤고, `list_candidates.json` 에는 진짜 글 후보로 `https://www.animenewsnetwork.com/preview-guide/2026/spring/a-hundred-scenes-of-awajima/.234736` 가 있었다. 실패 이후 들어간 `5665fa8 [fix-layer: C] cloverworks news` 변경을 포함한 현재 코드로 `--reuse-probe` 를 다시 돌리자, LLM 3번째 시도에서 preview guide index 글(`.234640`)을 목록 루트로 쓰는 config 가 생성되어 baseline 30건을 잡았다.

## 무엇을 바꿨나
**단일 config**: `configs/host_animenewsnetwor_encyclopedia_83ff8a2d.json`
- 원 요청 URL 보존: `_source_url=https://www.animenewsnetwork.com/encyclopedia/releases.php`
- 목록: `https://www.animenewsnetwork.com/preview-guide/2026/spring/.234640`
- row: `ul > li.not_recent`
- 글 링크: `a[href*='/preview-guide/']`
- post_id: `/.<id>` 숫자
- 본문: `div.KonaBody` 계열 fallback

## 일반화 검토
이번 변경은 stale queue 회복으로 생성된 단일 config 추가다. 새 recognizer/probe/schema/prompt 코드는 추가하지 않았다.

Track B 후보:
- 2a recognizer: Anime News Network 전용 encyclopedia release URL 이 preview guide index article 로 이어지는 특수 구조라 플랫폼 recognizer 로 일반화하지 않았다.
- 2b article-url 교정: probe 의 첫 글 후보는 실제 글 URL 이었고, `--reuse-probe` 재시도만으로 통과했다.
- 2c probe digest: 실패 이후 이미 적용된 C-layer 변경(`5665fa8`) 포함 현재 코드가 회복시켰다. 이 slug 에서 추가 휴리스틱은 없다.
- 2d probe 오작동: 정적 HTTP 충분, article_entry_ok=True 로 probe 자체 실패는 아니다.

## 회귀 검증
- preflight: b-hit — 실패 이후 `5665fa8` 영향 영역 commit 존재, `register.py --reuse-probe` 성공.
- 누적 cross-check: `fetch_list` 3건, `posts_nonempty` 74건 모두 `track_b_trigger=true`; 이번 slug 는 기존 C-layer 변경으로 회복되어 추가 code fix 없음.
- `python scripts/register.py --reuse-probe "https://www.animenewsnetwork.com/encyclopedia/releases.php"` → PASS, baseline 30건.
- `python scripts/register.py --config configs/host_animenewsnetwor_encyclopedia_83ff8a2d.json` → PASS, baseline 30건.
- `make_adapter` 손 실행: list 5건, 첫 글 `234736`, body 14897 chars.

## 영향 범위
새 config 파일 1개만 추가한다. 공유 recognizer/probe/engine 동작은 바꾸지 않는다.
