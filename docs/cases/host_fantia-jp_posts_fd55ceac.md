---
slug: host_fantia-jp_posts_fd55ceac
url: https://fantia.jp/posts
status: "🚫 거부 (Fantia posts는 로그인 페이지로 리다이렉트 — 자동 등록 미지원)"
outcome: rejected
date: 2026-05-22
fix_layer: none
failure_keys: [probe_timeout, login_required, policy_reject]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [fantia, login-required, policy-reject, rejected, batch]
requested_by: batch
---

## 진단

- preflight: b-hit — 실패 뒤 영향 영역 commit `27ed350`, `5665fa8`가 있으나, 현재 probe 산출물은 timeout 중 남은 HTML뿐이고 digest(`summary.txt`, `diagnosis.json`, `list_candidates.json`)가 없다.
- original failure: `register probe timeout: probe timeout (120s)` / `[FAIL] probe_timeout: probe timeout (120s)`.
- URL 상태: `curl -L https://fantia.jp/posts` 최종 URL이 `https://fantia.jp/sessions/signin`이고 redirect 1회 뒤 HTTP 200이다.
- artifact 신호: `s1.H3.html` title/og/canonical 이 모두 `ログイン｜ファンティア[Fantia]` / `/sessions/signin` 이며, 본문에 `検索機能および、ランキングの表示はログインが必要です` 알림과 password login form, reCAPTCHA script가 있다.
- 정책 매핑: `probe.signals.classify(... final_url='https://fantia.jp/sessions/signin')` 결과 `LOGIN_REQUIRED`, notable `redirected to login`.

## 결과

config 없음. `/posts`는 공개 게시판 목록이 아니라 로그인 뒤 검색/랭킹 영역으로 리다이렉트된다. `docs/크롤링 지침.md` §6에 따라 `LOGIN_REQUIRED`는 rc=2 `policy_reject` 대상이고, 로그인 자동화는 하지 않는다. captcha/Cloudflare 차단 화면이 아니므로 stealth/render capability 트랙도 아니다.

## 트랙 B 검토

- 2a recognizer: X — 공개 Fantia 게시판 URL 패턴을 인식하지 못한 문제가 아니라 입력 URL 자체가 로그인 요구 영역이다.
- 2b `--article-url`: X — 목록 진입 자체가 login redirect라 첫 글 교정으로 해결되지 않는다.
- 2c/2d probe/schema/prompt: X — 기존 `probe.signals`와 `register.py` 정책 게이트가 이미 `LOGIN_REQUIRED`를 거부하도록 되어 있다. 이번 timeout artifact만 불완전하게 남았을 뿐 새 신호 추출이 필요하지 않다.
- 2e 수동 config/adapter: X — 인증 없는 공개 list source를 확인하지 못했다. storage_state 기반 로그인 세션 config는 사용자가 수동 로그인 상태를 제공하는 별도 범위다.

일반화 안 되는 이유: 로그인 리다이렉트는 이미 정책 거부로 모델링되어 있고, 이번 케이스는 특정 사이트의 공개 접근 정책 문제다.

## 회귀 검증

- `curl.exe -I -sS -L -o NUL -w ... https://fantia.jp/posts` -> `url_effective=https://fantia.jp/sessions/signin`, `http_code=200`, `num_redirects=1`.
- `python - <<classify snippet>>` equivalent via stdin -> `LOGIN_REQUIRED`, `redirected to login`.
- `probe_smoke`는 별도 실행 결과를 작업 로그에 남긴다.
