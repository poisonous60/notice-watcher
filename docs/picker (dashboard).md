# picker — dashboard 안 click 기반 사이트 등록 UI

자동등록 실패 ~30% gap 의 사용자 친화 대안. URL → row 1-click → 자동 매핑 →
host_*.json + poll_state baseline write. dashboard `/builder` route, dev box only.

ADR: 별도 안 — picker = `httpx_html` config 생성기. 기존 엔진 그대로 사용
(feed_url engine 없음, RSS 안 거침).

## 1. 동기

- notice-watcher 자동등록 70%, 30% gap = hand-config / 사용자 `/report` 처리.
- 사용자 회고 (2026-05-24): "URL 자동 vs UI picker (마우스로 row 짚기) 가
  더 낫지 않았나" → 외부 OSS (pol-ler — PolitePol Django fork) 검토.
- pol-ler 검증 결과: UX OK 이지만 selector 노출 X (RSS URL 만 노출) + stack
  무거움 (Django+Postgres) → 자체 빌드 결정.
- 자체 빌드 = pol-ler 와 같은 클릭 UX, output 은 RSS 가 아닌 *selector* →
  notice-watcher 의 `httpx_html`/`playwright_html` 엔진 그대로.

## 2. 위치 / 파일

| 파일 | 역할 |
|---|---|
| `dashboard/builder_view.py` | SSRF gate + session + HTML sanitize + save+smoke. backend 핵심. |
| `dashboard/app.py` (5 routes 추가 + middleware skip + import) | `/builder/*` 라우트 |
| `dashboard/templates/builder.html` | URL 입력 폼 |
| `dashboard/templates/builder_edit.html` | iframe + side panel 6-field UI + inline JS |
| `dashboard/templates/base.html` (1 줄 추가) | nav 에 "🎯 Builder" 항목, topbar 의 builder 페이지 snapshot dot hide |
| `dashboard/static/builder/picker.js` | iframe-side ES module: click capture + heuristic 매핑 |
| `dashboard/static/builder/finder.min.js` | vendored @medv/finder v4.0.2 MIT (8.5KB) — element → CSS selector |

deps: `fastapi`, `jinja2`, `httpx`, `bs4`, `pydantic` (전부 기존 `requirements*.txt` 안 있음).

## 3. routes

| method | path | 동작 |
|---|---|---|
| GET | `/builder` | URL 입력 페이지 |
| POST | `/builder/start` | URL → sid (in-memory) → 303 redirect `/builder/edit/{sid}` |
| GET | `/builder/edit/{sid}` | iframe + side panel UI |
| GET | `/builder/p/{sid}/{path:path}` | sanitized + script-injected target HTML proxy |
| POST | `/builder/api/save` | SavePayload → host_*.json + poll_state baseline + smoke |

middleware `_preflight_pull` skip_prefix 에 `/builder` 박힘 (snapshot 미사용,
proxy busy path 보호).

## 4. 보안 모델

### SSRF (codex review #3)
`_validate_target_url(url)`:
- scheme allowlist (http/https only)
- URL 길이 ≤ 2048
- DNS resolve → 모든 IP 가 public 일 때만 통과 (any blocked → 전체 reject).
  rebinding 우회 방지 — 이전 "1개라도 public 이면 통과" 는 httpx 재-resolve 시
  blocked IP 로 connect 가능 했음.
- redirect 매 hop 재검증.

### HTML sanitize (codex review #4)
`_sanitize_html(html, base_href, script_url)`:
- 제거 tag: `script`, `iframe`, `object`, `embed`, `applet`, `frame`, `frameset`
- 제거 meta: `http-equiv=refresh`
- 제거 link: stylesheet 외 모두 (preload/prefetch/dns-prefetch 등)
- 제거 attr: `on*=`, `href/src/action/formaction/srcdoc/data/background/ping` 의
  `javascript:` / `data:text/html` / `vbscript:` / `data:application/xhtml` URL
- form: `onsubmit=return false`, `action=javascript:void(0)`
- 박음: `<base href>` (relative URL → target 으로) + 우리 picker.js (absolute URL)

### CSP (response header)
```
default-src 'self' data: blob:;
img-src *           data: blob:;
style-src *         'unsafe-inline' data:;   # target 외부 stylesheet 허용
font-src *          data:;
script-src 'self';                            # target script 다 strip, 우리 것만
frame-src 'none';                             # iframe 다 strip
connect-src 'none';                           # XHR/fetch X
frame-ancestors 'self';
```

### 우리 script URL = absolute
`<base href="target">` 가 `/static/builder/picker.js` 를 target origin 으로
resolve → CSP `'self'` (=our dashboard) 와 mismatch 차단 했음. fix = 라우트가
`request.url.scheme + netloc + root_path + /static/builder/picker.js` 로 full URL
박음.

## 5. UX 흐름

```
1. /builder URL 입력 → 시작
2. /builder/edit/{sid} 에서 "Row 짚기" 클릭
3. iframe 안 공지 row 1개 click (어디든 — _ascendToRow 가 ancestor 자동 ascent)
4. 자동:
   - row_selector = finder(t) → :nth-* strip (일반화)
   - 매칭 row 다 box-shadow inset 녹색 + 옅은 녹색 배경 outline (시각 confirm)
   - _heuristicFields(sample row):
       title/link = row 안 innerText 가장 긴 <a href>
       post_id    = href query string 의 흔한 key (pkid/id/seq/no/nttId/articleNo/
                    bbsSeq/documentSrl/gid/idx/num/code/articleId/article_id/newsId/
                    news_id/view_id/boardSeq/cntntsId/bbsId/pid/aid) regex match,
                    또는 path 마지막 숫자 segment (e.g. /news/view/123456),
                    또는 row 자체 data-* attr (data-id/seq/post-id/no/article-id/nttid)
       date       = \d{4}[-./]\d{1,2}[-./]\d{1,2} 매칭 text 의 parent
5. side panel 에 6 field 자동 매핑 결과 표시. 틀린 field 만 "수정" 버튼 click
   → mode='field:<name>' → iframe element click 1번 → 그 field 만 업데이트
6. 옵션 (include_notices, strategy=httpx_html|playwright_html) 조정
7. "smoke 검증 + 저장":
   - SavePayload Pydantic 검증
   - smoke = ConfigAdapter(cfg) → fetch_list(page_size=10):
       posts ≥ 1, title 1+ nonempty, post_id 1+ nonempty 모두 통과해야 진행
   - host_<slug>.json + output/poll_state/<slug>.json baseline write
     (smoke 통과한 post_id 다 seen 으로 박음 — 첫 polling 시 신규 알림 폭주 방지)
```

## 6. UI 안내

| 상태 | UI |
|---|---|
| 대기 | "Row 짚기" 버튼 누르라 안내 |
| mode 활성 시도 | "⏳ <mode> 활성화..." 1.5s 안 ack 없으면 "⚠ picker.js 응답 없음 — F12 확인" |
| mode 활성 OK | "✓ 활성: <mode>" 녹색 + iframe cursor crosshair |
| nomode click | "⚠ 먼저 우측 Row 짚기 또는 수정 버튼" 주황 |
| row 매칭 | row_selector + 매칭 개수 + ≥2 녹색 / 1 주황 경고 |
| save 결과 | JSON pre 박스에 ok/stage/error/config_path/baseline_path/smoke 표시 |

## 7. 한계

| 케이스 | 동작 | 대안 |
|---|---|---|
| **SPA** (naver 카페, 모던 forum) | iframe 본문 빈 화면 (script strip + JS 무력) | recognizer / hand-config / `playwright_html` strategy — picker 안 거침 |
| **Cloudflare/captcha** | proxy fetch 자체 4xx | hand-config / 능력부족 case |
| **로그인 필요 사이트** | cookie 안 보냄 → 401 | hand-config |
| **post_id 복잡 추출** (concat·계산) | heuristic 못 잡음, 사용자 "수정" 도 transforms 입력란 X | host_*.json 손-편집 또는 hand-config |
| **uvicorn workers>1** | `_SESSIONS` in-memory process-local → /start vs /edit worker mismatch 시 404 | 현재 dashboard.py 가 workers 안 줘 기본 1, 안 깨짐. 운영 시 SQLite/cookie 로 교체 |
| **DNS rebinding race** | 검증 vs fetch 사이 race | 매우 narrow window. IP pin connect 는 over-engineering, 현 fix 충분 |

## 8. 사용자 검증 상태 (2026-05-24 끝)

- ✅ backend smoke (worktree python) — proxy_fetch swu live + sanitize + 한국어 보존
- ✅ Pydantic SavePayload accept/reject (bogus field, len>500) + SSRF localhost 차단
- ❌ swu / dgist UI 검증 미완 — picker.js + UI 통합 손-검증 안 끝남
- ⚠ gamemeca.com 사용자 테스트 시 발견된 bug 3건 모두 fix 함 (outline 안 보임,
  click ascent, post_id key — 4fcd210 + 9218cb7)
- 미시도: bobaedream (EUC-KR 인코딩), arca.live (cloudflare), inven (게시판 pagination)

## 9. 미해결 / TODO

| P | 항목 |
|---|---|
| P1 | 사용자 손-검증 완료: T1 swu → T2 인코딩 → T3 SPA → T4 cloudflare → T5 게시판. PASS/FAIL 사이트별 결과 기록 |
| P2 | smoke 통과 후 dashboard `/triage/failed` 의 "manual picker 등록" 버튼 → `/builder?url=...` 으로 jump (현재 사용자가 URL 직접 입력) |
| P2 | `output/cases.sqlite3` 에 picker save 시 method=`manual_picker` row backfill — `/cases` 페이지에서 보임 |
| P2 | SPA 사전 경고 — proxy fetch 후 text length / link count threshold 검사 → "JS 렌더링 필요 의심" 빨간 배너 |
| P3 | image hotlink 차단 사이트 (naver 등 403) — image proxy 추가 |
| P3 | post_id complex (concat·계산) 의 picker UI override — transforms 입력란 |
| P3 | recognizer 우선 — picker 진입 전 `engine.recognizers.recognize(url)` 매칭 시 "기존 recognizer 가 처리 — picker 불필요" 안내 |

## 10. commit history

| commit | 내용 |
|---|---|
| 332c998 (initial) | feat(dashboard): click-picker builder UI |
| 1d53d99 | fix v3 — codex review 10 bug 일괄 (SSRF rebinding, sanitize iframe/object/svg, picker.js auxclick, generalize class normalize, baseline write, Pydantic, reverse-proxy, snapshot dot, input squeeze, multi-worker comment) |
| 1ade14a | fix — idle navigate 차단 + mode 활성 visual (crosshair, ack, timeout) |
| c026e90 | fix — absolute script URL (`<base href>` 영향 회피) + CSP style-src 외부 허용 |
| beec113 | feat — 1-click row + 자동 field heuristic (8 click → 1~3 click) |
| a538e6c | fix — outline 강제 표시 (box-shadow inset) + _ascendToRow + post_id key 확장 (gid 등) |
| 18543bc + 9218cb7 | fix — matched outline 가 mode 변경 시 사라지던 bug (clearMatchedOutline 제거) |

## 11. codex review history

| review | 형태 | 결과 |
|---|---|---|
| v1 (계획) | pol-ler 검증 계획 review | 5 WARN 2 PASS — XSS/RSS polling/Windows docker/PASS 기준/B-axis automation/사이트 분류 |
| v2 (계획) | 자체 picker design plan review | 3 FAIL 4 WARN — SSRF 1, field mapping 3, iframe capture 6, smoke 8 등 |
| v3 (코드) | 332c998 + 318b2f3 5 파일 review | 0 P0, 4 P1 (SSRF rebinding/sanitize/multi-worker/baseline 폭주/Pydantic), 6 P2 — 10/10 fix 됨 (1d53d99) |

## 12. 알려진 root-cause notes (안 까먹게)

- **CRLF 함정** (Windows clone): pol-ler 초기 빌드 시 `wait-for-it.sh` / `frontend/start.sh`
  CRLF 박힘 → Linux container shebang 깨짐. 우리 picker 코드 도 `.js` / `.html`
  파일 모두 LF/CRLF 경고 띄움 (git autocrlf). 동작 영향 X (브라우저는 둘 다 OK).
- **picker.js loaded console.log**: F12 console 에 `[picker] loaded` 안 보이면
  load 실패 확정 (ES module + finder.js import 어딘가 깨짐).
- **mode 활성 ack timeout 1.5s**: ack 없으면 picker.js load 실패 의심 메시지 표시.
- **single worker 가정**: `_SESSIONS` in-memory. workers>1 운영 시 SQLite 로 교체.

## 13. 다음 세션 진행 순서 (제안)

1. dashboard 띄움 (`DEPLOY_HOST=... python scripts/dashboard.py --reload`)
2. http://127.0.0.1:8765/builder 사용자 검증 T1 swu.ac.kr
   - F12 console 의 `[picker] loaded` 확인
   - "Row 짚기" → row click → 매칭 outline + 자동 매핑 결과
   - smoke + save → host_*.json + poll_state baseline 확인
3. 깨지는 케이스 발견 시 root cause 분석 후 fix
4. T1 PASS 면 T2~T5 진행 (bobaedream/dgist/arca/inven)
5. 전부 PASS 면 §9 의 P2 항목 (triage 페이지 jump 버튼, cases backfill) 진행
