---
slug: hoyolab-recognizer
url: https://www.hoyolab.com/circles/2/0/official?lang=ko-kr
status: ✅ recognizer 승급 (cluster 3건 → engine/recognizers/hoyolab.py)
outcome: improved
date: 2026-05-20
failure_keys: []
config_strategy: httpx_json
engine_files_touched: [engine/recognizers/hoyolab.py]
---

## 무엇이 일어났나
batch (configs/candidates) 에서 HoYoLAB 공식 게시판 3건이 개별 LLM 생성됨:
`circles/2/0/official`(Genshin) · `circles/6/0/official`(HSR) · `circles/8/0/official`(ZZZ).
3개 자동생성 config 가 `gids=2/6/8` 숫자 하나 빼고 **byte 동일** (httpx_json, bbs-api-os.hoyolab.com getNewsList).
genshin(2)·hsr(6) 은 batch 에서 LLM 생성 rc=1 실패했고 zzz(8)만 등록 성공 — 같은 구조인데 LLM 비결정성으로 2개 샜다.

`scripts/cluster_report.py` 의 [A] SAME-HOST cluster 로 감지됨 (같은 host, path `/circles/<N>/<N>/official` 만 다름, strategy 동일).

## 무엇을 바꿨나
recognizer-extension 스킬로 cluster → `engine/recognizers/hoyolab.py` 승급:
- 정규식 `//www\.hoyolab\.com/circles/(\d+)/\d+/official\b` — gid(첫 숫자 segment)만 capture. `official` literal 요구 → recommend/기타 게시판 안 잡음.
- builder: gid 를 `board`/`_slug_board`(`circles_{gid}_official`)·`list.url_template`(`gids={gid}`)·`Referer` 에 치환. lang query 는 `qs()` 로 추출(기본 `ko-kr`). 나머지 list/article skeleton 은 상수.
- 검증 `tests/recognizers/test_hoyolab.py` — round-trip: 기존 config 3건의 *기능 필드* 재현(메타키 제외), recognize() 통합, lang 기본값, non-official negative. probe_smoke stage 5 자동 발견.

## 효과
- 이후 HoYoLAB official 게시판(다른 gid 포함) 등록 → probe/Gemini 생략, builder 결정적 생성 = **토큰 0 + 실패 없음**.
- cluster_report 재실행 시 hoyolab 후보 자동 소멸 (live `recognize()` 억제 — 재알림 X).
- 기존 config 3건은 손 안 댐 (slug 마이그 X, Rule D 회피). recognizer 는 이후 등록부터.

## 회귀 검증
```
$ PYTHONPATH=. python tests/recognizers/test_hoyolab.py
  PASS gid2_board / gid6_api_template / roundtrip_reproduces_existing (all reproduced) /
       recognize_integration / lang_default_kokr / non_official_unmatched
  6 passed

$ PYTHONPATH=. python scripts/probe_smoke.py --stage 5
  [stage 5] heuristic units — 0 FAIL · coverage 29/29
  ==== summary ==== PASS 509  FAIL 0  → exit 0   (test_hoyolab 자동 발견 포함)

$ PYTHONPATH=. python -c "from engine.recognizers import recognize_reject; ..."
  reject 충돌: None (circles/2,8 둘 다) — article_page_reject 와 안 겹침

$ PYTHONPATH=. python scripts/cluster_report.py   # 봉합 확인
  recognized 17→20 (hoyolab 3건 흡수) · [A] SAME-HOST cluster 0곳 (hoyolab 후보 소멸)
```

## 비고 — 파이프라인 첫 실증
이 케이스가 "자동생성 개별 config 묶음 → recognizer 승급" 파이프라인(cluster_report 감지 + recognizer-extension 스킬)의 첫 end-to-end 실증.
설계·codex 리뷰: 2026-05-20 dev box session. dashboard `/clusters` 페이지는 cluster 재발 시 추가 (codex simplicity check — 현재는 CLI 리포트로 충분).
