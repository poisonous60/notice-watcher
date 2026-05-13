# 게임 공지사항 알림 Agent를 위한 크롤링 API 및 방법 종합 조사

## 결론 먼저 — 추천 스택 요약

하루 1회 정도의 가벼운 폴링으로 게임사 공식 공지사항·아카라이브·디시인사이드 글을 수집하고 LLM으로 요약하는 시나리오라면, **풀 헤드리스 브라우저 또는 상용 스크래핑 API를 모든 사이트에 일률적으로 적용하기보다는 사이트별로 가장 가벼운 진입점을 선택**하는 하이브리드 구조가 압도적으로 유리합니다. 구체적으로는 다음 조합을 권장합니다.

| 사이트 유형 | 1차(무료/저비용) 권장 | 보조/대체 |
|---|---|---|
| 게임사 공식 공지(메이플 등 넥슨, 엔씨, 스마일게이트, 펄어비스) | `httpx`/`requests` + `BeautifulSoup`/`lxml`. RSS·Open API 있으면 우선 사용 (넥슨은 `openapi.nexon.com` 제공) | Playwright(JS 렌더링이 필요한 일부 게임 홈페이지) |
| 아카라이브 (arca.live) | 비공식 모바일 앱 API(`https://arca.live/api/app/...`) + 게시판 페이지 GET. Cloudflare 챌린지가 뜨면 헤드리스 우회 필요 | `cloudscraper`, `undetected-chromedriver`, 또는 Playwright + stealth. 정 안 되면 ScrapingBee/ScraperAPI의 JS 렌더링 모드 |
| 디시인사이드 (dcinside) | 모바일 API `m.dcinside.com/api/gall_list.php?...&app_id=...` 또는 `app.dcinside.com/api/gall_list_new.php` (User-Agent를 `dcinside.app`, Referer를 `http://www.dcinside.com`으로 위장) | 비공식 라이브러리 `dc_api`(Python), Playwright (모바일 갤러리 페이지) |
| LLM 친화 1줄 통합 옵션 | Jina Reader(`r.jina.ai/<URL>`)로 마크다운 변환 — 무료 티어로 시작 가능 | 확장 시 Firecrawl(`/scrape`, `/crawl` 엔드포인트) |

새 글 감지 전략은 **마지막으로 수집한 게시물 ID(또는 timestamp)를 로컬 SQLite/JSON에 저장하고 다음 폴링 시 그보다 큰 ID만 요약 파이프라인에 넣는 방식**이 가장 단순하고 안정적입니다. 일 1회 폴링은 robots.txt와 사이트 부담 모두에서 사실상 문제가 되지 않는 수준입니다.

법적으로는 잡코리아 vs 사람인(2017 대법원), 야놀자 vs 여기어때(2022 대법원, 2024 민사) 판례를 종합하면, **(1) 공개된 정보를 (2) 통상의 사용자가 접근 가능한 방식으로 (3) 사이트의 부담을 일으키지 않을 정도의 빈도로 (4) 영업적 무임승차 없이** 수집한다면 형사처벌 가능성은 낮으나, 약관·robots.txt 위반과 부정경쟁방지법상 민사 손해배상 가능성은 별도로 남는다는 점을 항상 인지해야 합니다.

---

## 1. 대상 사이트별 크롤링 방법

### A. 게임사 공식 공지사항 게시판

한국 주요 게임사의 공지 페이지는 대부분 “정적 HTML + 가벼운 JS 보강” 구조이며, 일반 HTTP 클라이언트(`requests`, `httpx`, `aiohttp`)로 충분히 가져올 수 있는 경우가 많습니다.

- **넥슨(Nexon)**: `https://notice.nexon.com/Notice/NoticeList`, 게임별 메이플스토리 `https://maplestory.nexon.com/News/Notice/Notice/...` 등이 대표 URL입니다. 메이플스토리·던파 등 일부 타이틀은 **공식 Open API**(`https://openapi.nexon.com/`)를 무료로 제공하지만, 여기에는 캐릭터/큐브/랭킹 정보만 포함되어 있고 “공지사항 본문” 자체는 포함되지 않습니다. 따라서 공지 본문은 결국 HTML 파싱 또는 RSS가 필요합니다. 넥슨 통합 공지 페이지는 RSS를 공식적으로 광고하지 않으므로, 사이트 footer·`<link rel="alternate" type="application/rss+xml">` 메타태그·`/rss`, `/feed` 경로 시도 → 실패 시 HTML 파싱으로 fallback하는 패턴을 권장합니다.
- **엔씨소프트, 스마일게이트, 펄어비스 등**도 거의 동일합니다. 공지 게시판은 SSR 위주이므로 JS 렌더링은 보통 불필요합니다. 다만 일부 게임은 SPA(React/Next.js) 기반의 신규 사이트로 이전 중이므로, 화면이 비어 있으면 Playwright/Puppeteer로 fallback해야 합니다.
- **봇 차단**: 게임사 공식 공지 페이지에 Cloudflare “I’m under attack” 또는 reCAPTCHA가 걸려 있는 경우는 드뭅니다. 일반적인 자동화 보호(WAF) 정도라서 합리적인 User-Agent와 1초 이상 간격이면 통과합니다.
- **RSS 피드 확인 절차**:
  1. 페이지 HTML에서 `<link rel="alternate" type="application/rss+xml" ...>` 검색
  2. `/rss`, `/feed`, `/rss.xml`, `/atom.xml`, `/board/rss` 등 관용 경로 시도
  3. 페이지 footer/sitemap.xml 확인
  4. 모두 실패하면 “정적 HTML 파싱 + 마지막 게시물 ID 저장”으로 우회

### B. 아카라이브 (arca.live)

- **봇 차단/캡차 시스템**: arca.live는 **Cloudflare 봇 매니지먼트**를 사용하며, 사용자가 빠르게 여러 페이지를 자동 요청하면 “Cloudflare challenge”(403/429, 종종 사람 확인 페이지)가 뜹니다. 컴퓨터공학 채널의 실제 사용자 보고에서도 “requests로는 봇 검사 걸림 → puppeteer로 바꿔도 4번째 요청쯤 걸림 → 5초 간격이면 통과” 같은 패턴이 자주 보고됩니다. 또한 성인 등급/한국 IP 차단된 채널은 **HTTP 451**(Unavailable For Legal Reasons)을 반환합니다.
- **gallery-dl 등 외부 라이브러리에서 `https://arca.live/api/app/view/article/...` 엔드포인트 호출 시 403 Cloudflare challenge가 발생**한다는 이슈가 GitHub에 보고되어 있습니다(mikf/gallery-dl #7556). 즉 Firefox 쿠키를 그대로 넘겨도 cf_clearance 토큰이 만료되면 막힙니다.
- **공식 API**: 공식적으로 일반 개발자에 공개된 API는 없습니다. 다만 모바일 공식앱이 사용하는 **내부 JSON API**(`https://arca.live/api/app/list/channel/<채널명>`, `/api/app/view/article/<채널>/<번호>` 등)가 존재하며, 아카 리프레셔 채널 등에서 이를 활용한 사례가 있습니다. 공앱 API는 HTML이 아닌 JSON을 반환하므로 파싱이 훨씬 깨끗하지만, **여전히 Cloudflare 보호 하**에 있어 클라이언트가 정상 브라우저처럼 보여야 합니다.
- **비공식 라이브러리**:
  - `arcalive` (npm/PyPI 둘 다 존재, GitHub 활동 거의 정지) — 로그인/게시글/댓글 API 래핑. 단 “성인 게시글은 로그인해도 안 가져와진다”는 등 한계 보고됨.
  - `Arca-API` (flipggs/Arca-API) — Node 기반, 매우 작은 규모.
  - 사용자 스크립트 `ArcaRefresher`(lekakid) — Tampermonkey용이라 서버사이드 크롤링에는 부적합하지만, 어떤 DOM 구조와 어떤 엔드포인트가 유효한지 분석할 때 좋은 참고 자료입니다.
- **사용자가 경험한 “히토미 브라우저(Hitomi Downloader)” 활용 원리**: KurtBestor/Hitomi-Downloader는 Python 기반 데스크톱 다운로더로, 내부적으로 **임베디드 Chromium**을 띄워 페이지를 렌더링하고, 필요 시 `clf2` 모듈로 **Cloudflare 챌린지를 자동 통과**한 뒤 쿠키를 캡처해 추출 스크립트가 사용합니다. 즉 “히토미 브라우저로 아카라이브 글이 받아져요”의 본질은 (a) 진짜 Chromium이 JS를 실행하므로 Cloudflare가 사람으로 인식, (b) 사이트별 “downloader 스크립트”가 페이지 구조를 알고 추출, (c) DPI 우회·사용자 로그인 시 쿠키 import 등 부가 기능 — 이 세 가지의 조합입니다.
  - **파이프라인 통합 가능성**: Hitomi Downloader는 GUI 중심이고, 자체 “스크립트” 시스템(`/wiki/Scripts`)으로 사이트 핸들러를 확장할 수 있지만, Headless 서버 봇 용도로는 무겁고 부적합합니다. **그 작동 원리(Chromium 실행 → Cloudflare 통과 → 쿠키 캡처)를 직접 재현**하는 것이 더 깔끔하며, 이는 사실 `undetected-chromedriver`, `Playwright + playwright-stealth`, `camoufox`(Firefox 기반 안티디텍트), `SeleniumBase` 같은 도구가 이미 똑같이 하고 있는 일입니다.
- **새 글 감지 권장 방식**: 채널 목록 첫 페이지(또는 공앱 list API의 첫 페이지)만 받아서 게시물 ID 목록을 만들고, 직전 폴링에서 저장한 “마지막 ID”보다 큰 것만 본문 fetch → 본문은 JSON API가 가장 효율적입니다. 전체 페이지 파싱은 절대 권장하지 않습니다.

### C. 디시인사이드 (dcinside.com)

- **봇 차단**: 디시인사이드 자체는 Cloudflare를 메인 WAF로 쓰지 않고, **자체 차단(IP 단위 rate limit, User-Agent 필터, Referer 체크)** 위주입니다. PC 웹 `gall.dcinside.com`은 공격적인 스크래핑에 IP 단위 차단을 거는 것으로 알려져 있습니다.
- **모바일 vs PC**:
  - 박종훈 기술블로그(2023)의 실전 보고에 따르면 PC는 차단이 빈번해 Playwright로 헤더(`User-Agent`, `Referer: https://gall.dcinside.com/`, `sec-ch-ua-mobile`, `Accept-Language: ko-KR`)를 정교하게 세팅해야 했습니다.
  - 모바일 `m.dcinside.com`과 공식 앱 백엔드는 **JSON 기반 비공식 REST API**를 노출합니다. GitHub `organization/OpenDC`에 정리된 분석 문서가 사실상 표준 참고자료이며, 핵심 엔드포인트는:
    - 글 목록: `http://app.dcinside.com/api/gall_list_new.php?id=<갤러리>&page=1&app_id=<base64>`
    - 글 본문: `http://app.dcinside.com/api/gall_view_new.php?id=<갤러리>&no=<글번호>&app_id=<base64>`
    - 모바일 웹: `https://m.dcinside.com/api/gall_list.php?id=<갤러리>&page=1&app_id=<base64>` (응답이 깨지면 `redirect.php?hash=<base64(URL)>` 우회 사용)
    - 모든 호출에 `User-Agent: dcinside.app`, `Referer: http://www.dcinside.com` 필수.
- **갤러리별 새 글 크롤링 권장 방식**:
  1. 위의 `gall_list_new.php` 호출로 1페이지(보통 30~50개)만 받고, 게시물 번호(`no`) 기준으로 직전 저장값보다 큰 것만 추출.
  2. 새 글마다 `gall_view_new.php`로 본문을 받아 LLM에 전달.
  3. 마이너 갤러리/미니 갤러리도 같은 패턴이지만 `id=` 값과 `headid` 등 파라미터가 추가됩니다.
- **비공식 Python 라이브러리**:
  - `eunchuldev/dcinside-python3-api` (`dc_api`) — async 기반, `api.board(board_id="programming")`으로 무한 글 목록 iterate, 글 본문/이미지/댓글 모두 지원, 댓글/글 작성도 가능. 새 글 감지 봇에 가장 적합한 선택지입니다.
  - `seunghyukcho/dc-crawler` — 글·댓글 수집용 단순 라이브러리.
- **RSS**: 디시인사이드는 공식 RSS를 제공하지 않습니다(과거 일부 갤러리에서만 제공된 적 있으나 현재는 사실상 사용 불가). 따라서 RSS 의존은 권장하지 않습니다.

---

## 2. 크롤링 도구/API 옵션

### 2-1. 무료 / 오픈소스

| 도구 | 장점 | 단점 / 한계 | 본 프로젝트 적합도 |
|---|---|---|---|
| **`requests` + BeautifulSoup** | 가장 단순, 의존성 최소, 정적 HTML에서 매우 빠름 | JS 렌더링 불가, Cloudflare/봇탐지 회피 안 됨 | 게임사 공식 공지 ★★★★★, 디시 모바일 API ★★★★, 아카라이브 ★★ |
| **`httpx` / `aiohttp`** | async, HTTP/2, 대량 동시 요청 시 효율 | 위와 동일한 봇 회피 한계 | 일 1회 폴링이라면 굳이 async 필요는 적음. dc_api가 내부적으로 사용 |
| **Selenium + selenium-stealth / undetected-chromedriver** | 진짜 Chrome 띄움 → Cloudflare/JS 대응. 한국 블로그(pythondocs.net)에 실전 노하우 풍부 | 무겁고 느림, Selenium 자체 핑거프린트는 detected될 수 있어 stealth 필요 | 아카라이브 fallback ★★★★ |
| **Playwright (Python/Node)** | 현대적 API, headful/headless 모두, screenshot/PDF, stealth 플러그인 | Selenium보다 무겁지 않지만 여전히 메모리·CPU 비용 | 박종훈 블로그처럼 디시인사이드 백업에 사용. 아카라이브 강력 ★★★★★ |
| **Puppeteer (Node) + @sparticuz/chromium** | Lambda·Cloud Run에 올리기 좋음. 클리앙 사례에서 Cloudflare 통과 성공 보고 | Node 생태계 한정, RAM 1GB+ 필요 | 서버리스로 가성비 좋음 ★★★★ |
| **Scrapy** | 대규모 크롤링 프레임워크, 미들웨어, 파이프라인 | 일 1회 단순 폴링에는 과한 학습 비용 | 본 프로젝트엔 오버엔지니어링 ★★ |
| **Crawl4AI** | LLM 친화 마크다운 출력, Playwright 기반 셀프호스팅 | 인프라/프록시 직접 관리 | 셀프호스팅 의지 있을 때 ★★★ |
| **`cloudscraper`** | requests 호환, 일부 Cloudflare 챌린지 통과 | Cloudflare 업데이트에 자주 깨짐, 최신 v2 챌린지엔 거의 무력 | 단기 보조 ★★ |
| **`camoufox` / SeleniumBase UC** | 최신 안티디텍트, 2026년 현재도 Cloudflare 통과 가능한 몇 안 되는 OSS | 환경 세팅이 까다롭고 헤비함 | 아카라이브 강제돌파 ★★★★ |
| **gallery-dl** | 100+ 사이트 추출기, ArcalivePostExtractor 내장 | arca.live는 현재 Cloudflare로 막힘 (#7556 이슈) | 참고용 ★★ |

### 2-2. 유료 / 상용 스크래핑 API (2026년 시점 기준)

가격은 본 글 작성 시점에 공개된 정보이며, **모두 변동 가능**합니다. 시작 전에 공식 페이지에서 재확인하세요.

| 서비스 | 시작 가격 | 무료 티어 | JS 렌더링 | CAPTCHA/Cloudflare | 한국 IP/사이트 | 메모 |
|---|---|---|---|---|---|---|
| **ScraperAPI** | $49/월 (Hobby) | 일정량 무료 트라이얼 | 포함(크레딧 더 소모) | 자동 retry 포함 | 지원 | 가장 “일반적인” 선택. 한국 사이트 hit/miss 있음 |
| **ScrapingBee** | $49/월 (Freelance, ~150K 크레딧) | 1,000 무료 호출 | 포함(5크레딧) | Stealth 모드 추가 크레딧 | 지원 | 단순 API, JS 렌더링 강함, 미디어 응답 4.29초로 다소 느림 |
| **Bright Data (구 Luminati)** | PAYG $1.50/1K | 무료 트라이얼 | Web Unlocker/Web Scraper API | 업계 최고 수준 | 매우 강함(거대 잔여 풀) | 엔터프라이즈, 가격·셋업 부담 |
| **Apify** | Starter $29 / Scale $99 | $5 크레딧/월 무료 | Actor 기반 | Actor마다 다름 | 한국 사이트용 Actor도 존재 | 마켓플레이스 “디시인사이드”/“아카라이브” Actor는 거의 없음. 직접 작성 필요 |
| **Zyte (구 Scrapinghub)** | API ~$1.01/1K (쉬움) ~ 그 이상 | 무료 트라이얼 | Smart Browser | 자동 anti-bot | 지원, Scrapy 친화 | Python/Scrapy 팀에 최적, 빠름(2.58s 중앙값) |
| **Oxylabs** | $49/월~ | 무료 트라이얼 | 포함 | 강함 | 거대 프록시 풀 | 대역폭 기반 — 비용 예측 어려움 |
| **Crawlbase (구 ProxyCrawl)** | 1,000 무료 호출 → $29/월~ | 1,000 호출 무료 | 포함 | Smart Proxy | 한국 IP 옵션 | 단순 토큰 기반 API |
| **해시스크래퍼(Hashscraper, 한국)** | 한국어 UI/봇 마켓 | 일부 무료 | 포함 | 사이트별 봇으로 추상화 | **디시인사이드 게시물 수집 봇 제공** | 코딩 없이 시작 가능, API 연동 가능 |
| **Octoparse** | $89/월~ (Standard) | 무료 플랜 | 포함 | Cloudflare CAPTCHA 자동 처리 모드 | **디시인사이드 템플릿 제공** | 노코드 GUI, 빠른 PoC용 |

본 프로젝트(일 1회·소수 갤러리)는 무료 한도만으로 충분히 운용 가능한 규모입니다. 유료 옵션은 “Cloudflare가 과해져서 셀프 OSS로는 더 이상 못 통과한다”는 단계에서 검토하면 됩니다.

### 2-3. LLM 친화적 크롤링 API (최신 트렌드)

| 도구 | 본 프로젝트와의 궁합 |
|---|---|
| **Firecrawl** (`firecrawl.dev`) | URL → LLM-ready Markdown / JSON. `/scrape`, `/crawl`, `/map`, `/search` 통합. Starter ~$83/월부터, 무료 크레딧 있음. 게임 공식 공지처럼 “페이지 한 장을 깔끔히 변환”하는 데 최적. Cloudflare 사이트엔 일부 약함 — 아카라이브엔 보장되지 않음. |
| **Jina Reader** (`r.jina.ai/<URL>`) | 1줄 변환 — `https://r.jina.ai/https://maplestory.nexon.com/News/Notice/...` 같이 prefix만 붙이면 끝. 무료 티어 있고 토큰 단가 매우 저렴. 게임사 공식 공지의 본문 정제·LLM 입력 단계에 추천. 단 Cloudflare 강한 사이트, 로그인 필요, 복잡한 인터랙션 페이지엔 약함. |
| **Browserbase** | 클라우드에 매니지드 Chromium을 띄우고 Playwright/Puppeteer로 원격 조작. CDP 호환. 본 프로젝트가 “셀프 Playwright를 안 돌리고 클라우드에서 돌리고 싶다”면 좋은 선택. |
| **Crawl4AI** (셀프호스팅) | OSS, Playwright 위에 마크다운 변환. 비용 0이지만 인프라 직접 운영. |
| **Spider.cloud, ScrapeGraphAI** | LLM/AI 에이전트 친화. ScrapeGraphAI는 자연어 추출 스키마를 받아 JSON 반환 — 게시판 메타(title/date/author/body) 같은 작은 스키마 추출에 빠르게 사용 가능. |

요약하면, **게임사 공지처럼 합법적이고 봇 보호가 약한 페이지**는 Jina Reader 1줄 변환이 LLM 파이프라인 통합 면에서 가장 깔끔합니다. **Cloudflare가 강한 아카라이브**는 Firecrawl/Jina 같은 “LLM 수렴형” API보다 직접 헤드리스 또는 ScraperAPI/Bright Data 같은 “통과 능력에 특화된” 서비스가 더 신뢰할 만합니다.

---

## 3. 자바스크립트 렌더링 및 봇 우회 전략

### 3-1. Headless 브라우저 vs HTTP 요청 — 선택 기준

다음 중 하나라도 해당하면 헤드리스 브라우저(Playwright/Puppeteer/UC)가 필요합니다.
1. 페이지를 `curl`로 받았을 때 본문이 비어 있고 `<div id="root">`만 있는 경우(SPA)
2. Cloudflare “Just a moment…” 또는 “Verifying you are human” JS 챌린지 페이지 반환
3. reCAPTCHA/hCaptcha/Turnstile 위젯 강제
4. 무한 스크롤·클릭 후 데이터 로드되는 페이지
5. 로그인 후에만 보이는 콘텐츠

이외(특히 게임사 공지, 모바일 디시 API)는 `httpx`/`requests`로 충분합니다. 일 1회 사용엔 헤드리스가 압도적으로 비효율적이므로, **HTTP 클라이언트로 시도 → 실패 시에만 헤드리스로 fallback**하는 2단계 전략을 권장합니다.

### 3-2. User-Agent / 헤더 / 프록시 로테이션

- 평범한 데스크톱 Chrome User-Agent 1~3개를 라운드로빈
- `Accept-Language: ko-KR,ko;q=0.9` 명시
- `Referer`를 사이트 자체 도메인으로 세팅(특히 디시 — `Referer: http://www.dcinside.com` 필수)
- IP 차단이 걸리는 경우 한국 IP 풀이 있는 프록시(Bright Data, Oxylabs, Smartproxy 등) 또는 로컬 VPN 사용. 일 1회 폴링이라면 차단 자체가 거의 발생하지 않으므로 보통 불필요.

### 3-3. Cloudflare/CAPTCHA 우회 (2026년 현황)

- **`cloudscraper`/`cfscrape`/`Humanoid` 같은 OSS 라이브러리는 사실상 메인 사용처가 아닙니다.** Bright Data 2026 가이드도 “이런 라이브러리는 수년간 업데이트되지 않아 현재의 Cloudflare를 통과하기 어렵다”고 명시합니다.
- **현재 OSS에서 그나마 작동하는 두 옵션은 (a) `Camoufox`(Playwright + custom Firefox 기반 anti-detect), (b) `SeleniumBase` UC 모드.** 둘 다 내부적으로 진짜 브라우저 + 핑거프린트 위장.
- **`undetected-chromedriver`**(ultrafunkamsterdam) — 특정 Chrome 버전에 의존(예: 115). 매년 깨짐과 패치를 반복.
- **상용 API**의 Stealth/Anti-bot 모드는 사실상 “위 OSS들을 클라우드에서 굴려주는 것”이며, 개발 시간 대비 가성비가 크게 좋아질 수 있습니다(특히 1인 프로젝트).
- **2Captcha/Anti-Captcha**: hCaptcha/recaptcha를 비용($1/1K~$3/1K) 내고 풀어주는 서비스. 본 프로젝트의 폴링 사용 사례에는 거의 불필요.

### 3-4. 한국 사이트에서 자주 마주치는 봇 차단 유형

1. **Cloudflare JS challenge** — 아카라이브, 일부 게임 커뮤니티(루리웹 등)
2. **자체 IP rate-limit + User-Agent 필터** — 디시인사이드, 잡코리아
3. **451 Unavailable For Legal Reasons** — 아카라이브 성인/한국 차단 채널, 한국 IP에서만 발생
4. **DPI(통신사 SNI) 차단** — Hitomi 등 일부 도메인. 히토미 다운로더가 GoodbyeDPI를 내장한 이유. 게임 공지엔 해당 없음.

### 3-5. 히토미 브라우저 작동 원리 다시 정리

- 본질은 **(a) 임베디드 Chromium + (b) 사이트별 Python “downloader 스크립트”(extractor 클래스 상속) + (c) Cloudflare 솔버(`clf2`) + (d) 브라우저 쿠키 import + (e) GoodbyeDPI**의 통합 패키지입니다(KurtBestor/Hitomi-Downloader 위키, DeepWiki 분석).
- “히토미 브라우저로 아카라이브가 잘 받아진다”는 사용자 경험은 (a)·(c)·(d)의 효과로, 결국 **Playwright(Chromium) + stealth + 사용자 쿠키 재사용** 조합으로 동일하게 재현 가능합니다. 따라서 서버 사이드 알림 봇에는 Hitomi Downloader를 직접 통합하기보다 **그 원리를 Playwright로 재구성**하는 편이 운영·자원 면에서 훨씬 합리적입니다.

---

## 4. 새 글 감지 전략

### 4-1. 폴링 효율 — 일 1회는 사실상 무부담

- 각 사이트에 1일 1회 “목록 1페이지 + 신규 글 본문”만 가져온다면 사용자 1명이 해당 게시판을 한 번 방문하는 것과 트래픽이 동일하거나 더 적습니다. robots.txt 위반·서비스 부담은 사실상 발생하지 않습니다.
- 알림 latency가 더 짧아야 한다면 30분~1시간 폴링도 안전합니다. 아카라이브 같은 Cloudflare 사이트는 짧은 간격일수록 챌린지가 자주 뜨므로, **간격을 고정하기보다 jitter(±30%)**를 주는 편이 좋습니다.

### 4-2. 마지막 게시물 ID/타임스탬프 비교

- 가장 단순하고 신뢰성 있는 방식. 박종훈 기술블로그(2023)의 `latest_id_pointer.json` 패턴이 사실상 표준.
- 디시·아카는 글 번호가 단조 증가하므로 **`last_seen_id` 1개**만 저장하면 됩니다.
- 게임 공식 공지가 ID 대신 날짜만 보이는 경우, RFC2822/ISO 날짜를 파싱해 `last_seen_at` 저장.
- 충돌/누락 방지를 위해 “직전 5~10개의 ID 집합”을 추가로 저장해 deduplication하는 보강도 추천.

### 4-3. RSS/Atom 활용

- 메이플스토리·검은사막 공지 등 일부 게임은 비공식적으로 RSS를 노출하지만 보장은 없습니다. RSS는 “있으면 무조건 우선 사용”하되 fallback 경로 필수.
- 아카라이브, 디시인사이드, 루리웹은 **공식 RSS 사실상 없음**. 무시.

### 4-4. 변경 감지 서비스(Distill.io, Visualping)

- “셀프호스팅하지 않고 폴링만 외주” 용도로는 가능하지만, 본 프로젝트는 “감지 후 LLM 요약 → 모바일 푸시”까지 자체 파이프라인을 가져야 하므로, 이런 SaaS는 알림 시점만 잡고 본문 fetch는 결국 다시 직접 해야 합니다. **권장도 낮음.** 다만 ‘아카라이브가 너무 자주 막혀서 SaaS의 헤드리스 인프라를 빌리고 싶다’면 Visualping의 “content change → webhook” 트리거를 LLM 파이프라인의 진입점으로 쓰는 변형은 유효합니다.

---

## 5. 한국 개발자 커뮤니티의 실전 사례

- **`eunchuldev/dcinside-python3-api`** — 가장 잘 알려진 비공식 디시 라이브러리. async 인터페이스로 “board 글 무한 iterate → 본문/댓글/이미지 추출 → 댓글/글 작성”까지 지원. 본 프로젝트의 디시인사이드 부분에 그대로 사용 가능.
- **`seunghyukcho/dc-crawler`** — 더 단순한 디시 크롤러.
- **`organization/OpenDC`(GitHub)** — 디시인사이드 모바일/공식앱 API의 내부 동작 분석 문서. `gall_list_new.php`, `gall_view_new.php`, 검색 API의 파라미터·헤더가 정리되어 있음.
- **박종훈 기술블로그(jonghoonpark.com, 2023)** — Playwright(Python)로 디시 갤러리 주기 백업·텔레그램 봇 알림 구축한 실전 글. 헤더 셋업, 마지막 ID 기록 패턴이 그대로 본 프로젝트의 템플릿이 됩니다.
- **클리앙 “Cloudflare 우회 크롤링 성공” 글** — Node Puppeteer + `@sparticuz/chromium`을 AWS Lambda(1024MB)로 올려 Cloudflare 사이트를 통과한 사례.
- **블로그 peanutz.site** — `selenium-stealth` 활용한 Cloudflare 우회 한국어 가이드.
- **pythondocs.net “셀레니움 봇 탐지 우회” 시리즈** — undetected-chromedriver와 “이미 열린 Chrome에 attach” 기법.
- **arca.live `programmers` 채널 토론(2022)** — 아카라이브 자체 사용자들이 “requests/puppeteer 모두 봇 검사에 걸린다 → 5초 간격이 안전선”이라는 합의를 형성한 사례.
- **`KurtBestor/Hitomi-Downloader`(27.7K star)** — Cloudflare solver(`clf2`), DPI bypass, 임베디드 브라우저 로그인을 한 패키지로 통합한 가장 잘 알려진 한국 OSS. 직접 통합보다는 “설계 참고”로 가치가 있습니다.
- **Hashscraper, Octoparse(한국어 지원)** — 노코드로 디시인사이드 갤러리·키워드 모니터링 봇을 GUI로 만들 수 있어 프로토타이핑/검증용으로 빠릅니다.

실전 노하우 종합:

1. 디시는 **모바일/앱 JSON API + dc_api 라이브러리**가 가장 안정.
2. 아카라이브는 **헤드리스 Chromium + stealth + 5초 이상 간격**이 무난한 합의.
3. 어떤 방식이든 **마지막 본 ID 저장 + 1페이지만 fetch**가 사실상 표준.
4. `requests`로 막히면 → `cloudscraper` → `undetected-chromedriver`/`Playwright stealth` → 상용 API 순으로 단계적으로 올린다.

---

## 6. 법적 / 윤리적 고려사항

### 6-1. 핵심 한국 판례

| 판례 | 결론 | 본 프로젝트 시사점 |
|---|---|---|
| **잡코리아 vs 사람인 (대법원 2017)** | 사람인의 무단 크롤링은 데이터베이스권 침해 + 부정경쟁행위. 약 4.5억원 손해배상 확정. **결정적 사유: VPN으로 IP 우회, robots.txt 무시, User-Agent 위장, 영업적 무임승차** | 사이트가 robots.txt로 명시 금지 + 약관에 금지 명문화 + 차단 우회까지 했다면 민사 책임 가능성 높음 |
| **야놀자 vs 여기어때 (대법원 형사 2022)** | 1심 유죄 → 2심·대법 무죄 확정. **결정적 사유: 가져간 정보가 일반 이용자에게 공개돼 있고, API에 접속 차단 조치가 없었으며, 업무방해도 입증 부족** | 공개 정보를 정상 빈도로 가져오는 것은 정보통신망 침해죄에 해당하지 않을 가능성 큼 |
| **야놀자 vs 여기어때 (민사 2024)** | 형사는 무죄지만 부정경쟁방지법상 ‘성과 도용’으로 **10억원 손해배상 인정** | 형사 무죄 ≠ 민사 무죄. **영업적 활용**(특히 경쟁 서비스에 그대로 게시) 시 위험 |

### 6-2. 본 프로젝트 적용 가이드

본 프로젝트는 **(a) 본인이 보기 위한 알림**, **(b) LLM 요약 후 푸시**, **(c) 원문 그대로의 영리 재게시 아님**, **(d) 일 1회 저빈도** — 잡코리아·야놀자 판례의 ‘위험 구성요건’과 거리가 있습니다. 그럼에도 다음 원칙을 지켜야 위험이 최소화됩니다.

1. **robots.txt 사전 확인** — 모든 대상 도메인의 `/robots.txt`를 fetch하고, `Disallow`된 경로는 건드리지 않음.
2. **약관 검토** — 게임사 공식 사이트와 디시·아카는 “자동화된 수집/복제 금지” 또는 유사 조항이 약관에 있는 경우가 흔합니다. 발견 시 “요약·개인 알림용” 한정에 머무르고, **원문을 그대로 재배포하지 말 것**(LLM 요약본 + 원문 링크만 푸시).
3. **차단 우회 정도** — 단순 User-Agent 정상화는 일반적이지만, **VPN/프록시로 명시적 차단을 우회**하는 행위는 사람인 판례에서 위법성 가중 요소로 판단되었음. 게임사가 공식적으로 IP/지역 차단을 걸었다면 우회하지 말 것.
4. **요청 빈도/부담** — 동일 호스트당 동시 1, 1초 이상 간격, 일 1회 폴링이라면 “정상 사용자보다 적은 부하”로 해석될 수 있음.
5. **개인정보** — 글쓴이 닉네임, IP 끝자리(디시), 댓글 등 개인정보는 푸시 메시지에서 제거 또는 마스킹 권장.
6. **서비스 약관에 명시된 크롤링 금지/허용 신호 우선** — 예컨대 넥슨이 자체 Open API를 제공하는 영역(랭킹, 큐브)은 반드시 그 API를 쓰고, 공지사항처럼 API가 없는 부분만 HTML 폴링.

### 6-3. 한 줄 결론

> “공개된 페이지를 사용자처럼, 적은 빈도로, 본인 알림 목적으로만 가져와 LLM 요약 후 본인 디바이스에 푸시한다”면 형사 리스크는 사실상 없으며 민사 리스크도 매우 낮습니다. 다만 **차단 우회 + 영업적 재배포 + 고빈도 호출** 중 하나라도 추가되는 순간 위험 등급이 즉시 상승합니다.

---

## 7. 단계별 도입 로드맵 (무료 → 확장)

**Phase 1 — 무료/셀프호스팅 (월 0원~$5)**

- 게임사 공지: `httpx` + `BeautifulSoup` (또는 Jina Reader 1줄 변환으로 본문 정제)
- 디시인사이드: `dc_api`(Python async) 또는 `m.dcinside.com/api/gall_list.php` 직접 호출 (`User-Agent: dcinside.app`)
- 아카라이브: `requests`로 시도 → 403/Cloudflare 시 Playwright + stealth로 fallback. 5초 이상 간격.
- 새 글 감지: SQLite에 `(site, board, last_seen_id, last_seen_at)` 한 테이블
- 스케줄: cron 또는 GitHub Actions cron(일 1회)
- LLM 요약: OpenAI/Claude API + “모바일 푸시 1줄 + 원문 링크” 포맷
- 푸시: ntfy.sh, Pushbullet, 텔레그램 봇 — 모두 무료

**Phase 2 — 안정화 ($10~$50/월)**

- Playwright를 Browserbase 또는 단순 VPS(t4g.small급)로 분리
- 본문 정제는 Jina Reader 또는 Firecrawl `/scrape` 무료/저가 티어
- 한국 IP 필요 시 가벼운 한국 VPS 1대(2~5천원/월) 위에 봇 호스팅 — 프록시 비용 절약 효과

**Phase 3 — 차단 본격화 시 ($50~$200/월)**

- 아카라이브가 Cloudflare를 더 강화한다면 ScrapingBee Stealth 모드 또는 ScraperAPI Render+Stealth로 “아카라이브 전용 백엔드” 한정 사용
- 또는 Bright Data Web Unlocker (per-request) — 사용량이 적으니 PAYG 적합
- LLM 비용 최적화: 본문 길이 큰 글은 Jina로 마크다운화 → 토큰 절감 후 GPT-4.1-mini/Haiku 같은 저가 모델로 1차 요약

**Phase 4 — 다중 사용자/서비스화 ($200+/월)**

- Apify Actor로 “디시 갤러리 watcher” 액터 직접 작성·배포
- Bright Data 데이터셋/Web Scraper API로 SLA 보장
- Firecrawl `/crawl`로 게임사 전체 공지 사이트맵 일일 동기화 + 변경분만 LLM에 투입

---

## 부록: 즉시 사용 가능한 핵심 엔드포인트 치트시트

```
# 디시인사이드 (모바일 웹 API, 비공식)
GET https://m.dcinside.com/api/gall_list.php?id={갤러리}&page=1&app_id={base64앱ID}
헤더: User-Agent: dcinside.app
      Referer: http://www.dcinside.com

# 디시인사이드 (앱 API, 비공식 - 더 풍부한 정보)
GET http://app.dcinside.com/api/gall_list_new.php?id={갤러리}&page=1&app_id={base64앱ID}
GET http://app.dcinside.com/api/gall_view_new.php?id={갤러리}&no={글번호}&app_id={base64앱ID}
헤더 동일

# 아카라이브 (공식앱 내부 API, 비공식)
GET https://arca.live/api/app/list/channel/{채널명}
GET https://arca.live/api/app/view/article/{채널명}/{글번호}
※ Cloudflare에 막힐 수 있으므로 cf_clearance 쿠키가 있는 헤드리스 세션 필요

# 아카라이브 (일반 페이지, HTML 파싱)
GET https://arca.live/b/{채널명}            (목록)
GET https://arca.live/b/{채널명}/{글번호}    (글)

# 넥슨 메이플스토리 공식 Open API (공지 본문 X, 게임데이터 O)
https://openapi.nexon.com/  (인증키 발급 후 캐릭터/큐브/랭킹)

# 넥슨 통합 공지
https://notice.nexon.com/Notice/NoticeList
https://maplestory.nexon.com/News/Notice/Notice/{글번호}

# Jina Reader (무료 1줄 마크다운 변환)
GET https://r.jina.ai/https://maplestory.nexon.com/News/Notice/Notice/99837
```

이 치트시트와 Phase 1 무료 스택만으로 “하루 1회, 게임사 + 디시 + 아카라이브 신규 글 → LLM 요약 → 모바일 푸시” 파이프라인의 첫 동작 가능 버전을 한 주 안에 구축할 수 있고, 이후 차단 강도와 사용자 수에 따라 Phase 2~4로 단계적으로 확장하면 됩니다.