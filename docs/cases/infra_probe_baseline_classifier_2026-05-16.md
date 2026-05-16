---
slug: infra_probe_baseline_classifier_2026-05-16
url: (인프라 case — 특정 사이트 X. 트리거 = triage 큐의 techethics-ieee + standardsuniversity 2건 진단 중 발견)
status: 🏗 인프라 (probe baseline classifier — robots.txt 오분류 + SSL cert 에러 verdict 분리)
outcome: improved
date: 2026-05-16
fix_layer: C+F
failure_keys: [classifier_short_body_false_positive, baseline_cert_lumped_into_blocked, register_message_misleading]
config_strategy:
adapters_changed:
engine_files_touched: [probe/signals.py, probe/baseline.py, probe/diagnose.py, scripts/register.py, tests/probe_heuristics/test_signals_classify.py, tests/probe_heuristics/test_diagnose_cert_verdict.py]
tags: [self-improvement, probe-classifier, baseline, ssl-cert, dns, robots-txt-size, verdict-precision]
requested_by: 운영자 (dev box session — triage 진단 중)
---

## 무엇이 일어났나

triage 큐 2건 진단 중 probe artifact 에서 발견된 두 가지 분류 정확성 결함:

1. **techethics.ieee.org/about/** — B2 (robots.txt) 가 HTTP 200 + 193 bytes 정상 응답인데 `signals.classify()` 가 "suspiciously empty body (<200 bytes) — UA/header filter suspected" 휴리스틱에 걸려 `BLOCKED_BOT` 으로 분류. robots.txt 는 원래 짧다 (수십~수백 바이트가 정상) — 일반 HTML 페이지 휴리스틱이 그대로 적용된 게 원인.
2. **www.standardsuniversity.org** — cert subject `CN=*.ieee.org` (SAN 에 standardsuniversity.org 없음) 으로 httpx 가 `CERTIFICATE_VERIFY_FAILED: Hostname mismatch` 던지고 Playwright 는 `ERR_CERT_COMMON_NAME_INVALID`. probe 가 `UNKNOWN_ERROR` 로 묶고 verdict 는 `BASELINE_BLOCKED` 으로 뭉뚱그림 → register 메시지가 "차단(BLOCKED) 사이트로 보임 — 차단 우회는 하지 않음" 이라고 잘못 안내. 실제론 차단이 X — 사이트 운영 오설정 + 원본 URL 이 302 redirect 로 다른 페이지 향함.

## 왜 문제인가

1. **직접 원인 (classifier 측면)**
   - `signals.classify()` 가 target 종류 (HTML 페이지 vs robots.txt) 를 모름 → robots.txt 에 HTML 페이지용 size 임계 적용.
   - `diagnose()` 가 baseline 의 `UNKNOWN_ERROR` 에러 문자열을 들여다보지 X → cert/dns 단계 실패와 IP 차단을 동일 verdict 로 처리.
2. **사용자 영향**
   - 봇 `/watch` 결과 메시지가 부정확. 사용자가 "차단 사이트인가 보다" 오해 → 사실은 URL 죽음 / cert 오설정.
3. **운영자 영향**
   - probe artifact 의 B2 `suspiciously empty body` 노이즈가 매번 떠서 진짜 차단 신호와 섞임 → 진단 시간 낭비.
   - cert 깨진 사이트가 IP 차단 처럼 보여서 "IP 풀고 재시도" 같은 헛수고 가능성.

## 픽스 (fix_layer: C+F — 4 파일 + 2 테스트)

### C-1. `probe/signals.py:classify()` — `is_robots_txt` 파라미터 추가

```python
def classify(..., is_robots_txt: bool = False):
    ...
    # 5) OK
    if status is not None and 200 <= status < 400:
        if is_robots_txt:
            return Classification.OK, notable  # robots.txt 는 짧은 게 정상
        if len(body_text) < 200:
            return Classification.BLOCKED_BOT, ...  # 기존 HTML 휴리스틱 유지
```

기본값 False → 호출처 전부 변경할 필요 X.

### C-2. `probe/baseline.py:_ping()` — B2 일 때 flag 전달

```python
cls, notable = classify(
    ..., is_robots_txt=(target_label == "B2"),
)
```

### C-3. `probe/diagnose.py` — cert/dns 에러 감지 + 새 verdict

새 helper `_is_cert_or_dns_error(err)` — `CERTIFICATE_VERIFY_FAILED`, `Hostname mismatch`, `SSL: `, `ERR_CERT_`, `[Errno -2]` (getaddrinfo), `Name or service not known` 등 마커 매칭.

```python
baseline_cert_broken = bool(baseline_classes) and all(
    c == Classification.UNKNOWN_ERROR for c in baseline_classes
) and any(_is_cert_or_dns_error(r.error) for r in baseline.values())

if baseline_bot_only:
    notes.append("baseline ... Cloudflare ... 사이트 자체 정책")
elif baseline_cert_broken:
    notes.append(f"baseline ping 이 SSL 인증서/DNS 단계에서 실패 — 사이트 운영 오설정 또는 사이트가 사라졌을 가능성. 샘플 에러: {sample}")
elif not baseline_ok:
    notes.append("baseline ping 일부 실패 — IP/도메인 차단 의심")
```

verdict_parts:
```python
if baseline_bot_only:
    verdict_parts.append("CLOUDFLARE_PROTECTED_SITE")
elif baseline_cert_broken:
    verdict_parts.append("CERT_OR_DNS_BROKEN")  # 신규
elif not baseline_ok:
    verdict_parts.append("BASELINE_BLOCKED")
```

### F-1. `scripts/register.py:_policy_check()` — verdict 별 메시지 분기

```python
if not _entry_matrix_has_ok_list(digest):
    if "cert_or_dns_broken" in verdict:
        return False, [f"목록 페이지 접근 단계 이전에 SSL 인증서/DNS 가 깨짐 (verdict={...!r}). "
                       "사이트가 사라졌거나 운영 오설정 — 등록 거부."]
    return False, [f"... 차단(BLOCKED) 사이트로 보임 ..."]
```

## 영향

- **회귀 risk**: 0. `is_robots_txt=False` 가 default → 기존 모든 호출처 동작 동일. cert verdict 도 *추가* 분기일 뿐 BASELINE_BLOCKED 의 super-set 아닌 분리 케이스.
- **false positive**: cert/dns 마커 6종 모두 명확한 에러 문자열 — 일반 차단 (`HTTPStatusError: 403`) 은 안 매치.
- **다른 사이트 혜택**:
  - 모든 사이트의 probe artifact 에서 robots.txt `suspiciously empty body` 노이즈 사라짐 → 진단 가독성 ↑
  - 앞으로 cert 깨진 / DNS 사라진 사이트 들어오면 사용자에게 정확한 사유 안내

## 회귀 검증

- `python scripts/probe_smoke.py --stage 3 --stage 5` → **285 PASS / 0 FAIL** (이전 275 → +10 = 새 fixture 4 + 6).
- 새 fixture:
  - `tests/probe_heuristics/test_signals_classify.py` 4 case — robots 짧은 본문 OK / robots 빈 본문 OK / HTML 짧은 본문 여전히 BLOCKED_BOT / default flag 미지정 시 기존 동작 보존.
  - `tests/probe_heuristics/test_diagnose_cert_verdict.py` 6 case — httpx hostname mismatch / Playwright cert common name / DNS getaddrinfo / 403 일반 에러 negative / None negative / 빈문자열 negative.

## 남은 정리

- 두 triage 큐 항목 (techethics-ieee + standardsuniversity) 은 별도 host case 로 분리 기록.
- N100 배포 후 재-probe 하면 verdict 가 `CERT_OR_DNS_BROKEN` 으로 바뀌고 register 메시지가 새 문구로 나오는지 사용자가 확인 가능.
