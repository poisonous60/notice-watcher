# 보류한 휴리스틱 일반화 후보 (deferred heuristics ledger)

case 처리 중 *probe/엔진 일반화 후보* 가 떠올랐으나 한 가지 이유로 *지금* 박지 않은 것들. 같은 패턴 1건 더 들어오면 임계량 도달 — 그때 휴리스틱화.

`docs/cases/INDEX.md` 와 별개 파일. 파일명 `_` prefix — `cases_index.py` 가 INDEX.md 빌드/DB backfill 에서 skip.

## 컨벤션

각 후보 = 한 H2 섹션. 필수 항목:

```
## <후보명>
- **신호**: probe digest / artifact 의 어느 키·임계값
- **잡힐 케이스**: case slug (+ 한 줄 카테고리)
- **보류 사유**: 무엇이 가로막나 (false-positive 위험·단일 사례·임계값 모호 등)
- **재검토 트리거**: 어떤 조건 되면 박을지 (보통 = "같은 패턴 N건 더")
- **트리거 시 픽스 자리**: probe/extract.py + register.py + tests/probe_heuristics/<name>.py 같은 구체 자리
- **최초 보류 commit**: <sha> (해당 case 의 PR)
- **관련 case**: link list
```

새 후보 박을 자리 — case 의 자가 점검 §6.7 에서 "트랙 B 매칭 0" 또는 "보류" 결정한 항목.
없애기 — 트리거 도달해서 휴리스틱화 PR 박을 때 이 섹션 삭제 + 그 PR 의 commit msg 에 "deferred_heuristics ledger 항목 제거: <후보명>" 명시.

---

## `_external_only_check`

- **신호**: `list_candidates.row_external_host.external_ratio >= 0.95 AND total_count >= 1`
- **잡힐 케이스**:
  - `host_github-wiki-see_m_6c370ddf` — wiki 미러 단일 페이지 (external_ratio=1.0/total=1, 외부 참고 PDF)
  - `host_tistory-com_root_c59077fa` — Tistory 메인 multi-host hub (external_ratio=1.0/total=3)
- **보류 사유**: 운영 `host_poly-pizza_root_a38820de` 가 external_ratio=1.0/total=1 (sponsor link) — board 인데 false-positive 차단 위험. 임계값 `total>=3` 으로 올리면 github-wiki-see (total=1) 못 잡지만 PATTERNS_REJECT 가 잡음 → 일반 휴리스틱이 *명백한 case* 만 잡으려면 임계값 결정 모호.
- **재검토 트리거**: 같은 패턴 *미커버* 호스트 1건 더 (`PATTERNS_REJECT` 안 박혀 있고 external_ratio≥0.95 인 single-article/hub 사이트).
- **트리거 시 픽스 자리**:
  - `probe/extract.py` — 기존 `list_row_external_host` 의 결과 그대로 사용 (새 휴리스틱 추가 X)
  - `scripts/register.py` 새 게이트 `_external_only_check(digest, url)` — `_meta_article_diverging_check` 뒤, `_board_shape_check` 앞
  - `tests/probe_heuristics/test_external_only_gate.py` — fixture 신규 (poly-pizza false-positive 차단 케이스 포함)
- **최초 보류 commit**: `6c738e7` ([fix-layer: F] FAILED 큐 5건 일괄 거부)
- **관련 case**: [host_github-wiki-see_m_6c370ddf](host_github-wiki-see_m_6c370ddf.md), [host_tistory-com_root_c59077fa](host_tistory-com_root_c59077fa.md), [infra_article_page_reject_3_2026-05-17](infra_article_page_reject_3_2026-05-17.md)

## `_multi_host_hub_check`

- **신호**: `list_candidates.row_external_host.external_ratio >= 0.95 AND len(set(urlsplit(u).netloc for u in sample_external_urls)) >= 3` (= 3+ 서로 다른 외부 호스트)
- **잡힐 케이스**:
  - `host_tistory-com_root_c59077fa` — Tistory 메인 (3 unique subdomain hosts)
- **보류 사유**: 단일 사례 — 일반화 over-engineering. `_external_only_check` 의 더 좁은 변형 (`unique_host>=3` 추가) — 그게 채택되면 이건 흡수됨.
- **재검토 트리거**: 같은 패턴 *플랫폼 hub root* 2건째 (`brunch.co.kr/`, `steemit.com/trending`, `medium.com/`, `dev.to/` 같은 플랫폼 메인) 들어오면.
- **트리거 시 픽스 자리**: `_external_only_check` 와 같은 자리. `external_ratio>=0.95 AND total>=3 AND unique_host>=3` 으로 더 정확한 multi-host hub 만 잡음.
- **최초 보류 commit**: `6c738e7`
- **관련 case**: [host_tistory-com_root_c59077fa](host_tistory-com_root_c59077fa.md), [infra_article_page_reject_3_2026-05-17](infra_article_page_reject_3_2026-05-17.md)
