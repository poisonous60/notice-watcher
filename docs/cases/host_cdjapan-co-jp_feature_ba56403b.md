---
slug: host_cdjapan-co-jp_feature_ba56403b
url: https://www.cdjapan.co.jp/feature/
status: ✅ 손 config (작동중, baseline 23, httpx_html)
outcome: handcrafted
date: 2026-05-21
requested_by: batch
failure_keys: [post_id_unique, title_nonempty, post_id_stable_shape]
fix_layer: config
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [cdjapan, feature, archive-list, duplicate-sections]
---

## 무엇이 일어났나

`[FAIL] post_id_unique: 중복 10건`. 자동 생성 config 는 `/feature/`의 `#content ul.list-thumb > li`를 넓게 잡았다. 이 페이지는 상단 `Special Pick Up`과 하단 카테고리별 feature 섹션에 같은 feature 링크가 반복되어, 같은 `post_id`가 여러 번 추출됐다.

실패 뒤 `5665fa8` probe 휴리스틱 변경이 있어 preflight b-hit로 `register.py --reuse-probe`를 재시도했지만, 자동 생성은 여전히 root selector를 넓게 잡아 `post_id_unique`에서 실패했다.

## 해결

단일 config `configs/host_cdjapan-co-jp_feature_ba56403b.json`을 추가했다.

- 목록 URL은 중복 섹션이 있는 `/feature/` 대신 archive 목록인 `/feature/?all=1`을 사용한다.
- 행 선택자는 archive 본문 목록의 `#content > div.row.sdw > ul.list-thumb > li`로 제한한다.
- `post_id`는 `/feature/<slug>`에서 추출한다.
- `title`은 `YYYY-MM-DD HH:MM:SS` 날짜 prefix 뒤의 본문 텍스트를 추출한다.
- 본문은 `#search-result article.article .article-body`를 우선 사용한다.

## 회귀 검증

- `python scripts/register.py --config configs/host_cdjapan-co-jp_feature_ba56403b.json` → baseline 23건.
- `make_adapter` 손 실행: list 10건, 첫 글 `banner_Rare_CD_Restocked_2605`, body 4508 chars.

## 일반화 검토

- 2a platform recognizer: X. CDJapan feature archive 단일 사이트 구조이며 재사용 가능한 플랫폼 패턴으로 보기 어렵다.
- 2b `--article-url`: X. 첫 글 URL은 실제 글이 맞고 본문도 추출된다. 문제는 목록 root selector가 중복 섹션을 포함한 것이다.
- 2c probe heuristic: 보류. probe는 `#content > div.row.sdw`와 `ul.list-thumb > li` 후보를 이미 노출했고, `?all=1` archive URL 선택은 사이트별 의미 해석이다.
- 2d probe bug: X. 정적 HTTP로 충분하다는 판정과 첫 글 probe는 맞았다.
- 2e 수동 config: O. archive 목록 URL과 좁은 selector를 지정하는 것이 가장 작은 해결이다.

일반화 안 되는 이유: root `/feature/`와 `?all=1` archive의 관계는 CDJapan 사이트별 링크 의미다. 공용 probe/engine에 박으면 다른 사이트의 카테고리 허브와 archive 관계를 추측해야 해 과잉 일반화가 된다.

## 자가 점검 (§6)

1. **자리**: config only (단일 수동 config, generic 추론 개선 아님).
2. **이전 케이스**: `post_id_unique`는 누적 trigger지만, 이번 해결은 사이트별 archive URL 선택이다.
3. **누구 깰까**: 새 config 파일만 추가하므로 기존 config 영향 0.
4. **검증**: register baseline 23건 OK, make_adapter list/body 확인.
5. **outcome=handcrafted**: 자동 solver의 미지 유형 처리가 늘어난 것이 아니라 단일 사이트 config를 쓴 것이다.
6. **fixture**: 새 strategy/휴리스틱이 아니므로 별도 fixture 추가 없음.
7. **트랙 B 보류 사유**: 위 일반화 검토 참조.
