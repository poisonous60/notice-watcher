---
slug: host_fantia-jp_posts_fd55ceac
url: https://fantia.jp/posts
status: "🚫 거부 + probe generic 개선 (hard login redirect는 headless 생략)"
outcome: improved
date: 2026-05-22
fix_layer: C
failure_keys: [probe_timeout, headless_wallclock, login_required, policy_reject]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [fantia, login-required, policy-reject, probe-timeout, rejected, batch]
requested_by: batch
---

## 진단

- preflight: b-hit — 실패 뒤 영향 영역 commit `27ed350`, `5665fa8`가 있으나, 현재 probe 산출물은 timeout 중 남은 HTML뿐이고 digest(`summary.txt`, `diagnosis.json`, `list_candidates.json`)가 없다.
- original failure: `register probe timeout: probe timeout (120s)` / `[FAIL] probe_timeout: probe timeout (120s)`.
- URL 상태: `curl -L https://fantia.jp/posts` 최종 URL이 `https://fantia.jp/sessions/signin`이고 redirect 1회 뒤 HTTP 200이다.
- artifact 신호: `s1.H3.html` title/og/canonical 이 모두 `ログイン｜ファンティア[Fantia]` / `/sessions/signin` 이며, 본문에 `検索機能および、ランキングの表示はログインが必要です` 알림과 password login form, reCAPTCHA script가 있다.
- 정책 매핑: `probe.signals.classify(... final_url='https://fantia.jp/sessions/signin')` 결과 `LOGIN_REQUIRED`, notable `redirected to login`.
- root cause: Phase 1 정적 응답만으로 hard login redirect가 확정되는데도 Phase 2 headless를 먼저 시작하고 무제한 join했다. Fantia 로그인 SPA는 JS/recaptcha/광고 스크립트가 무거워 register subprocess 120s budget을 소모했다.

## 결과

config 없음. `/posts`는 공개 게시판 목록이 아니라 로그인 뒤 검색/랭킹 영역으로 리다이렉트된다. `docs/크롤링 지침.md` §6에 따라 `LOGIN_REQUIRED`는 rc=2 `policy_reject` 대상이고, 로그인 자동화는 하지 않는다. captcha/Cloudflare 차단 화면이 아니므로 stealth/render capability 트랙도 아니다.

probe generic 개선:
- `scripts/probe.py` Phase 1 뒤 hard login redirect가 확정되면 Phase 2 headless를 생략한다.
- headless 호출은 별도 child process + `PROBE_HEADLESS_JOIN_CAP_S`(default 45s)로 감싸 cap 초과 시 `UNKNOWN_ERROR`로 degrade한다. Phase 9 article/headless click도 같은 guard를 탄다.
- hard login redirect에서는 sitemap 후보 회복도 의미가 없으므로 Phase 6 sitemap fetch를 생략해 probe 전체 wall-clock이 policy reject로 빨리 수렴한다.

## 트랙 B 검토

- 2a recognizer: X — 공개 Fantia 게시판 URL 패턴을 인식하지 못한 문제가 아니라 입력 URL 자체가 로그인 요구 영역이다.
- 2b `--article-url`: X — 목록 진입 자체가 login redirect라 첫 글 교정으로 해결되지 않는다.
- 2c/2d probe/schema/prompt: O — `LOGIN_REQUIRED` 정책 게이트 자체는 맞았지만, probe가 그 결론까지 도달하기 전 headless/sitemap 단계에서 wall-clock을 잃었다. hard login short-circuit + headless cap으로 같은 패턴을 timeout 대신 graceful degrade/rc=2로 수렴시킨다.
- 2e 수동 config/adapter: X — 인증 없는 공개 list source를 확인하지 못했다. storage_state 기반 로그인 세션 config는 사용자가 수동 로그인 상태를 제공하는 별도 범위다.

일반화: hard login redirect는 사이트별 문제가 아니라 공개 목록이 아닌 URL에서 반복되는 probe timeout 패턴이다. 정적 단계에서 정책 거부가 충분히 확정되면 headless/render 시도는 정보 이득 없이 budget만 소모한다.

## 회귀 검증

- `curl.exe -I -sS -L -o NUL -w ... https://fantia.jp/posts` -> `url_effective=https://fantia.jp/sessions/signin`, `http_code=200`, `num_redirects=1`.
- `python - <<classify snippet>>` equivalent via stdin -> `LOGIN_REQUIRED`, `redirected to login`.
- before: `python scripts/probe.py "https://fantia.jp/posts" --lite`가 134~154s 외부 timeout. summary가 쓰였어도 Python process가 종료되지 않았다.
- after: `python scripts/probe.py "https://fantia.jp/posts" --lite` -> rc=0, 2.8s, `Verdict: LOGIN_REDIRECT`.
- after: `python scripts/register.py "https://fantia.jp/posts"` -> rc=2, 3.5s, timeout 대신 policy reject.
- `probe_smoke --stage 3 --stage 5`는 별도 실행 결과를 작업 로그에 남긴다.
