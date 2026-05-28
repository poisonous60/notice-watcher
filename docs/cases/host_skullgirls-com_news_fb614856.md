---
slug: host_skullgirls-com_news_fb614856
url: https://skullgirls.com/news/
status: ✅ registered (re-probe 자동 회복)
outcome: improved
date: 2026-05-28
failure_keys: [probe_grounding_list_row_selector, posts_nonempty]
config_strategy: httpx_html
tags: [batch-2026-05-28-games-indie-news-07, llm-flakiness, re-probe-recovery, wordpress-style]
---

# skullgirls.com/news — LLM auto mode flakiness, dev box `--reuse-probe` 자동 회복

## 신호
- batch `2026-05-28-games-indie-news-07` (id 5850) gen_fail rc=1.
- N100 result_tail: `auto mode: api_loop_once failed; escalating to agentic with failure_packet` → `agentic generate: max_cycles ... FAILED: agent did not produce a passing config`.
- attempt 1 schema fail: `선택자='title, > title'` (invalid CSS).
- 최종 last_feedback: `probe_grounding_list_row_selector 0 nodes` (i=1), `posts_nonempty 0건; probe mismatch` (i=2).

## site 자체는 정상
- live `curl -sI https://skullgirls.com/news/` → 200 OK, 11180 bytes static HTML.
- 6 `<article class="post-excerpt">` 행, WordPress permalink `/YYYY/MM/slug/` (마지막 글 2021).
- probe digest `list_html` 의 `html_repeating_patterns[0]` = `sel=div.content > article.post-excerpt cc=6` 정상.
- soupsieve / lxml 둘 다 selector 매치 6.

## Track B 6-layer audit (all miss)
- **E** miss — schema 정상 (1st attempt invalid selector fail-fast 잡힘).
- **D** miss — retry feedback (`posts_nonempty 0건; probe mismatch`) 명확. 모델 재학습 못 한 게 본질이지 message 보강 자리 X.
- **C** miss — probe digest `html_repeating_patterns` 에 valid selector cc=6 정상 추출.
- **B** miss — WordPress permalink few-shot 풍부.
- **A** miss — system 룰 추가 X (정상 모델이면 1st 시도서 잡는 패턴).
- **F** miss — recognizer 신설 X (단일 site, generic WP).

## 회복 경로 (mechanism = improved, re-probe 회복 함정)
dev box `python scripts/register.py --reuse-probe 'https://skullgirls.com/news/' --no-agentic` → `mode=api_loop` 시도 1 PASS (6건). config 박힘.

→ AUTO 가 *재시도* 시 정상 selector 생성. 손-config 작성 X (refactor v3 §6.5 "re-probe 회복 함정": `--reuse-probe` 가 LLM 으로 자동 회복한 config = `improved` outcome, handcrafted 아님). fix_layer = none — probe/heuristic/prompt 코드 변경 X.

## 일반화 후보 X
batch 100건 중 단일 gen_fail. cross-site 패턴 X. cases_index `probe_grounding_list_row_selector` 4건은 *다른 root-cause* (cross-host redirect 등 기존 fix 처리). `posts_nonempty` 140 = generic high-volume, 본 case 의 specific signal 아님.

LLM auto mode policy (`api_loop_once` → agentic escalate) 가 flaky 1st attempt 후 즉시 escalate 하는 게 잠재 개선 자리지만, 본 case 1건만으로 policy refactor 근거 부족. 다음 batch 들의 단발 flakiness gen_fail 누적 시 D-layer (api_loop_once 의 attempt budget 확대) 또는 register.py auto mode policy 자리로 escalate.
