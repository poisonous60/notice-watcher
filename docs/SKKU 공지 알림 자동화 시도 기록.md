# SKKU CSE 공지 자동 알림 — 시도 기록

매일 성균관대 소프트웨어학과 공지를 받아와 **졸업 관련이면 본문 요약 + 링크**, 아니면 짧게 제목만, 새 공지가 없으면 한 줄 알림을 디스코드로 보내는 봇을 만드는 과정에서 **6번 막히고 7번째에 성공**한 기록.

본 문서는 어떤 길을 시도했고 왜 막혔는지, 그리고 최종적으로 채택한 구조와 그 근거를 정리한다. 같은 종류의 자동화를 시도할 때 같은 함정을 다시 밟지 않기 위함.

---

## 0. 최종 채택 구조

```
GitHub Actions (cron 매일 08:07 KST, ubuntu-latest, Azure US)
    ↓
Python 스크립트 실행
    ├─ adapters/skku_cse.py  : httpx + bs4 (probe 검증된 selector)
    ├─ keyword + lookback 필터
    ├─ Gemini 2.5 Flash REST API : 본문 4-6줄 요약
    └─ Discord webhook POST
```

| 구성 요소 | 채택 |
|---|---|
| 스케줄러 | GitHub Actions cron (`7 23 * * *` UTC) |
| 스크랩 환경 | GitHub Actions runner (Azure US) |
| 스크랩 코드 | `adapters/skku_cse.py` (httpx + BeautifulSoup) |
| 요약 모델 | `gemini-2.5-flash` REST API (free tier) |
| 알림 채널 | Discord incoming webhook |
| 비용 | 영구 0원 (모두 무료 티어) |
| repo | https://github.com/poisonous60/skku-notice-bot |

---

## 1. 시도 기록 (시간 순)

### 시도 1 — Claude Routines + WebFetch 직접 호출
- **무엇을**: claude.ai/code/routines 에 daily cron + WebFetch(SKKU URL) 등록
- **결과**: HTTP 403 Forbidden (즉시)
- **원인**: SKKU 사이트가 Anthropic 데이터센터 IP/UA를 봇으로 분류해 차단
- **교훈**: SKKU는 단순 UA만 넣어도 한국 가정 IP에선 통과하지만, 클라우드 IP는 헤더 무관 차단

### 시도 2 — Claude Routines + Jina Reader (`r.jina.ai`)
- **무엇을**: WebFetch URL을 `https://r.jina.ai/<SKKU URL>` 로 (Jina의 무료 reader 프록시)
- **결과**: 200 OK 받지만 **본문에 게시판 테이블이 없음** — Jina의 메인 콘텐츠 추출기가 메뉴까지만 캡처하고 잘라먹음
- **보강 시도**: `X-Target-Selector: ul.board-list-wrap` 헤더로 부분 추출하면 정상 작동 (로컬 확인). 그러나 **WebFetch는 커스텀 헤더 미지원**. URL 파라미터(`?target_selector=...`)도 Jina 측에서 받지 않음.
- **교훈**: Jina는 헤더로만 정밀 제어 가능 → Claude WebFetch와 호환 불가

### 시도 3 — Claude Routines + `api.allorigins.win` (무료 CORS 프록시)
- **무엇을**: `https://api.allorigins.win/raw?url=<encoded SKKU>`
- **로컬**: 200 OK, 60KB 정상 HTML, 게시글 selector 모두 동작
- **루틴**: 403
- **원인**: 무료 공공 프록시는 어뷰즈 방지로 알려진 데이터센터 IP를 차단함. Anthropic IP가 그 블랙리스트에 포함.

### 시도 4 — Claude Routines + Cloudflare Worker
- **무엇을**: 본인 계정에 워커(`skku-proxy.poisonous60.workers.dev`) 배포. Chrome UA + `Accept-Language: ko-KR` 주입해서 SKKU 호출.
- **로컬**: 200 OK
- **루틴**: 403, **`?ping=1` 같은 SKKU 무관 엔드포인트도 403**
- **진단**: ping이 워커 코드 한 줄이면 항상 200을 반환해야 하는데 403이 났다 = **워커 코드가 실행조차 안 됨** = Cloudflare 엣지가 Anthropic 요청을 워커 진입 전에 차단
- **원인**: `*.workers.dev`라는 공유 서브도메인에 Cloudflare 기본 봇 관리가 활성. 무료 플랜에선 끌 수 없고 우회하려면 본인 도메인을 워커에 연결해야 함.

### 시도 5 — Claude Routines + Vercel Edge Function (서울 리전 핀)
- **무엇을**: Vercel CLI로 배포, `regions: ['icn1']` 으로 서울(AWS Seoul) 리전 고정
- **로컬**: 200 OK, `region=icn1` 정상
- **루틴**: 403
- **원인 추정 (당시)**: Vercel hobby tier가 Anthropic IP를 자동으로 봇으로 분류

### 시도 6 — Claude Routines + Vercel + Protection Bypass Token
- **무엇을**: Vercel 보호 레이어를 우회하라고 만들어진 정식 메커니즘. 비밀 토큰 발급 후 URL에 `?x-vercel-protection-bypass=<token>&x-vercel-set-bypass-cookie=true` 추가
- **로컬**: 200 OK
- **루틴**: 403 (토큰을 줘도 동일)
- **진단을 통한 발견**: 검색해보니 GitHub Issue #41741 등에서 동일 패턴 보고됨. **Claude Code의 WebFetch는 Anthropic 자체 egress 프록시를 거치며, 이 프록시는 호스트 allowlist를 가지고 있다.** `*.vercel.app`, `*.workers.dev` 등은 allowlist에서 제외되어 있어 토큰이 평가될 기회조차 없음 (`x-deny-reason: host_not_allowed`).
- **교훈**: 우리가 시도해온 5번째 우회까지가 모두 같은 근본 원인이었음 — 모든 무료 CDN/프록시 도메인이 Anthropic egress allowlist에 빠져 있음. **Claude 루틴 안에서 임의 도메인을 fetch하는 것 자체가 구조적으로 불가**.

### 시도 7 — ★ GitHub Actions + Gemini + Discord (최종)
- **발상 전환**: Claude 루틴이 SKKU에 직접 접근하려고 발버둥치는 게 아니라, **워크플로우 전체를 Anthropic 인프라 밖에서 돌리자**. Claude 모델이 꼭 필요하면 어차피 Anthropic API를 별도로 호출하면 되고, 이 사례에선 무료 Gemini로 충분.
- **GitHub Actions runner의 SKKU 도달성**: 사전에 막힐 가능성을 우려했으나 **실제 호출 시 통과**. SKKU의 차단 로직은 Anthropic IP 대역 한정인 듯.
- **결과**: 첫 풀 실행에서 3건 모두 발송 성공. 이후 알림 분기 로직 추가 후에도 정상.

---

## 2. 차단 매트릭스 (요약표)

| 진입 경로 | 한국 가정 IP | Anthropic Claude 루틴 | GitHub Actions (Azure US) |
|---|---|---|---|
| SKKU 직접 (httpx + Chrome UA) | ✅ 200 | ❌ 403 | ✅ 200 |
| Jina `r.jina.ai` | ✅ (콘텐츠 잘림) | ✅ (콘텐츠 잘림) | — |
| `allorigins.win` | ✅ 200 | ❌ 403 | — |
| Cloudflare Worker (`workers.dev`) | ✅ 200 | ❌ 403 (코드 미실행) | — |
| Vercel Edge (`vercel.app`, icn1) | ✅ 200 | ❌ 403 | — |
| Vercel + bypass token | ✅ 200 | ❌ 403 | — |

---

## 3. 핵심 발견 — Anthropic Egress Proxy의 도메인 Allowlist

Claude Code의 WebFetch (루틴/Cowork 포함)는 Anthropic이 운영하는 **egress 프록시**를 거친다. 이 프록시는 임의의 외부 호스트로 요청을 보내지 않고, **도메인 allowlist에 있는 호스트만 통과**시킨다.

- 막혀 있는 도메인 (확인됨): `*.vercel.app`, `*.workers.dev`, 일반 무료 프록시 서비스 다수
- 통과되는 도메인 (확인됨): GitHub 관련 (`github.com`, `raw.githubusercontent.com`), Wikipedia 등 주류 사이트
- 차단 사유 헤더: `x-deny-reason: host_not_allowed`

**참고 GitHub 이슈**:
- [anthropics/claude-code#41741 — WebFetch blocked by egress proxy for custom domains](https://github.com/anthropics/claude-code/issues/41741)
- [anthropics/claude-code#22846 — WebFetch returns 403 on Wikipedia and other sites](https://github.com/anthropics/claude-code/issues/22846)
- [anthropics/claude-code#52479 — WebFetch blocked by AllTrails edge protection](https://github.com/anthropics/claude-code/issues/52479)
- [anthropics/claude-code#13718 — Webfetch not working in cloud version](https://github.com/anthropics/claude-code/issues/13718)

**결론**: Claude 루틴 안에서 임의 사이트를 자유롭게 fetch하는 워크플로우는 현시점(2026-05) 구조적으로 어렵다. 만약 꼭 루틴을 써야 한다면 **GitHub Gist 같은 allowlist 안 도메인**에 외부에서 미리 데이터를 올려놓고 루틴이 그걸 읽는 식의 우회가 필요.

---

## 4. 왜 GitHub Actions가 정답이었는가

| 요구사항 | GitHub Actions |
|---|---|
| 24/7 동작 (PC 무관) | ✅ |
| 무료 | ✅ (월 2000분 중 우리 용도 ~3분) |
| cron 스케줄 | ✅ (UTC 기준, KST는 9시간 빼서 작성) |
| 사이트 직접 호출 가능 | ✅ (Azure US runner, SKKU 통과) |
| 비밀 키 안전 보관 | ✅ (encrypted secrets) |
| Discord 등 임의 외부 호출 | ✅ (egress 제한 없음) |
| 코드 변경 = git push | ✅ |

**Anthropic 인프라의 egress 제한이 없다는 점이 결정적**. SKKU도 Discord도 Gemini API도 자유롭게 호출 가능.

---

## 5. 운영 메모

- **cron 시간**: `7 23 * * *` (UTC) = 매일 08:07 KST. 정시(`0`)는 GitHub 부하 몰리는 시간이라 5~30분 지연 잦음. 7분 옮긴 이유.
- **lookback**: 2일. 일요일이나 운영 실패 시 24시간을 놓치는 걸 방지하기 위해 1일이 아닌 2일.
- **키워드**: `졸업, 졸업과제, 졸업평가, 졸업논문, 졸업요건, 학위, 연구논문작품` (env `SKKU_KEYWORDS`로 오버라이드 가능)
- **알림 분기**:
  1. 새 공지 0건 → `🔕 오늘(YYYY-MM-DD) 추가된 공지 없음.`
  2. 졸업 키워드 매칭 → 글마다 `🎓 + 제목 + 날짜 + 링크 + Gemini 4-6줄 요약`
  3. 졸업 외 → 한 메시지에 `📢 졸업 외 새 공지 N건:` + 제목 리스트
- **Gemini 주의**: `gemini-2.5-flash`는 기본적으로 thinking mode가 on이라 `maxOutputTokens` 한도를 thinking이 다 먹는 사례가 있음. `generationConfig.thinkingConfig.thinkingBudget = 0` 명시 필요.
- **PowerShell 5.1 stdin 인코딩 함정**: `"value" | gh secret set NAME` 패턴은 UTF-16으로 인코딩되어 secret 값이 깨짐. **`gh secret set NAME --body "value"` 형태로 직접 인자 전달**해야 함.
- **GitHub Actions runner의 SKKU 도달성**: 현재(2026-05) 통과. SKKU가 정책 강화하면 ScraperAPI 무료 1000회/월(`SKKU_PROXY_URL` env로 자동 폴백) 또는 한국 VPS로 우회 가능.

---

## 6. 만약 GitHub Actions도 막힌다면 (예비 카드)

1. **ScraperAPI 무료** 1000 req/month — SKKU만 그쪽으로 우회. `SKKU_PROXY_URL=https://api.scraperapi.com?api_key=...&url={target}` 한 줄로 어댑터가 자동 사용.
2. **한국 VPS** 월 5천원 — Vultr Seoul, AWS Lightsail Seoul 등에 인스턴스 띄워 cron + Python. 한국 IP라 차단 가능성 거의 0.
3. **Cloudflare Tunnel from 자택 PC** — PC가 켜져 있을 때만이라는 단점이 있지만 IP 문제는 영구 해결.

---

## 7. 같은 패턴을 다른 사이트에 적용할 때

1. **probe 도구로 사이트 분석** (`scripts/probe.py "<URL>"`) — selector·차단 정책·필요 헤더 파악
2. **`docs/사이트 어댑터 추가 가이드.md` 따라 어댑터 작성**
3. **본 봇의 `notify_skku.py`를 새 어댑터로 갈아끼우면 알림 시스템 즉시 재사용 가능**

다른 학교·학과 공지 사이트도 SKKU와 비슷한 차단 패턴이 일반적이므로, **GitHub Actions에서 직접 호출**이 첫 시도 1순위. 막히면 이 문서의 차단 매트릭스 순서를 참고해 다음 카드로 이동.
