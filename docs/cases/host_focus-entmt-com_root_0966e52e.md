---
slug: host_focus-entmt-com_root_0966e52e
url: https://www.focus-entmt.com/
status: 🧩 수동 config — Focus Entertainment /en/news static cards
outcome: handcrafted
date: 2026-05-26
fix_layer: none
failure_keys: [codex_agentic_timeout, root_marketing_homepage, article_fetch_timeout]
config_strategy: httpx_html
adapters_changed: []
engine_files_touched: []
tags: [manual-config, static-html, news-cards, list-only-body]
requested_by: dashboard
---

## 트리거

`https://www.focus-entmt.com/` 자동 등록 실패.

`output/poll_state/host_focus-entmt-com_root_0966e52e.FAILED.json`:

`gemini 생성+검증 3회 실패`, `last_feedback = codex_agentic timeout after 93.58492471510544s`.

## preflight

preflight: `miss — host_focus-entmt-com_root_0966e52e`.

- `configs/host_focus-entmt-com_root_0966e52e.json` 없음.
- `engine.recognizers.recognize("https://www.focus-entmt.com/")` 결과 `None`.
- 큐 진입 뒤 현재 worktree에 prompt/engine/probe/recognizer 변경 없음.
- 최초 로컬 artifact 부재라 `scripts/triage.py pull --slug host_focus-entmt-com_root_0966e52e` 로 N100 artifact 를 read-only pull 했다.
- 현재 Windows dev box 에서는 Focus origin TLS/connect 가 `ConnectError [WinError 10054]` 또는 `ConnectTimeout` 으로 실패한다. N100 artifact 와 독립 web fetch 는 접근 가능해서, 로컬 live fetch 실패는 config selector 증거로 쓰지 않았다.

## 진단

N100 probe 요약:

- B1/B2: 200 OK.
- S1.H2: 200 OK, `s1.H2.html` 저장.
- S1.H3: 429 `BLOCKED_BOT`.
- S1.H4: `ReadTimeout`.
- verdict: `정적 HTTP로 충분`, recommended: `httpx (S1.H2)`.
- HTML 반복 후보 6건, first article: `https://www.focus-entmt.com/en/news/warhammer-40000-space-marine-2-shadowdrops-its-purgation-update-just-in-time-for-the-warhammer-skulls-festival`.
- `root_marketing_homepage.is_root_marketing_homepage = true`.
- article direct fetch: `ConnectTimeout`; Playwright article click: `TimeoutError`.

원 URL은 마케팅 홈이지만, 정적 HTML 안에 최신 뉴스 카드 6개가 있고 canonical board 는 `/en/news` 다. 카드 행은 `main a[href*='/en/news/']` 로 안정적으로 분리되고, 각 행 안에 category/date/title/summary/image 가 있다.

## 픽스

`configs/host_focus-entmt-com_root_0966e52e.json` 을 추가했다.

- `strategy: httpx_html`
- `list.url_template: https://www.focus-entmt.com/en/news`
- `row_selector: main a[href*='/en/news/']`
- `post_id`: news URL slug
- `title`: card `h3`
- `published_at`: `p.text-sm` (`%d %B %Y`)
- `category`: card 상단 game label
- `summary`: card teaser
- `cover_image`: card image
- `article.body_empty_acceptable: true`
- `polite_sleep: 5-6s`

article fetch 가 probe 에서 timeout 난다. 폴링은 새 글 본문 fetch 실패를 post raw 의 `fetch_error` 로 남기고 목록 필드 기반 알림은 계속 만들 수 있으므로, list cards 를 권위 데이터로 두고 본문은 optional 로 둔다.

## 트랙 B 검토

- 2a 인식기: X. Focus Entertainment 단일 host 의 board remap 이며 플랫폼 패턴이 아니다.
- 2b `--article-url`: X. 첫 글 URL 자체는 맞았고, 실패는 agentic timeout 및 article fetch timeout 이다.
- 2c probe heuristic: X. digest 가 이미 `root_marketing_homepage` 와 same-host `/en/news/` row 후보를 노출했다.
- 2d prompt/schema: X. LLM 입력 신호 부족이 아니라 codex agentic timeout 이 직접 실패다.
- 2e 수동 config: O.

일반화 안 되는 이유: “root marketing homepage with news cards” 신호는 이미 digest 에 있으며, 이번 해결은 Focus 전용 `/en/news` 카드 구조와 article timeout 정책 선택이다. ALLOW-LIST 밖 prompt/probe/engine 변경으로 확장할 근거가 부족하다.

## 회귀 검증

- `engine.config_schema.validate_config(configs/host_focus-entmt-com_root_0966e52e.json)` → pass.
- N100 `s1.H2.html` artifact offline parse → 6 posts. 첫 글: `warhammer-40000-space-marine-2-shadowdrops-its-purgation-update-just-in-time-for-the-warhammer-skulls-festival`, date `2026-05-21T00:00:00`.
- `python scripts/probe_smoke.py --stage 3 --stage 5` → PASS `1493`, FAIL `0`.
- `python scripts/register.py --config configs/host_focus-entmt-com_root_0966e52e.json` → fail on this Windows dev box only: `httpx.ConnectTimeout` during `fetch_list`. Earlier N100 S1.H2 artifact proves the same target/headers class can fetch the static list; this workspace’s live route currently cannot.

영향 범위는 새 config 파일 1개뿐이다. engine/probe/prompt/recognizer 는 변경하지 않았다.

## escalate

ALLOW-LIST 밖 공통 개선은 하지 않았다. 필요하다면 별도 chunk 로 “agentic timeout 을 site outcome 과 분리해 cheaper fallback/manual handoff 로 기록” 하는 register orchestration 개선을 검토할 수 있지만, 이 slug 의 등록 config 자체에는 필요 없다.
