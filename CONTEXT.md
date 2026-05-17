# notice-watcher

공지사항 자동 알림 봇. 사용자가 URL 던지면 시스템이 사이트 구조 인식 (probe → recognizer → schema) 후 주기 폴링·Discord 알림. 자동 인식 실패 사이트는 사람-루프 (hand-config pipeline) 로 들어가 손-개입·자가개선 후 재배포.

## Language

**hand-config pipeline**:
자동 등록 실패 사이트 (FAILED 큐) 가 들어왔을 때 진단 → probe 휴리스틱·prompt·schema·recognizer 개선 → cases 기록 → dev box push → N100 pull → 봇 재시작 까지 한 사이클.
_Avoid_: probe 개선 루프 (probe 만이 아님), hand-config 워크플로 (실행 단위 강조 부족), 자가개선 사이클 (너무 추상), 자가개선 인프라 (인프라 자체와 혼동)

## Flagged ambiguities

- "probe 개선 루프" / "hand-config 워크플로" / "자가개선 사이클" 셋이 같은 개념 가리킴 — 결정: **hand-config pipeline** 으로 통일 (2026-05-17).
