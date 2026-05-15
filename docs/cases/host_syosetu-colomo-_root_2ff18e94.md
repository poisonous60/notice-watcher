---
slug: host_syosetu-colomo-_root_2ff18e94
url: https://syosetu.colomo.dev/
status: 🚫 거부 (게시판 형식 아님 — 사전 게이트 추가)
date: 2026-05-15
fix_layer: F
failure_keys: [schema, row_required_selector]
config_strategy:
adapters_changed:
engine_files_touched: [scripts/register.py, bot/worker.py]
tags: [policy-gate, non-board, triage-pollution]
---

## 무엇이 일어났나
사용자가 봇에서 `/preview https://syosetu.colomo.dev/` 호출 → 자동 등록 파이프라인이 probe + gemini 4회 시도 후 실패 → `output/poll_state/host_syosetu-colomo-_root_2ff18e94.FAILED.json` + `output/triage_queue.jsonl` 항목 1건.

페이지 자체가 게시판이 아니라 일종의 랜딩/리다이렉트 페이지였음. `list_candidates.json` 신호:

- `traffic_json_api_candidates`: 0
- `inline_js_data_candidates`: 0
- `hydration_list_candidates`: 0
- `feed_candidates`: 0 (`feed_candidates.json` candidates=[])
- `html_repeating_patterns`: 7건 있지만 모두 `href_pattern_guess=None` 또는 외부 호스트(`syosetu.org`). selector 는 `#output > strong` 같은 일반 텍스트 반복.
- `first_article_url`: `https://syosetu.org/` (외부 호스트)
- `article_click.json` note: "클릭할 만한 글 링크 후보 없음 (best=0)"

gemini 가 억지로 `row_selector="main#output > strong"` 같은 config 를 만들어냈고, validate.py 의 schema 단계가 `row_required_selector: None` 으로 거부 → `[FAIL] schema/list/row_required_selector` 4회 반복 → `.FAILED.json` + triage 큐 진입.

## 왜 문제인가
1. probe 1회 + gemini 4회 호출 = 비용 낭비. URL 만 보고도 게시판인지 아닌지 못 알지만 probe 신호로는 충분히 알 수 있었다.
2. 비-게시판 URL 이 자유롭게 triage 큐에 쌓이면 운영자 noise — hand-config 모드 B 진단에서 "이건 그냥 게시판이 아님" 같은 항목이 계속 끼게 된다.
3. `_policy_check` 는 LOGIN_REQUIRED / BLOCKED 만 잡고, 게시판 형태 여부는 안 본다 — 이번까지 사각지대.

## 픽스 (fix_layer: F — scripts/register.py 등록 플로우에 새 사전 거부 단계)
`scripts/register.py` 에 `_board_shape_check(digest, url)` 추가. probe 끝나고 `_policy_check` 통과 직후, gemini 부르기 전. 같은 호스트로 가는 board 신호(아래 중 하나라도)가 있으면 통과:

- `list_candidates.traffic_json_api_candidates` 비어있지 않음
- `list_candidates.inline_js_data_candidates` 비어있지 않음
- `list_candidates.hydration_list_candidates` 비어있지 않음
- `list_candidates.html_repeating_patterns[]` 중 `href_pattern_guess` 또는 `sample_url` 가 같은 호스트
- `list_candidates.first_article_url` 같은 호스트
- `article_sample.clicked_resolved_url` 같은 호스트
- `feed_candidates` 비어있지 않음 (RSS/Atom)

전부 실패면 rc=3 으로 거부 (`.FAILED.json` 안 쓴다 — `_save_failed` 는 gemini 실패 시에만 호출). `bot/worker.py` 가 rc=3 일 땐 `append_triage_queue` 를 건너뛰고 사용자에게 "게시판 형식 아님" 친절 메시지로 ack 갱신.

## 영향
- 비-게시판 URL: probe(~10s) 후 즉시 거부. gemini 4회 절약 + triage 큐 비-게시판 오염 막힘.
- 정상 게시판: 신호 7가지 중 하나는 거의 항상 잡힘 (probe 가 first_article_url 또는 html_repeating_patterns 를 못 채우는 게시판은 사실상 없음). 회귀 risk 낮음.
- False positive 가능성: 글 0건짜리 신생 게시판(아직 글 없음 + 행 selector 만 있음) — 현재 휴리스틱은 `html_repeating_patterns` 의 href 가 *같은 호스트로 가는 게* 있어야 통과. 글 0건이면 그런 패턴도 없을 가능성 → 차단될 수 있음. 그 경우 사용자에게 글 생긴 후 재시도 안내.

## 회귀 검증
- `python scripts/probe_smoke.py` → `PASS 191 FAIL 0 WARN 3` (WARN 은 옛 diagnosis.json 재생성 권유로 본 변경과 무관). stage 3 의 25/25 configs validate + make_adapter OK 유지.
- 영향 configs 손-실행: 0건. `_board_shape_check` 는 `scripts/register.py` 의 main flow 안에 새로 끼운 사전 거부 단계 — 이미 등록된 25 configs 의 `register.py --config` 경로는 이 함수 자체를 통과하지 않음(`--config` 분기는 main_inner 의 위쪽에서 바로 `make_adapter` + `_save_state`). probe→gemini 일반 파이프라인을 새로 도는 신규 등록 요청만 영향.
- 트리거 사례 (syosetu.colomo.dev) 의 probe artifact 로 함수 단독 호출 확인: 7개 신호 모두 0/외부 호스트 → `(False, "게시판 형식이 아닌 것 같다 ...")` 반환. main flow 에서 `return 3`.

## 남은 정리
- N100 에 남아있는 `output/poll_state/host_syosetu-colomo-_root_2ff18e94.FAILED.json` + `output/triage_queue.jsonl` 의 syosetu 항목은 새 코드와 무관하게 그대로 남아있음 → 배포 후 손으로 한 번 청소.
