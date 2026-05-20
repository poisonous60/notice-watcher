---
slug: host_ppomppu-co-kr_zboard_66450ede
url: https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu
status: ✅ 손-config (같은 도메인 working config 베낌)
outcome: handcrafted
date: 2026-05-20
fix_layer: none
failure_keys: [posts_nonempty]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [ppomppu, handcrafted, batch-2026-05-20]
---

## 무엇이 일어났나

catalog 2026-05-20 batch — ppomppu 자유게시판 (`?id=ppomppu`) 만 `posts_nonempty: 0건` 4회 fail. 같은 도메인의 phone (`?id=phone`)·computer (`?id=computer`) 보드는 자동 등록 OK.

진단:
- probe digest 정상 (verdict=`정적 HTTP로 충분`, html_repeating_patterns top1 = `tbody > tr.baseList.bbs_new1` cc=29, first_article_url 정상)
- LLM 가 `tbody > tr.baseList.bbs_new1` 가 아닌 `table tbody tr` / `tbody > tr` 같은 generic selector 박아서 fetch 시 0건 (광고/공지 행 등 noise 섞임).
- 같은 도메인 working configs (`configs/host_ppomppu-co-kr_zboard_c5e1b04b.json` = computer, `_dc254579.json` = phone) 가 `#revolution_main_table tr.baseList` 사용 — 안정.

## 무엇을 바꿨나

`configs/host_ppomppu-co-kr_zboard_66450ede.json` — working config 패턴 베낌. board="ppomppu", url_template = `zboard.php?id={board}` (divpage 안 박음 — 자유게시판은 divpage 없이 첫 페이지 정상).

검증:
- `validate_config` OK.
- `make_adapter().fetch_list(page=1)` → 10건 (initial pagination, page_size 적용).
- `register.py --config` → 28건 baseline.

## 트랙 B 검토

- (2a) 인식기 — ppomppu 단일 도메인이지만 *plural-board* (각 게시판이 id 파라미터). 기존 working configs 가 이미 같은 패턴 — 다른 게시판도 같은 패턴 자동 등록 가능 (실제 catalog 의 phone/computer 모두 자동). 자유게시판은 LLM 의 selector 선택 *우연* 으로 실패한 케이스 — 손-config 가 충분, 인식기 박는 가치 ≈ 0.
- (2c) probe 휴리스틱 — 신호 (cc=29 selector) 이미 *probe 가 잘 제시*. LLM 가 generic selector 골라 망친 케이스 — LLM 선택 안정성 문제이지 probe 신호 문제 X.
- 매칭 0 — 단일 사이트 fix.
