---
slug: highwire-recognizer
url: https://www.biorxiv.org/content/early/recent
status: ✅ recognizer 승급 (HighWire Press bioRxiv + medRxiv 2건 → engine/recognizers/highwire.py)
outcome: improved
date: 2026-05-21
failure_keys: []
fix_layer: B
config_strategy: httpx_html
engine_files_touched: [engine/recognizers/highwire.py]
---

## 무엇이 일어났나
N100 snapshot 기준 HighWire Press 기반 preprint 사이트 2건이 개별 config 로 쌓였다:
`https://www.biorxiv.org/content/early/recent`, `https://www.medrxiv.org/content/early/recent`.

두 URL 모두 `/(content)/(early)/(recent)` 폼이고 제목 selector 는
`a.highwire-cite-linked-title span.highwire-cite-title` 로 같지만, snapshot 의 list row/article selector,
date 추출, timezone, polite sleep, bioRxiv 의 `/collection/{board}` list URL 이 서로 달랐다.

## 무엇을 바꿨나
recognizer-extension 스킬로 `engine/recognizers/highwire.py` 를 추가했다:
- 정규식은 `//(?:www\.)?(bio|med)rxiv\.org/content/early/recent/?(?:[?#].*)?$` 로 recent 목록만 잡는다.
- builder 는 host 별 canonical skeleton 을 둔다. bioRxiv 는 snapshot ground truth 에 맞춰
  `board=biochemistry`, `list.url_template=https://www.biorxiv.org/collection/{board}` 를 유지하고,
  `_source_url` 은 실제 입력 URL인 `/content/early/recent` 로 둔다.
- medRxiv 는 `board=all`, `list.url_template=https://www.medrxiv.org/content/early/recent` 를 유지한다.
- `_slug_board=content` 로 기존 fallback URL path 첫 segment 와 같은 board 식별자를 쓴다.

## 검증 모델
dev worktree 에 snapshot config 파일은 없으므로 `tests/recognizers/test_highwire.py` 안에 제공받은
두 JSON 을 ground truth 로 embed 했다. round-trip 검증은 builder 출력에서
`_recognized_platform`, `_source_url`, `_note`, `_slug_board` 만 제외하고 기능 필드 전체를 비교한다.

같은 host false-match 방지로 bioRxiv/medRxiv article URL
`/content/10.1101/...v1` 과 `/content/early` 등을 negative 로 검증했다.

## 효과
이후 bioRxiv/medRxiv `/content/early/recent` 등록은 probe/Gemini 없이 결정적 config 로 생성된다.
기존 N100 config 는 손대지 않았다. recognizer 는 이후 등록부터 적용된다.

## 회귀 검증
```
PYTHONPATH=. python -m pytest tests/recognizers/test_highwire.py -q
PYTHONPATH=. python scripts/probe_smoke.py --stage 5
PYTHONPATH=. python scripts/probe_smoke.py --stage 3 --stage 5
```

reject 충돌은 두 멤버 URL 모두 `None` 이어야 한다.
