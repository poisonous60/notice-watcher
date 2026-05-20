---
name: recognizer-extension
description: >-
  notice-watcher 의 자동생성된 개별 config 묶음(같은 사이트/플랫폼, param 만 다름)을
  recognizer(플랫폼 config) 로 승급하는 워크플로우. 사용자가 "recognizer 승급", "플랫폼 config 만들어줘",
  "이 cluster 묶어줘", "/recognizer-extension" 라고 할 때. cluster_report.py / dashboard 가 출력한
  cluster 후보를 단서로 사용자가 손-호출 (자동 X — ADR 0003 분리 철학). agent 가 멤버 config 비교 →
  canonical 템플릿 판단 → recognizer 작성·검증. 이 프로젝트 (`poisonous60/notice-watcher` dev박스 clone) 전용.
---

이미 N개 쌓인 near-identical config 를 recognizer 로 묶어 *이후 같은 platform 등록을 토큰 0* 으로 만든다.
hand-config 트랙B 2a(신규 단일 사이트 보고 사람이 recognizer 판단)와 평행 — 이 SKILL 은 *이미 cluster 가 떴을 때* agent 가 합성.

**왜 agent 가 (순수 기계 diff X)**: config 들이 변형됨 (HTML selector·timeout·LLM noise). hoyolab 처럼 byte-identical 인 건 운 좋은 경우. agent 가 어느 게 canonical 인지·어느 슬롯이 URL 변수인지 *판단* 해야 함. cluster_report 는 단서만 제공.

## 0. 진입 — 트리거

사용자 손-호출만:
- `/recognizer-extension`
- "recognizer 승급", "플랫폼 config 만들어줘", "이 cluster 묶어줘"
- `python scripts/cluster_report.py` 또는 dashboard `/clusters` 의 cluster 보고 사용자 결정

자동 호출 X (ADR 0003 — 코드 확장은 사용자 게이트).

## 1. cluster 확인

```
PYTHONPATH=. python scripts/cluster_report.py
```

출력:
- **[A] SAME-HOST** — 같은 host, path/param 만 다름 (예: hoyolab circles 2/6/8). 가장 깨끗.
- **[B] CROSS-HOST CMS** — host 다르지만 path-template 같음 (그누보드 등).

각 멤버의 strategy / adapter 표시됨. `⚠️ strategy 혼재` 면 같은 platform 아닐 수 있음 — 의심.

대상 cluster 의 멤버 config 경로 확보 (`configs/<slug>.json`).

## 2. 멤버 config 비교 → canonical 템플릿 (agent 판단)

멤버 config 들을 *전부 읽고* leaf 단위 비교:
- **상수 슬롯**: 모든 멤버 동일 → builder 에 그대로 박음.
- **변수 슬롯**: 멤버마다 다른 값 → 그 값이 *URL 어디서 오는지* 찾음 (path segment / query value).
  - 예 hoyolab: `gids=2/6/8`, `board=circles_2_official`, `Referer=.../circles/2/...` 의 `2` ← URL path `/circles/2/`.
- **URL 에서 못 찾는 변수 슬롯** = 자동 추출 불가. 그 멤버를 cluster 에서 빼거나, 사용자에게 보고 후 중단.
- selector/timeout 등 *사소하게* 다른 건 (LLM noise) → 가장 많은/검증된 멤버 값을 canonical 로 채택. case 파일에 어느 멤버 기준인지 기록.

## 3. recognizer 작성

`engine/recognizers/<platform>.py` — 기존 형식 (NAME / 정규식 / `_build(m, url)` / `PATTERNS`).
worked example: `engine/recognizers/hoyolab.py` (gid 1개만 변수인 최소 케이스).

- 정규식: 멤버 URL 들 정렬 → 고정부 literal, 변수부 capture group. 변수 너무 넓게 잡지 말 것 (false-match). official 같은 literal 은 살려서 다른 게시판 안 잡히게.
- builder: 상수 skeleton + capture 를 변수 슬롯에 치환. `_slug_board` 반드시 포함 (slug 안정성).
- `_common.UA` / `qs()` 재사용.

## 4. round-trip 검증 (필수)

`tests/recognizers/test_<platform>.py` — `run()` protocol (probe_smoke stage 5 자동 발견).
worked example: `tests/recognizers/test_hoyolab.py`.

반드시 포함:
- **roundtrip**: 각 멤버 URL → builder → 기존 config 의 *기능 필드* 재현 (메타키 `_recognized_platform`/`_source_url`/`_note`/`_slug_board` 제외하고 동일).
- **recognize() 통합**: `recognize(url)["_recognized_platform"] == NAME`.
- **다른-host negative**: 무관 host URL 은 None.
- **같은-host 다른-종류 negative (필수 — false-match 핵심 가드)**: 같은 platform 의 *다른 종류 페이지* ≥2개를 **능동적으로 찾아** None(또는 다른 platform) 검증.
  recognizer 정규식이 너무 넓으면 같은 host 의 엉뚱한 페이지를 이 platform 으로 잡아 *valid 하지만 의미가 틀린* config 빌드 → fetch 검증도 통과해 silent 오등록 (예: github release recognizer 가 `/issues`·`/wiki`·repo 홈을 release 로 잡음). regex literal(`/releases`·`/official` 등)이 유일한 방어.
  샘플 소스:
    1. `cluster_report` / `compute_clusters` 가 같은 host 인데 *이 cluster 에 안 묶인* 다른 path-template config — 천연 counter-example.
    2. 그 platform 의 알려진 다른 페이지 종류 (github: `/issues` `/wiki` `/pulls` `/tree/...` `/owner/repo`(홈); hoyolab: `/recommend` `/topic/...`).
  각 → `recognize()` 가 이 recognizer 로 *안* 잡는지(None 또는 타 platform) assert. 하나라도 잡히면 정규식 좁혀 재작성.
- 재현 안 되는 멤버 → §2 로 돌아가 cluster 재정의.

## 5. reject 충돌 검사

```
PYTHONPATH=. python -c "from engine.recognizers import recognize_reject; print(recognize_reject('<멤버 url>'))"
```
None 이어야 함 (article-page reject 가 먼저 잡으면 recognizer 무력). 충돌 시 정규식/REJECT 조정.

## 6. 봉합 확인

```
PYTHONPATH=. python scripts/cluster_report.py
```
대상 cluster 가 후보에서 *사라져야* 함 (recognize() 라이브 체크로 자동 억제). 안 사라지면 정규식이 멤버 URL 안 잡는 것.

## 7. 리뷰 → 배포

- `Agent(subagent_type='hand-config-reviewer', model='sonnet')` 호출.
- `docs/cases/<platform>-recognizer.md` 작성 + `python scripts/cases_index.py` + `--backfill-db output/cases.sqlite3` (CLAUDE.md §6).
- pre-push hook (probe_smoke stage 3·5) 통과 → push → N100 pull → `systemctl --user restart notice-bot.service` (engine/ 변경이므로 restart 필요).

## 8. 기존 config 처리

승급 후 **기존 멤버 config 는 손 안 댐** (slug 마이그 X — Rule D 회피). recognizer 는 *이후* 등록부터 적용.
주의: 같은 URL 재등록 시 new platform slug 로 중복 폴링 가능 (register.py 의 canonical-url 중복 가드로 별도 봉합 — 미구현 시 case 파일에 명시).
