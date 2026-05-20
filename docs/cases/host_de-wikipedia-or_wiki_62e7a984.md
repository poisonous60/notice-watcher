---
slug: host_de-wikipedia-or_wiki_62e7a984
url: https://de.wikipedia.org/wiki/Spezial:Letzte_%C3%84nderungen
status: ✅ 인식기 거부필터 완화 (de/fr/es Wikipedia RecentChanges 통과 → 일반 파이프 등록)
outcome: improved
date: 2026-05-20
fix_layer: F
failure_keys: [recognize_reject, article_page_reject_false_positive]
config_strategy: none
engine_files_touched: [engine/recognizers/article_page_reject.py]
tags: [recognizer, wikipedia, recognize_reject, i18n, batch-2026-05-20-b]
requested_by: catalog 2026-05-20-b
---

## 무엇이 일어났나

batch 2026-05-20-b 에 비-영어 Wikipedia RecentChanges 5건. zh (`Special:最近更改`) ·
commons (`wikimedia.org/Special:RecentChanges`) 는 등록 성공, **de/fr/es 는 거부**:

> [PHASE] recognize_reject (article_page_reject)
> ❌ 등록 거부 — 위키피디아 단일 article — 게시판 아님. 보드는 `/wiki/Special:RecentChanges` 등.

## 진단

`engine/recognizers/article_page_reject.py` 의 Wikipedia 패턴은 `/wiki/<title>` 를 단일
article 로 거부하되 negative look-ahead 로 보드/메타 namespace 를 통과시킨다. look-ahead 에
`Special:`·ko `특수:`·ja `特別:` 는 있었지만 **유럽어 localized Special namespace 가 누락**:

- de `Spezial:Letzte_Änderungen`
- fr `Spécial:Modifications_récentes` (URL-encoded `Sp%C3%A9cial:`)
- es `Especial:CambiosRecientes`

→ namespace 가 안 걸려 `[^/?#]+` 가 title 로 매칭 → 단일 article 로 false-reject.
zh 가 통과한 건 영어 `Special:` prefix 를 썼기 때문, commons 는 host (`wikimedia.org`) 가
`*.wikipedia.org` regex 에 안 맞아 애초에 미매칭.

## 트랙 B (영구) — 같은 패턴 자동 처리

negative look-ahead 에 `Spezial:|Spécial:|Sp%C3%A9cial:|Especial:|Speciale:|Speciaal:|
Specjalna:` 추가 (de/fr/es + it/nl/pt/pl 이웃 언어). 임의 lang Wikipedia RecentChanges 가
자동으로 일반 파이프라인으로 흘러 등록됨.

fixture `tests/recognizers/test_article_page_reject.py` 에 5d/5e/5f (de/fr/es Special 통과)
추가. 동시에 `tests/recognizers/` 를 `probe_smoke` stage 5 게이트(EXTRA_UNIT_TEST_DIRS)에 편입 —
이전엔 recognizer fixture 가 pre-push 게이트 밖이었음.

## 트랙 A (즉시)

코드 변경 자체가 트랙 A — de/fr/es RecentChanges 가 배포 후 일반 파이프라인 probe→config 로
등록됨 (zh/commons 와 동일 경로).

## 회귀 검증

`test_article_page_reject.py` 57 cases PASS (gap_check 포함). de/fr/es `recognize_reject → None`
확인. 영어/ko/ja/category/Main_Page 통과 케이스 회귀 없음.
