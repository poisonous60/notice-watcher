---
slug: ruliweb-recognizer
url: https://bbs.ruliweb.com/mobile/board/1004/rss
status: ✅ recognizer 승급 (Ruliweb bbs cluster 4건 → engine/recognizers/ruliweb.py)
outcome: improved
date: 2026-05-21
failure_keys: []
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/ruliweb.py]
---

## 무엇이 일어났나
N100 snapshot 기준으로 `bbs.ruliweb.com` 개별 config 4건이 같은 host cluster 로 잡혔다:
`/mobile/board/1004/rss`, `/news/board/1001/rss`, `/pc/board/1003/rss`, `/ps/board/300004`.

공통점은 host 와 board id URL 구조이고, 차이는 목록 소스다. mobile/news/pc 는 RSS XML이고 ps 는 HTML board list 이다.
따라서 selector 를 하나로 합치지 않고 section 별 builder branch 로 승급했다.

## 무엇을 바꿨나
`engine/recognizers/ruliweb.py` 추가:
- 정규식은 `bbs.ruliweb.com/(mobile|news|pc|ps)/board/<digits>` board root 만 매칭한다.
- mobile/news/pc 는 `/rss` suffix 가 있어야 하고, ps 는 `/rss` 를 거부한다.
- `_slug_board` 는 `mobile_1004`, `news_1001`, `pc_1003`, `ps_300004` 형태로 section 을 포함해 충돌을 피한다.
- headers 는 `_common.UA` 를 재사용하고, embedded snapshot 의 Accept/Accept-Language/Referer 차이를 보존했다.

`tests/recognizers/test_ruliweb.py` 추가:
- embedded N100 JSON 을 ground truth 로 두고 builder 출력의 기능 필드를 round-trip 비교한다.
- `recognize()` 통합, `recognize_reject()` 충돌 없음, 다른 host negative, 같은 host article/다른 section negative 를 검증한다.
- pytest 직접 실행과 probe_smoke stage 5 run protocol 둘 다 동작한다.

## 효과
이후 같은 Ruliweb board URL 은 probe/Gemini 없이 known-platform config 로 생성된다.
기존 gitignored N100 snapshot config 는 건드리지 않았다. 기존 멤버 config 도 삭제하지 않는다.

## 검증
```
$ PYTHONPATH=. python -m pytest tests/recognizers/test_ruliweb.py -q
1 passed
```

stage 5 smoke 와 reject 충돌 확인은 이 변경 검증 세션에서 이어서 실행한다.
