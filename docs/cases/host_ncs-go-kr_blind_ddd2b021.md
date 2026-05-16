---
slug: host_ncs-go-kr_blind_ddd2b021
url: https://www.ncs.go.kr/blind/bl04/RecrtNotifList.do?searchNcsLclasCd=20&searchNcsMclasCd=01&searchNcsSclasCd=&searchNcsSubdCd=&searchStatus=&searchStartDt=&searchEndDt=&searchDstin=&searchType=&searchField=&searchCondition=0&searchKeyword=
status: ✅ 해결 (probe 룰 정정 + 손-config)
outcome: improved
date: 2026-05-16
fix_layer: C
failure_keys: [classify_login_false_positive, baseline_ok_mismatch, posts_nonempty, post_id_unique]
config_strategy: playwright_html
adapters_changed: []
engine_files_touched: [probe/signals.py, probe/diagnose.py]
tags: [login-false-positive, inline-js-marker, baseline-mismatch, ncs, blind-recruitment]
requested_by: poi23619
---

## 무엇이 일어났나
사용자가 봇에서 `/preview <NCS 채용공고 목록 URL>` 호출 → 자동 등록 파이프라인이 거부. `output/triage_queue.jsonl` 항목 + register 마지막 출력:

```
[register] 목록 페이지에 정적으로도 headless 로도 접근 실패 (verdict='BASELINE_BLOCKED').
차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음. 등록 거부.
- GoodbyeDPI 미가동 — 통신사 SNI 차단 영향 여부를 보려면 GoodbyeDPI를 가동한 뒤 재실행.
```

사용자 질의: "브라우저로 로그인 없이 잘 보이는데 차단됐다는 게 뭐냐."

## 진짜 원인 (회선 차단 X — probe 룰 다층 false positive)

dev box + N100 양쪽 `curl -I https://www.ncs.go.kr/...` 모두 200 OK. SNI 검열 / IP 차단 모두 부정. 그러나 dev box 의 `python scripts/probe.py` 는 거부 → probe 의 분류 룰 자체 결함.

### 1) `signals.classify` 의 LOGIN_REQUIRED false positive (`probe/signals.py:96`)

NCS list 페이지 (555 KB) 안 inline `<script>` 에 `fn_layerNcsS_loginCheck()` 함수 정의:
```javascript
alert("로그인이 필요한 서비스입니다. 로그인하여 주십시오.");
```
이 *alert 문자열* 이 `_LOGIN_BODY_MARKERS_STRONG` 의 `"로그인이 필요한 서비스"` 와 매치 → S4 (headless) 응답이 `Classification.LOGIN_REQUIRED` 로 분류 → `entry_matrix` 에 list target OK 0건 → `scripts/register.py:_entry_matrix_has_ok_list` False → 거부.

브라우저로는 그 함수가 *호출 안 됨* (사용자가 회원 전용 기능 버튼 누를 때만). 페이지 자체는 정상 채용공고 목록.

### 2) `baseline_ok` 정의 모순 (`probe/diagnose.py:28`)

```python
baseline_ok = all(c == Classification.OK for c in baseline_classes)  # 잘못
```
B1 (`/`) + B2 (`/robots.txt`) 둘 중 하나만 OK 면 IP 차단 아님이라는 `probe/baseline.py:66 is_baseline_blocked()` 정의와 어긋남. `robots.txt 404` 같은 흔한 케이스 (NCS 도 robots 없음) 에서 verdict 텍스트에 `BASELINE_BLOCKED` 가 잘못 박힘.

NCS 거부의 *직접* 트리거는 (1) 이지만 (2) 도 같은 영역의 진짜 버그. 영향 사이트: `output/probe/*/diagnosis.json` 의 `BASELINE_BLOCKED` verdict 박힌 case 4건 (`cse-skku-edu_cse`, `mabinogimobile-_News`, `nte-perfectworl_kr`, `syosetu-colomo-_root`) 모두 B1=OK + B2=BLOCKED_BOT 패턴 — register 거부엔 영향 X (verdict 텍스트만 잘못).

## 픽스 (fix_layer: C — probe digest 의 분류 신호 룰 정정)

### A. inline `<script>`/`<style>` 제거 후 마커 검사 — `probe/signals.py`
```python
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>",
                              re.DOTALL | re.IGNORECASE)
def _strip_scripts(s: str) -> str:
    return _SCRIPT_STYLE_RE.sub("", s)
```
LOGIN strong/weak 마커, form 매치, GEO 마커, BOT weak 마커 (길이 비교) 모두 `visible_text = _strip_scripts(body_text)` 로. inline JS alert 문자열·i18n 사전 안 marker 가 본문 콘텐츠로 오인되는 false positive 차단. `body_short_lc` 도 visible 기반.

BOT strong 마커는 본래 `body_short_lc[:8000]` 만 보는데 visible 적용 후도 그대로 — Cloudflare 챌린지 페이지의 `<script>` 안에는 보통 challenge keyword 가 없고 외부 `<noscript>` 본문에 있음. `<noscript>` 도 strip 대상이긴 하나 그 안의 `Just a moment` 같은 마커가 사라지는 영향이 있으면 별 case 로 재검토.

### B. `baseline_ok` 정의 통일 — `probe/diagnose.py`
```python
from .baseline import is_baseline_blocked
baseline_ok = not is_baseline_blocked(baseline)
```
B1 또는 B2 중 *하나라도* OK 면 차단 아님 — `baseline.is_baseline_blocked()` 와 동치.

### C. 손-config — `configs/host_ncs-go-kr_blind_ddd2b021.json`
픽스 A/B 후 register 가 entry_matrix 게이트 통과 → gemini 호출까지 감. 그러나 NCS 의 list HTML 이 `<table class="boardtable_list">` 가 두 번 (header table + body table 분리) → LLM 의 `row_selector="table.boardtable_list tbody tr"` 가 sticky/duplicate row 까지 잡아 `post_id_unique` 3회 fail. 또 NCS 가 query param 빈 값들 명시 여부에 따라 정렬이 다른 응답을 줘서 LLM fetch 와 probe artifact 가 미스매치.

손-config 의 핵심:
- `row_selector`: `table.boardtable_list tr:has(ul[id^="ul_"])` — `ul[id^=ul_]` 가진 tr 만 (header table 의 thead row 거름).
- `post_id`: same row 내 `ul[id^="ul_"]` 의 `id` 속성 → `remove_prefix("ul_")`. `onclick="fn_view(...)"` 보다 안정 (header row 에는 ul 없음).
- `url`: 사용자 원본 URL 의 풀 query string 형태로 template. NCS 디폴트 정렬을 강제하기 위해 `url_template` 도 풀 query 그대로.

## 영향
- **LOGIN false positive**: 비슷한 패턴 (inline JS `alert("로그인...")` 또는 i18n string) 가진 *정상 콘텐츠 페이지* 가 미래에 자동 등록 거부될 위험 차단. 진짜 로그인 페이지는 visible body 에 마커가 있어 그대로 분류.
- **baseline_ok**: `robots.txt 404` + 정상 도메인 사이트의 verdict 텍스트가 더 이상 잘못 `BASELINE_BLOCKED` 박지 않음. 4건 영향 case 는 register 거부엔 영향 X (entry_matrix 만 봄) — verdict 표기만 정확해짐. 옛 `diagnosis.json` 재-probe 시점에 새 룰 적용.
- **회귀 risk**: A 의 `<noscript>` 제거가 SPA shell 페이지에서 `<noscript>` 본문의 "JavaScript is required" 같은 마커를 놓치는 가능성. 그러나 그건 BLOCKED 보다는 OK 분류 = 더 관대 — 통과시켰을 때 후속 단계 (headless retry, list_candidates 0건) 에서 잡힘.

## 회귀 검증
- `python scripts/probe_smoke.py` → `PASS 215  FAIL 0  WARN 4  SKIP 0`. WARN 4 = 옛 probe artifact 재생성 권유 (본 변경 무관).
- `python scripts/probe.py "<NCS 목록 URL>" --lite` 재실행:
  - 픽스 전: S4 → `LOGIN_REQUIRED`, 본문 진입 OK=False, verdict=`BASELINE_BLOCKED`, 권장 진입=`통과한 전략 없음`.
  - 픽스 후: S4 → `OK`, S4.article → `OK`, 본문 진입 OK=True, 권장 진입=`Playwright headless + stealth (S4)`. verdict 에 `BASELINE_BLOCKED` 는 여전 — NCS 의 경우 httpx 베이스라인이 SSL handshake fail (별도 트랙 — `probe/headers.py` 의 preset 과 NCS TLS 협상 불일치). register 게이트엔 영향 X.
- `register --config configs/host_ncs-go-kr_blind_ddd2b021.json` → `✅ 등록 완료 — baseline 10건`. 추출된 ID 모두 유니크, URL 모두 다른 `recrtNo`, 본문 ~8 KB.
- 영향 4건 case 의 *기존 등록 상태* 변동 검증: 모두 `--config` 분기로 등록된 손-config 또는 SKKU 류 어댑터 — `_entry_matrix_has_ok_list` 거부 게이트 자체를 거치지 않아 변동 없음.

## 단일 commit 정책
fix_layer F (probe 룰) + 손-config + case .md + INDEX 한 commit. case_runs DB row 의 `files_changed` derive 가 `git diff HEAD~1..HEAD` 만 보므로 분할 시 첫 commit 캡쳐 누락.

## 남은 정리
- N100 의 `output/poll_state/host_ncs-go-kr_blind_ddd2b021.FAILED.json` + `output/triage_queue.jsonl` 의 NCS 항목 → `register.py --config` 가 자동 정리.
- 사용자 (`poi23619`) 에게 등록 완료 통보 — 봇 명령 없음, owner DM 또는 사용자에게 `/watch` 재요청 권유.
- SSL handshake fail (httpx preset 과 NCS TLS) 는 *별 case*. NCS 자동 등록은 S4 (playwright_html) 만 OK 면 충분 — 우선순위 낮음.
- (선택) NCS 가 같은 패턴 게시판 여럿이면 `engine/recognizers/ncs.py` 추가 → `/watch` 만으로 즉시 등록. 현재는 사용자 1건이라 보류.
