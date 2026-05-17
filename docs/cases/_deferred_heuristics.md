# 보류한 휴리스틱 일반화 후보

case 처리 중 떠올랐으나 *지금* 박지 않은 probe/엔진 일반화 후보. 같은 패턴 1건 더 들어오면 임계량 도달 — 그때 휴리스틱화.

파일명 `_` prefix → `cases_index.py` 가 INDEX.md/DB 빌드 skip.

format: `- **<후보명>** — <신호> — 잡힐 case — 보류 사유 — 재검토 트리거 — 최초 commit`

새 후보 add: 한 줄 append. 박을 때 그 줄 삭제 + commit msg "deferred_heuristics 제거: <후보명>".

## 후보

- **`_external_only_check`** — `row_external_host.external_ratio≥0.95 AND total≥1` — github-wiki-see/tistory — `host_poly-pizza` (ratio=1.0/total=1, sponsor link) false-positive 위험 — 같은 패턴 미커버 호스트 1건 더 — commit `6c738e7`
- **`_multi_host_hub_check`** — `external_ratio≥0.95 AND ≥3 unique external hosts` — tistory — 단일 사례 over-engineering, `_external_only_check` 변형이라 그것 채택 시 흡수됨 — 플랫폼 hub root 2건째 (brunch/steemit/medium) — commit `6c738e7`
