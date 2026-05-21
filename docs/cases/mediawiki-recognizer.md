---
slug: mediawiki-recognizer
url: https://en.wikipedia.org/wiki/Special:RecentChanges
status: ✅ recognizer 승급 (MediaWiki RecentChanges cluster 8건 → engine/recognizers/mediawiki.py)
outcome: handcrafted
date: 2026-05-21
failure_keys: [posts_nonempty]
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/mediawiki.py]
---

## 무엇이 일어났나

Wikipedia, Wikimedia Commons, Wiktionary 의 RecentChanges config 8건이 같은 MediaWiki 변경목록 DOM을 공유했다.

- `li.mw-changeslist-line`
- `a.mw-changeslist-title`
- `data-mw-revid`, `data-mw-logid`, `data-mw-ts`

차이는 host 와 localized Special page title 뿐이었다.

## 무엇을 바꿨나

`engine/recognizers/mediawiki.py` 를 추가했다.

- `wikipedia.org`, `wikimedia.org`, `wiktionary.org` 하위의 알려진 RecentChanges title 8종만 인식한다.
- `/wiki/<localized Special:RecentChanges>` 와 `/w/index.php?title=<localized Special:RecentChanges>` 형태를 받는다.
- 일반 article URL, `Special:Watchlist`, 파일 페이지, 무관 host 는 매칭하지 않는다.
- 새 config 의 `board` 와 `_slug_board` 는 `RecentChanges` 로 고정했다.

기존 config 파일은 건드리지 않았다. recognizer 는 이후 같은 MediaWiki RecentChanges 등록부터 적용된다.

## 회귀 검증

실행 대상:

```
PYTHONPATH=. python -m pytest tests/recognizers/test_mediawiki.py -q
PYTHONPATH=. python scripts/probe_smoke.py --stage 5
```

reject fast-path 충돌도 `tests/recognizers/test_mediawiki.py` 에서 8개 멤버 URL 모두 `None` 으로 확인한다.
