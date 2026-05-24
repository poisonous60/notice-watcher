---
slug: host_yongin-go-kr_user_f1eef610
url: https://www.yongin.go.kr/user/bbs/BD_selectBbsList.do?q_bbsCode=1001
status: "✅ 수동 config — Playwright로 용인 시정소식 10건 추출"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys: [posts_nonempty, tls_handshake, playwright_required]
config_strategy: playwright_html
---

Python/httpx는 로컬에서 TLS handshake 실패가 나지만 Chromium은 같은 URL을 정상 렌더한다. 목록은 `table tbody tr`이고 상세 URL은 `q_bbscttSn`으로 식별된다.

- preflight: miss — 로컬 FAILED/probe artifact 없음
- 조치: `playwright_html` config 추가
- 일반화 안 되는 이유: TLS/SNI 호환 문제로 보이며 이번 allow-list에서는 engine/httpx 계층을 고치지 않는다.
- 회귀 검증: `register.py --config`와 `probe_smoke --stage 3 --stage 5` 대상.
