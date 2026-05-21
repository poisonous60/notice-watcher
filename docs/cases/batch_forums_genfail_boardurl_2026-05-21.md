---
slug: batch_forums_genfail_boardurl_2026-05-21
url: https://www.humoruniv.com/
status: ✅ 4 사이트 hand-config (포털/board-root → 실제 board URL) + engine encoding 옵션
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [posts_nonempty, matches_probe_first_article]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: [engine/strategies/httpx_html.py, engine/config_schema.py]
tags: [gen-fail, board-url, portal-homepage, encoding, euc-kr, smf-rss, playwright, batch-2026-05-21-forums]
---

## 무엇이 일어났나

`2026-05-21-forums` 의 gen_fail 4건 — 전부 `[FAIL] posts_nonempty: 0건` +
`matches_probe_first_article`(probe 는 진짜 글 URL 찾았으나 LLM config selector 0행). 공통 원인 =
**입력 URL 이 포털 홈페이지 / 소프트웨어 root** 라 글 목록 행이 없음. 해법 = 실제 board/feed URL.

| slug | 입력(root) | 실제 등록 URL | strategy | baseline |
|---|---|---|---|---|
| eevblog | eevblog.com/forum/ | `index.php?action=.xml;type=rss2;limit=30` (SMF RSS) | httpx_html(XML) | 30 |
| humoruniv | humoruniv.com/ | `web.humoruniv.com/board/humor/list.html?table=pds` | httpx_html(euc-kr) | 20 |
| bobaedream | bobaedream.co.kr/ | `/list?code=best` (베스트 게시판) | httpx_html | 30 |
| etoland | etoland.co.kr/ | `/b/etohumor07` (React SPA) | playwright_html | 30 |

### 진단 (§2 강제 인용)
1. last_feedback `[FAIL]`: `posts_nonempty: 0건` + `[warn] matches_probe_first_article`
2. diagnosis verdict: `정적 HTTP로 충분` (probe 가 root 정적 OK 로 봤으나 board 행 없음 — 포털/위젯/SPA)
3. §매칭: docs/config 자동생성 실패 — 홈페이지 위젯 오인(board URL 필요)
4. 분기: 2e (수동 config) — 자동이 root→board URL 추론 못 함. + F (engine encoding 신규)
5. 누적: humoruniv·bobaedream 메모리에 "홈페이지 위젯" 기록됨
6. preflight: miss (recognize None, board URL 은 수동 발견 필요)

## 무엇을 바꿨나

### configs/ 4개 (위 표)
- eevblog = SMF 전역 RSS (`action=.xml;type=rss2`). humoruniv = euc-kr board. bobaedream = utf-8 best 게시판
  (root /cyber/ 는 자동차 매물 마켓이라 제외, 전 게시판 인기글 best 선택). etoland = React app-router SPA
  (정적 anchor 없음, __NEXT_DATA__/RSS 없음) → playwright_html.

### engine — encoding 옵션 (fix_layer F, 범용)
- `engine/strategies/httpx_html.py`: `_decode(adapter, r)` — `cfg.encoding` 명시 시 `r.content.decode(enc)`,
  미명시 `r.text`. httpx charset 자동검출이 meta-only euc-kr 을 utf-8 로 오판해 mojibake 나는 걸 차단
  (humoruniv 한글 깨짐 → euc-kr 강제). fetch_list·fetch_article 양쪽 적용.
- `engine/config_schema.py`: top-level `encoding` string 허용.
- 테스트: `tests/validate/test_encoding_decode.py` (euc-kr/cp949/미명시 3케이스).

### etoland playwright 안정화 (중요 교훈)
- 초기 `wait_selector: a[href*='/view/']` 가 사이드바/skeleton 의 조기 /view/ 링크에 매칭 → 본 목록
  렌더 전 content() 캡쳐 → 1/3 만 성공. **wait_selector 를 실제 행 링크로 스코프**
  (`li.flex.items-start.gap-1\.5 a[href*='/view/']`) + idle_timeout 14000 → 4/4 안정. Tailwind
  `gap-1.5` 의 `.5` 는 selector compile validate(E-gate, b41d9a9) 가 escape 강제.

## 검증

- 각 config smoke fetch_list ≥10건, register baseline 위 표대로. etoland 4/4 재현 확인.
- `probe_smoke --stage 3 --stage 5` PASS (102 configs validate, stage5 +3 encoding 케이스, 658 cases 0 FAIL).

## outcome = handcrafted

자동이 root→board URL 매핑·encoding·SPA 렌더를 추론 못 한 케이스. 수동 board URL 발견 + config 작성.
engine encoding 옵션은 범용(fix_layer F)이나 전체는 handcrafted(특정 사이트 패치 묶음).

## 트랙 B

- encoding 옵션 = 범용 재사용 (euc-kr/cp949 한국 사이트 재발 대비).
- SMF RSS(eevblog) = recognizer 후보 (simplemachines 도 SMF). cluster 쌓이면 recognizer-extension.
- etoland wait_selector 교훈 = playwright 행-스코프 wait_selector 원칙 (skeleton 오매칭 회피).
