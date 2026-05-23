---
slug: _bug_validate_year_archive_discourse_4digit
url: https://forum.safe.global/
status: ✅ 개선 — Discourse 4자리 topic id (5000~9000) 가 더 이상 연도 아카이브로 오분류되지 않음
outcome: improved
date: 2026-05-23
fix_layer: D
failure_keys: [post_id_not_year_archive_false_positive, discourse_topic_id_4digit, recognizer_fallback_then_gen_fail]
config_strategy: handwritten
adapters_changed: []
engine_files_touched: [generate/validate.py, tests/validate/test_nav_archive_reject.py]
tags: [bugfix, validate, discourse, year-archive-heuristic, batch-2026-05-21-crypto]
---

## 무엇이 일어났나

`crypto` batch 의 forum.safe.global / forum.celestia.org / forum.thegraph.com (모두 Discourse,
probe 의 `detect_discourse_platform` 가 generator meta 로 정확히 검출) 가 DiscourseAdapter
fast-path 에서 등록 시도됐으나 *validate* 가 hard-fail:

```
known(discourse (probe generator meta)) 인식했지만 목록 검증 실패 — 폴백:
post_id_not_year_archive(post_id 전부 연도뿐 → 연도 아카이브 인덱스(글 아님):
['7022', '6992', '6990', '7003', '6871'] (개별 글 행을 가리키는 row_selector 로 바꿔라))
```

원인: `generate/validate.py:_is_year_archive` 가 모든 `post_id` 가 `\d{4}` 면 True 를 돌려줌.
Discourse 의 topic id 가 4자리 정수(safe.global=6976/7022 등)면 *연도처럼 보여* 잘못 걸림 →
DiscourseAdapter 폴백 → 일반 LLM 파이프라인 → playwright_html row_selector tries 3회 fail →
rc=1 gen_fail.

원래 의도: netbsd 2025/2024/2023, voidlinux 2026 같은 *진짜 연도 아카이브* 만 거부. 4자리 = 연도
는 너무 lax — 실제 연도는 1990..2030 범위 안.

## 무엇을 바꿨나

`_is_year_archive` 를 4자리 + *그럴듯한 연도 범위* (1990 ≤ year ≤ 2030) 로 좁힘. 1989 또는
2031 같은 경계 밖, 그리고 일부 ID 가 범위 밖이면 False.

`tests/validate/test_nav_archive_reject.py` 에 4 회귀 케이스 추가 (`discourse_topic_ids_4digit`,
경계 위/아래, mixed).

## 회귀 검증

- 기존 fixture: netbsd_years(2025/2024/2023), voidlinux_single_year(2026), mixed 등 모두 PASS 유지.
- `python scripts/register.py --reuse-probe https://forum.safe.global/` →
  `[register] ✅ 등록 완료 (알려진 플랫폼: discourse (probe generator meta)) — baseline 30건`.
  → `configs/host_forum-safe-glob_root_c795ebef.json` 자동 생성.
- 영향 사이트: forum.safe.global / forum.celestia.org / forum.thegraph.com (그리고 미래 같은
  topic id 범위의 다른 Discourse 사이트).

## 일반화

연도 범위 1990..2030 은 진짜 운영 사이트에서 의미 있는 연도 폭. 2030 이후 update 필요할 수 있음
(2030 → ... → 2040 으로 한 줄). 더 엄격한 변형(연도 sequential descending 만 인정 등) 은
*복잡도 대비 이득* 작아 미채택 — 단순 범위 체크가 충분.

트랙 B 매칭 0건 — 휴리스틱(C/D layer) 1줄 수정으로 봉합. 트랙 A 별도 수동 config 불요
(generic 추론 개선 = improved 효과 자동 회수).
