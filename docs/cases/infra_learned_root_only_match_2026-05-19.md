---
slug: infra_learned_root_only_match_2026-05-19
url: (infra — url_gate root-only matching)
status: ✅ root-only matching — learned entry path_prefix='' 가 호스트 전체 차단 X, root URL 만 차단
outcome: improved
date: 2026-05-19
fix_layer: F
failure_keys: [learned_blacklist_host_wide_overreach]
config_strategy: none
adapters_changed: []
engine_files_touched: [bot/url_gate.py, tests/probe_heuristics/test_learned_blacklist.py]
tags: [infra, learned-blacklist, root-only-matching, url-gate, host-overreach-fix]
requested_by: poi23619
---

## 무엇이 일어났나

[[infra_root_marketing_homepage_gate_2026-05-19]] 영구 게이트 배포 후 사용자가 `/preview https://edition.cnn.com/world` 시도 → 봇 거부 메시지 "이전 시도에서 거부된 패턴이에요 — 사유: register failed: gemini 생성+검증 3회 실패 ... 참고 URL: https://edition.cnn.com/".

원인 = N100 의 `output/learned_blacklist.json` 에 옛 4 학습 패턴 (CNN/Reuters/NatGeo/Vimeo) 박힘. 모두 `path_prefix=''` (= root URL 학습). `_normalize_groups` 가 빈 string filter (`if s.strip()`) → `path_prefix=[]` → `_check_policy` 의 `host_suffix only` 분기 도달 = **호스트 전체 차단**. `/world`, `/business` 등 모든 path 거부.

## 무엇을 박았나

### `bot/url_gate.py:_learned_to_groups`
learned entry 의 `path_prefix=''` (root URL 학습 — `_extract_url_pattern` 이 path='/' or empty 면 박는 값) → 그룹에 `match_root_only: True` flag 추가.

```python
if host and not pp:
    group_raw["match_root_only"] = True
```

### `bot/url_gate.py:_normalize_groups`
`match_root_only` 옵션 키 보존. `_DEFAULT_BLACKLIST` / `url_blacklist.json` 의 운영자 룰엔 없는 키 — host 전체 차단 의도 (youtube/x.com 등) 영향 X.

### `bot/url_gate.py:_check_policy`
`host_suffix only` 분기 안에서:
```python
if g.get("match_root_only") and path not in ("", "/"):
    continue   # root URL 아니면 학습 패턴 안 적용
```

## 효과

- 옛 4 학습 패턴: `https://edition.cnn.com/` 차단 유지, `/world` `/business` 등 카테고리 통과
- 미래 root URL fail 학습: 호스트 전체 차단 자동 회피 (root 만 차단). 의도 보존 + 사용자 friction 해소
- 운영자 host-wide 룰 (`_DEFAULT_BLACKLIST` 의 youtube/x.com host_suffix only 등) 영향 X — `match_root_only` 키 없음
- learned_blacklist.json 파일 그대로 (migration X). normalize 시점에서만 변환

## 트랙 B 자리 매핑 (§6 1번)
- (F) 새 엔진 코드 — `bot/url_gate.py` 의 normalize + check_policy 로직 확장. learned entry 의 path_prefix='' 의미 *호스트 전체* → *root 만* 변환.
- (C/D/B/A/E) 미해당.

위에서부터 차례 (E > D > C > B > A > F) — E~A 적용 자리 X (실시간 매칭 로직 자리 = F). F.

## 자가 점검 (§6)

1. **자리**: F. url_gate 매칭 로직 자리 외 fit 없음.
2. **이전 케이스**: [[infra_root_marketing_homepage_gate_2026-05-19]] 의 *후속 fix*. 그 영구 게이트 (LLM 호출 0 회로 root 차단) + 본 root-only matching (학습 부작용 회피) = 두 단계 방어.
3. **누구 깰까**: 0. 운영자 host-wide 룰 영향 X (flag 없음). learned entry path_prefix='' 인 경우만 root-only.
4. **검증**: probe_smoke PASS 381 / FAIL 0. fixture 10건 새 추가 (cases #16-#18) — root URL 차단 + 카테고리 통과 + 운영자 룰 영향 X + path-specific learned 공존.
5. **outcome=improved, fix_layer=F**.
6. **fixture**: `tests/probe_heuristics/test_learned_blacklist.py` 의 case #16-#18 (root_only_root_rejected / root_only_category_passes / default_blacklist_host_wide_youtube_root / root_and_path_coexist_* 등 10 신규).
7. **트랙 B**: 매칭 — 위 §자리 F.

## 옛 4 패턴 cleanup 결정

N100 의 옛 learned_blacklist.json 의 4 학습 (CNN/Reuters/NatGeo/Vimeo path_prefix='') *그대로 둠*:
- 새 root-only matching 이 의도 그대로 변환 (root 차단 + 카테고리 통과)
- 사용자 root URL 재시도 시 학습 횟수 ++ + 차단 메시지 표시 (= 의도 유지)
- 카테고리 URL 시도 시 통과 (= 사용자 friction 해소)
- cleanup 별 작업 X — 새 매칭 로직이 즉시 효과

이게 design 의 *real-world 검증* — N100 push 후 사용자 `/preview https://edition.cnn.com/world` 통과 확인.
