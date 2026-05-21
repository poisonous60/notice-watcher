---
slug: host_anime-japan-jp_news_90aa37b1
url: https://www.anime-japan.jp/news/
status: ✅ config 등록 (baseline 30, playwright_html)
outcome: handcrafted
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, matches_probe_first_article]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: []
tags: [gen-fail, stale-queue, reuse-probe, anime-japan, playwright]
---

## 무엇이 일어났나

`AnimeJapan` news 목록은 `https://www.anime-japan.jp/news/` 에서 렌더 후
`#js-news > div.mt-2.bg-white.rounded-lg.border.border-gray-300` 행으로 30건을 노출한다.
기존 자동 생성 시도는 정적/probe 후보의 첫 링크를 `https://www.anime-japan.jp/2025/` 로
잘못 잡고, 생성 config 가 `posts_nonempty: 0건` 으로 실패했다.

### 진단 (§2 강제 인용)

1. last_feedback `[FAIL]`: `posts_nonempty: 0건`
2. diagnosis verdict: `캡처 헤더 주입 시 정적 가능`
3. §매칭: `posts_nonempty` + `matches_probe_first_article` 계열. 정적 후보의 첫 링크가
   실제 news post URL 이 아니라 다른 섹션 URL 로 diverge 했다.
4. 분기: preflight b-hit. 실패 이후 `5665fa8 [fix-layer: C]` 가 probe row multi-anchor
   개선을 추가했고, 같은 artifact 에 `register.py --reuse-probe` 를 재실행하자 생성 3회차에서 PASS.
5. 누적: `cases_index.py query --failure-key posts_nonempty --json` 은 74건,
   `track_b_trigger=true`. 이번 건은 이미 들어온 Track B 개선으로 회복되어 추가 코드 변경 없음.
6. preflight: `b-hit — host_anime-japan-jp_news_90aa37b1 [5665fa8]`

## 무엇을 바꿨나

- `configs/host_anime-japan-jp_news_90aa37b1.json` 추가.
- strategy = `playwright_html`
- 목록 row = `#js-news > div.mt-2.bg-white.rounded-lg.border.border-gray-300`
- 글 URL = `https://www.anime-japan.jp/{board}/#{post_id}`
- 날짜 = `YYYY.M.D` 텍스트를 `iso8601` transform 으로 `+09:00` ISO 변환.

## 검증

- `python scripts/register.py --reuse-probe "https://www.anime-japan.jp/news/"` PASS
  - baseline 30건
  - 최신 샘플: `10318`, `10316`, `10314`
- `python scripts/register.py --config "configs/host_anime-japan-jp_news_90aa37b1.json"` PASS
  - baseline 30건

## outcome = handcrafted

이번 작업 자체는 새 generic 추론 개선이 아니라, 실패 후 이미 들어온 probe 개선을 재사용해
사이트별 config 를 생성한 stale queue 회복이다. 따라서 case outcome 은 `handcrafted`,
`fix_layer` 는 `none` 으로 둔다.

## 트랙 B

추가 Track B 변경 없음. 원인이던 row multi-anchor/first-article divergence 는 실패 이후 커밋
`5665fa8` 에서 이미 개선되었고, 이번 slug 는 그 개선으로 `--reuse-probe` 성공했다.
