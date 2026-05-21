---
slug: clien-recognizer
url: https://www.clien.net/service/board/lecture
status: ✅ recognizer 승급 (cluster 4건 → engine/recognizers/clien.py)
outcome: improved
date: 2026-05-21
failure_keys: []
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/clien.py]
---

## 무엇이 일어났나
N100 snapshot 기준 클리앙 게시판 4건이 개별 config 로 쌓였다:
`lecture`, `park`, `news?od=T31&category=0&groupCd=`, `use?od=T31&category=0&groupCd=`.
모두 `www.clien.net/service/board/<board>` 형태이고 `httpx_html` 전략이지만, 게시판별 selector 와
일부 header/list/article skeleton 이 달라 byte-identical cluster 는 아니다.

## 무엇을 바꿨나
recognizer-extension 스킬로 cluster → `engine/recognizers/clien.py` 승급:
- 정규식은 `//(?:www\.)?clien\.net/service/board/(lecture|park|news|use)(?:[/?#]|$)` 로 제한했다. 검증된 4개 게시판만 잡아 같은 host 의 다른 게시판 false-match 를 피한다.
- builder 는 URL path 의 board segment 를 capture 하고, `lecture/park/news/use` 별로 N100 snapshot 의 기능 필드(`headers`, `timeout`, `list`, `article`)를 재현한다.
- `news/use` 는 canonical list URL 에 `?od=T31&category=0&groupCd=` 를 유지한다.
- `_slug_board` 는 board 값(`lecture`, `park`, `news`, `use`)으로 고정했다.

## 효과
이후 같은 4개 클리앙 게시판 등록은 probe/Gemini 없이 결정적 config 로 생성된다.
기존 N100 config 는 손대지 않았다. recognizer 는 이후 등록부터 적용된다.

## 회귀 검증
```
PYTHONPATH=. python -m pytest tests/recognizers/test_clien.py -q
PYTHONPATH=. python scripts/probe_smoke.py --stage 5
```

reject 충돌은 4개 멤버 URL 모두 `None` 이어야 한다.
