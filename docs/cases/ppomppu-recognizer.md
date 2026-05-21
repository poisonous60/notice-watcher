---
slug: ppomppu-recognizer
url: https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu
status: ✅ recognizer 승급 (cluster 3건 → engine/recognizers/ppomppu.py)
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/ppomppu.py]
---

## 무엇이 일어났나

Ppomppu zboard 게시판 config 3건이 같은 host/path(`www.ppomppu.co.kr/zboard/zboard.php`)와
query `id=<board>` 값만 다르게 존재했다.

- `id=ppomppu`
- `id=computer&divpage=133`
- `id=phone`

세 config 모두 `#revolution_main_table tr.baseList` 행과 `a.baseList-title` 제목/URL 구조를 공유한다.
차이는 `divpage`, 일부 header, phone 쪽 published_at/author selector, article content fallback 순서다.

## 무엇을 바꿨나

`engine/recognizers/ppomppu.py` 를 추가했다.

- 정규식은 `ppomppu.co.kr/zboard/zboard.php` 와 query `id` literal 을 요구한다.
- builder 는 `id` 를 `board`, `_slug_board`, `Referer`, list template 에 반영한다.
- `divpage` 가 있으면 list template 과 Referer 에 보존한다.
- 기존 N100 snapshot 3건의 기능 필드는 테스트에서 embedded ground truth 로 재현한다.

기존 config 파일은 건드리지 않았다. recognizer 는 이후 같은 플랫폼 등록부터 적용된다.

## 회귀 검증

실행 대상:

```
PYTHONPATH=. python -m pytest tests/recognizers/test_ppomppu.py -q
PYTHONPATH=. python scripts/probe_smoke.py --stage 5
```

reject fast-path 충돌도 `tests/recognizers/test_ppomppu.py` 에서 3개 멤버 URL 모두 `None` 으로 확인한다.
