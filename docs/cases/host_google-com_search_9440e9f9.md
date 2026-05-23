---
slug: host_google-com_search_9440e9f9
url: https://www.google.com/search?sa=X&sca_esv=d27b705f235d78cd&sxsrf=ANbL-n5nYxvvoLZQf_qvbJovw6dbr9D4Hw:1778909863391&udm=2&fbs=ADc_l-bD_nyrjATWBKup7flJ4rea5XFXsPHwMjGsTekJ1HCohBAQ3Hh19DqzlO7wr7YUgTdO4_C3uXoTo1-SRivc_Swap6of3IufrklCc-R1r_cYZiN4MoktmDvuiC1PeD4nH8f3b94UIye9mkD9gJ2OhVe3exK-hbmw6eC71bKU8Iww7ZBWxXDSN4anKuWYzQn_6P9msObToyspvu095YuigmETY6lXxzyOSC7CqTlAUcF0IYHKDC4&q=%EB%8C%80%EB%82%98%EB%AC%B4&ved=2ahUKEwjMufrTi72UAxWpia8BHQuuKc4QtKgLegQIERAB&biw=1707&bih=791&dpr=1.5
status: 🚫 거부 (board_shape_check anti-bot 구멍 보강 + REJECTED 마커 — 비-게시판 영구 거부)
outcome: rejected_with_policy
date: 2026-05-16
fix_layer: F
failure_keys: [silent_hang, subprocess_pipe_inherit, playwright_close_no_timeout, board_shape_check, antibot_redirect, posts_nonempty]
config_strategy:
adapters_changed:
engine_files_touched: [bot/site_ops.py, probe/fetch_headless.py, scripts/register.py]
tags: [silent-death, subprocess, playwright, anti-bot, /preview, policy-gate, non-board, antibot-redirect, google-search]
requested_by: <owner>
---

## 무엇이 일어났나
사용자가 봇에서 `/preview https://www.google.com/search?q=대나무&...` (검색결과 SERP URL) 호출 → 봇 ack 메시지가 "🔎 사이트 분석 중… — `host_google-com_search_9440e9f9`" 에서 멈춤. 5분+ 무반응. 사용자 입장에서 "silent 죽음 + triage 도 안 들어감" 으로 보임.

N100 진단 (jobs #25):

```
status      = 'running'  (영원)
result_rc   = NULL
result_tail = NULL
ps          = register.py (PID 75450) do_wait → 손자 probe.py (PID 75452) do_epoll_wait
              + playwright driver (PID 75526) Sl
```

`register.py` 가 zombie 되도록 강제로 SIGTERM 던졌더니: register 만 defunct 됐고 **probe.py + playwright driver 가 살아남음**. 봇 worker 의 `for line in proc.stdout` 가 손자 살아있어서 EOF 안 받음 → 영원 block. 손자 SIGKILL 후에야 봇 worker 가 빠져나와 rc=-2 (chromium_lock 의 600s timer) finalize + triage 진입.

dev box 에서 같은 URL probe.py 단독 reproduce + instrumentation:

```
[trace9b] before goto                          ← Phase 9b article-by-click 진입
...
[trace9b] chosen href='#'                       ← google SERP 의 placeholder anchor
[trace9b] after expect_nav+click
[trace9b] after page.url = 'https://www.google.com/sorry/index?continue=...'   ← anti-bot challenge
[trace9b] after page.content (len=6288)
[trace9b] after screenshot
[trace9b] ENTER finally
[trace9b] before context.close (pages=1)        ← 여기서 ∞ wait
                                                  (after context.close 영원히 안 옴)
```

즉 *두 bug 가 도미노로 silent 죽음 패턴* 만든 거였음.

## 왜 문제인가
1. **bot/site_ops.py 의 process tree 분리 부재** — `subprocess.Popen` 이 default `start_new_session=False`. timeout 시 `proc.kill()` 만 부르면 register.py 자체는 SIGKILL 되지만 손자 (probe.py, playwright driver, chrome) 가 그대로 살아남아 register 의 stdout pipe 를 inherit 한 채 유지. 봇 worker 의 `for line in proc.stdout` 는 pipe 의 모든 writer 가 닫혀야 EOF — 손자가 잡고 있으면 영원 block. **timer 가 register 죽여도 봇 worker 는 멈춰있고 job 영원 'running'** — `mark_job_finished` 도달 X → triage 큐도 안 들어감.
2. **probe/fetch_headless.py 의 playwright sync_api `.close()` 무한 block** — `record_har_content="attach"` 모드에서 context.close 시 HAR flush 가 anti-bot challenge 페이지 (google `/sorry/index`) 상태로 끝나지 X. sync_api 의 `.close()` 는 timeout 인자 자체가 없어 node driver 응답까지 영원 wait. Phase 9b 가 SERP 의 placeholder `href="#"` anchor 를 점수 3점 받아 클릭 → JS handler 가 challenge 페이지로 redirect → 그 상태에서 close 가 망가짐.
3. **사용자 시점**: 봇 ack 메시지 영영 안 갱신. 무엇이 잘못된 건지 단서 0. 운영자 (= dev) 도 jobs row 만 보면 "running" 만 보이고 어디 끼었는지 모름.

## 픽스 (fix_layer: F)

### F-1. `bot/site_ops.py` — process group SIGKILL
```python
# Popen 호출에 process group 분리
proc = subprocess.Popen(cmd, ...,
                        env=child_env,
                        start_new_session=True)  # 새 process group leader

def _kill_on_timeout() -> None:
    if proc.poll() is None:
        timed_out.set()
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()  # fallback
```

`os.killpg(pgid, SIGKILL)` 이 register.py + 손자 probe.py + playwright driver + chrome 까지 한 번에 죽임 → register 의 stdout pipe 의 *모든* writer 닫힘 → EOF 도착 → 봇 worker 의 `for line in proc.stdout` 정상 종료 → rc=-2 (또는 받은 rc) → `mark_job_finished` 도달.

### F-2. `probe/fetch_headless.py` — `_bounded_close` helper
```python
def _bounded_close(closeable, *, label, timeout_s=10.0):
    """playwright sync_api .close() 가 anti-bot challenge 페이지 HAR flush 에서
    무한 block 하는 케이스 방어. 별 thread 에 close 던지고 timeout 안 끝나면 포기.
    leak 된 chromium 은 site_ops 의 process-group SIGKILL 이 정리."""
    done = threading.Event()
    def _go():
        try:    closeable.close()
        except: pass
        finally: done.set()
    threading.Thread(target=_go, daemon=True, name=f"bounded_{label}").start()
    if not done.wait(timeout_s):
        log.warning("playwright %s timed out (%.0fs)", label, timeout_s)
```

`fetch_with_capture` (Phase 2/9) + `fetch_article_by_click` (Phase 9b) 의 finally 블록 양쪽 적용. 자연 close 가 10s 안에 끝나면 정상 path (warning 안 찍힘). 영원 block 케이스만 포기. probe.py 가 return → register.py exit → 봇 worker 가 정상 rc 받아 finalize.

두 fix 모두 *방어 깊이* 의미: F-1 만 있어도 600s 후엔 정상 cleanup, F-2 만 있어도 close 가 10s 안에 끝남. 둘 다 있으면 30-60s 안에 사용자엔 "분석 시간 초과 / 자동 등록 실패" 친절 응답 + triage 진입.

## 영향
- **silent 죽음 패턴 자체 제거**: 어떤 사이트가 어떤 단계에서 hang 해도 ≤ 600s 안에 봇 worker 가 빠져나와 사용자/triage 에 결과 도달. 영원 'running' job 발생 0 보장.
- **회귀 risk 낮음**: `_bounded_close` 가 정상 close (대다수 사이트) 에서는 thread overhead 만 추가 (~ms). `start_new_session=True` 는 N100 Linux 에서 standard, dev box Windows 에서도 `CREATE_NEW_PROCESS_GROUP` 으로 매핑돼 import 깨지지 X.
- **이 case 의 google SERP URL 자체** 는 별도 fix 필요 — `/sorry/index` 같은 anti-bot 페이지 진입 시 즉시 거부하거나, `bot/url_gate.py` 에서 SERP path pre-screen. 별 작업으로 남김 (이번 commit 범위 밖).

## 회귀 검증
- 같은 google URL probe.py 재돌림 (dev box) → Phase 10 도달, `exit=0`. 첫 reproduce 의 5분+ hang 재발 X. `_bounded_close` warning 도 안 찍힘 — 이번 run 은 close 가 자연 10s 안에 끝남 (Google 응답 비결정적). 첫 reproduce 의 hang 은 진짜 hang 이었고 helper 가 보호 path.
- `python scripts/probe_smoke.py` (pre-push hook 자동) → `PASS 210 FAIL 0 WARN 0 SKIP 0` — stage 3 (configs validate + make_adapter 28/28) + stage 5 (heuristic 181 케이스) 모두 통과.
- `audit` (code-audit-reviewer subagent) PASS — Windows import 안전성, threading 모델, daemon thread leak 영향, CLAUDE.md §2/§3 (최소 변경 + surgical) 모두 OK.

## 남은 정리
- google SERP URL (`/search`, `/url?`) 같은 명백한 비-게시판 URL 을 `bot/url_gate.py` 또는 `scripts/register.py:_board_shape_check` 에서 즉시 거부 — 이번 fix 는 *증상* 제거, *원인 URL* 자체 차단은 별 작업. 같은 패턴 (네이버 검색, 빙 검색 등) 재발 가능.
- probe.py Phase 9b 의 `_score_click_link` 가 `href="#"` placeholder 에 3점 주는 게 부적절 — 점수 0으로 두면 click skip 됨 → google /sorry/index 같은 challenge 페이지 진입 안 함. 별 작업.
- N100 의 jobs #25 row (status='failed', rc=-2, triage_queue 진입 완료) 는 finalize 후 그대로 남음 — 정상.
- 이 case 가 보여준 진단법 — `/proc/<pid>/wchan` (do_wait / do_epoll_wait) + ps tree leaf 가 silent 죽음 root cause 찾기에 효과적. py-spy 없어도 충분. 비슷한 사일런트 죽음 신고 들어오면 우선 의심.

## 관련 commit
`57032e6` — fix(bot,probe): /preview 무한 hang — process-group kill + bounded playwright close

---

## 후속 (2026-05-16 — board_shape_check anti-bot 구멍 보강 + REJECTED 마커)

silent-hang fix 후 같은 사용자 (다른 Discord id `poi23619`) 가 동일 URL `/preview` 재시도 → 이번엔 pipeline 이 정상 흘러서 30~60s 안에 rc 반환됨 (silent-hang 재발 X — F-1/F-2 효과 확인). 다만 `_board_shape_check` 가 통과 → gemini 3회 retry → `.FAILED.json` + triage 큐 1건. "남은 정리" 항목(line 104) 이 예측한 그 자리.

### 진단

probe artifact (`list_candidates.json`, `article_click.json`) 신호:

- `list_candidates.first_article_url`: null
- `traffic_json_api_candidates` / `hydration_list_candidates` / `inline_js_data_candidates`: 모두 0
- `html_repeating_patterns`: 1건 (`div > br`, `href_pattern_guess=None`, `sample_url=None`)
- `feed_candidates`: 0
- **`article_sample.clicked_resolved_url`: `https://www.google.com/sorry/index?continue=...`** ← Google abuse-detection 챌린지

board 신호 0/7 인데 마지막 항목의 netloc(`www.google.com`) 이 원본 host 와 일치 → 기존 `_board_shape_check` 가 `clicked_same=True` 한 줄로 통과. anti-bot 챌린지로의 리다이렉트는 *negative* 증거(차단됨)인데 *positive* 로 해석된 게 hole.

### 픽스 (fix_layer: F — `scripts/register.py:_board_shape_check` 의 clicked 신호 정밀화)

> fix_layer 선택 근거: SKILL.md §6 의 (C) = `probe/` 휴리스틱 추가/수정(새 데이터 추출), (F) = `scripts/register.py` 플로우 변경. 이번 변경은 probe 가 *이미 추출한* `clicked_resolved_url` 을 register 단의 게이트가 *해석할 때* anti-bot 경로를 negative 로 가중. 새 probe 데이터 추출 없음 → (F) 가 정확.

`scripts/register.py`:
- 모듈 상수 `_ANTIBOT_REDIRECT_PATH_PREFIXES = ("/sorry/", "/captcha", "/recaptcha", "/challenges/", "/challenge/", "/cdn-cgi/challenge")`
- `_is_antibot_redirect(u)` — URL path 가 위 prefix 중 하나로 시작하면 True.
- `_board_shape_check` 내부:
  - `clicked_blocked = _is_antibot_redirect(clicked_url)`
  - `clicked_same = _same_host(clicked_url) and not clicked_blocked` — 같은 호스트라도 챌린지 경로면 board 신호로 안 셈.
  - 실패 메시지 `detail` 에 `clicked_blocked_by_antibot=<URL>` 표시 (운영자 디버깅 가시성).

### 트랙 A — REJECTED 마커 (사용자 향)

비-게시판 + anti-bot 챌린지 URL = 영구 거부 대상. 수동 config 작성 의미 없음. N100 에서 `_save_rejected` 호출 → `output/poll_state/host_google-com_search_9440e9f9.REJECTED.json` 작성, `.FAILED.json` + `triage_queue.jsonl` 항목 함께 제거. 같은 slug 재시도 시 봇 `is_rejected(slug)` 가 먼저 잡혀 "이전에 거부됨" 응답.

### 트랙 B enumerate (2a/2b/2c/2d) — 매칭 1, 미매칭 3

- 2a (인식기 확장) — X. google.com/search 는 게시판 아님, 인식기 박을 가치 없음.
- 2b (--article-url) — X. 진짜 글 페이지 없음 (검색 결과는 외부 호스트로 분기될 뿐).
- **2c (probe 휴리스틱) — O.** `_board_shape_check` 의 anti-bot 경로 제외 픽스가 이 자리. 같은 PR.
- 2d (probe artifact 수정) — X. probe 가 redirect 정확히 캡쳐 (article_click.json.resolved_url). 휴리스틱 해석 문제만.

### 후속 영향

- 비-게시판 + anti-bot 챌린지 URL 일반: 이제 board_shape_check 가 즉시 rc=3 거부 → 워커가 "게시판 형식 아님" 친절 메시지 + triage 큐 안 쌓음. Google 검색, search 엔진 결과, CF 챌린지 사이트 전반 적용.
- 정상 게시판 회귀 risk: 0. `clicked_resolved_url` 이 anti-bot 경로에 *우연* 매칭될 일 사실상 없음 (실제 게시판 path 는 `/board/`, `/article/`, `/post/`, `/notice/`, `/bbs/` 등). 23 configs 모두 `register.py --config` 경로 — 이 함수 안 탐.
- 트리거 사례 단위 검증 (probe artifact 재사용):
  ```
  _is_antibot_redirect("https://www.google.com/sorry/index?...")   == True
  _is_antibot_redirect("https://example.com/board/article/12345") == False
  _board_shape_check(digest, url)                                  == (False, "...clicked_blocked_by_antibot=...")  ← 이전엔 (True, "")
  ```

### probe.py Phase 9b `_score_click_link` 의 `href="#"` 점수 — 별 작업

이번 commit 범위 밖. anti-bot redirect 게이트가 잡으니 silent hang 재발 위험 0 (F-1/F-2 + C 보강). placeholder anchor 점수 0 으로 두면 click 자체 안 함 → 더 깨끗하지만 다른 사이트 회귀 영향 검토 필요 → 별 case.
