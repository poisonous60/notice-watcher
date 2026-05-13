# URL 유효성 검증 & 악성 URL 필터링 ― 디스코드 봇 probe 전단계 설계 가이드

**TL;DR**
- **결론**: probe 실행 전 필터링은 ① `urllib.parse` + `rfc3986`/`validators` 기반 구조 검증 → ② SSRF 차단(사설 IP/loopback resolve 차단) → ③ **Google Safe Browsing v4 무료 API**(비상업) 또는 상업적이면 **Google Web Risk Lookup**(10만 호출/월 무료) 단일 호출 → ④ HEAD 또는 32 KB Range GET으로 `Content-Type`·OG `og:type`·RSS auto-discovery 링크를 확인해 게시판/단건 판별 ― 이 4단 파이프라인이 비용·지연·정확도의 균형점이다.
- **상용 솔루션 선택**: 무료·저volume이면 Google Safe Browsing(비상업) 단독으로 충분하며, 상업 서비스라면 Web Risk Lookup이 사실상 표준이다. VirusTotal/urlscan.io/Cloudflare URL Scanner는 응답이 비동기(submit→poll)이고 분당 쿼터가 좁아 등록 시점 동기 필터로는 부적합하고, 백그라운드 deep-scan 큐로 두는 것이 맞다.
- **게시판/단건 판별의 한계**: 100 % 결정 가능한 휴리스틱은 없다. Open Graph `og:type=article`, RSS auto-discovery 링크 존재 여부, URL path/숫자 ID 패턴을 **신뢰도 점수로 합산**하고, 경계 케이스는 디스코드 봇에서 "정말 이 URL이 게시판 목록 페이지가 맞나요?" 재확인 메시지로 사용자 confirm을 받는 휴먼-인-더-루프 설계가 안전하다. 이는 Feedly/Inoreader가 RSS 등록 시 다중 후보 피드를 사용자에게 보여주는 방식과 같은 패턴이다.

---

## Key Findings

1. **URL 구조 검증의 사실상 표준은 `urllib.parse` + RFC 3986 보강이다.** Python 표준 `urlparse`는 형식 분해만 하고 유효성을 보장하지 않으므로, `rfc3986`의 `Validator()`(allow_schemes, allow_hosts, require_presence_of, forbid_use_of_password)나 `python-validators`의 `validators.url()`로 **scheme 화이트리스트(http/https만)**, host 존재, password 금지를 강제해야 한다. 단순 정규식 검증은 IDN·퍼센트 인코딩·IPv6 zone identifier(RFC 6874)에서 누락이 생긴다.

2. **Slack의 unfurling이 사실상의 산업 표준 콘텐츠 추출 절차**다. Slack은 사용자 입력 URL을 crawl할 때 응답을 **선행 32 KB만 fetch**하고(Facebook 512 KB, Twitter ~1 MB, LinkedIn 3 MB), oEmbed → Twitter Card → Open Graph → `<meta name="description">` 순으로 우선순위를 두며, 응답을 **글로벌하게 약 30분간 캐시**한다. Slack은 일부러 **robots.txt를 무시**하는데, "우리는 크롤러가 아니라 사용자를 대신해 한 번 요청하는 fetcher다"라는 입장이다. **bit.ly·t.co 등 URL 단축 서비스**는 입력 URL을 자체 안전 시스템(자체 blocklist + Google Safe Browsing류 추정)으로 1차 검사하고, 단축 URL 클릭 시 redirect 단계에서 한 번 더 검사하는 이중 구조다. **Notion**은 URL 임베드 시 oEmbed 프로토콜을 우선 시도하고, 실패하면 OG 메타로 fallback하는 동일한 패턴을 따른다.

3. **악성 URL API 4종 핵심 비교** (응답 속도·요금·rate limit 포함):

| 서비스 | 요금 | Rate limit | 응답 방식·지연 | 비고 |
|---|---|---|---|---|
| Google Safe Browsing v4 Lookup | 무료(비상업) | 기본 쿼터, 콘솔에서 증액 | **동기, 단일 HTTPS, p50 ≈ 100-300 ms** | v4는 deprecated 표시, v5 권장 |
| Google Web Risk Lookup | 10만 호출/월 무료, 이후 종량제 | 사실상 무제한(과금 기준) | **동기, p50 ≈ 100-300 ms** | 상업용. Safe Browsing과 동일 인텔리전스 |
| VirusTotal v3 (Public) | 무료(비상업) | **4 req/min, 500 req/day** | URL 조회는 동기(캐시 hit ≈ 200 ms), 신규 제출은 **비동기 분석 30 s ~ 수 분** | 70+ 엔진 합산. 디스코드 봇 동기 경로엔 부적합 |
| Cloudflare URL Scanner v2 | 무료(계정 필요), Enterprise 기능 유료 | account quota, bulk 최대 100 URL | **비동기, submit→poll, 보통 10-30 s** | 스크린샷·HAR·verdict 제공, 데이터 12개월 보관 |
| urlscan.io | 무료(가입 필요) | 분/시간/일 quota, 429 헤더로 잔여량 | **비동기, 보통 10-30 s** | 무료 사용자는 검색 기능 일부 제한 |
| PhishTank | 무료 (Cisco Talos) | 시간당 제한, 509 응답 | 동기 lookup | **2020년 이후 신규 가입 중단, 2026 현재도 중단 — 사실상 통합 불가** |
| Microsoft SmartScreen | – | – | – | **공식 외부 API 없음**. Microsoft Q&A 답변에서 명시적으로 부정. Defender for Endpoint 라이선스 내부에서만 간접 사용 |
| IPQualityScore Malicious URL | 무료 5,000 lookup/월(공유 풀) | 플랜별 | **동기, p50 ≈ 200-500 ms** | risk_score, phishing/malware bool, 70+ 카테고리 |

   동기·저지연이 필요한 디스코드 봇의 "등록 시점 차단" 경로에는 **Safe Browsing/Web Risk/IPQS**만 적합하다. VirusTotal·Cloudflare·urlscan.io는 비동기 큐로 이관하는 것이 정공법.

4. **PhishTank는 실질적으로 막혔다.** Cisco Talos가 운영하며 무료이지만 2020년 이후 신규 사용자 등록이 중단되었고 위키피디아·공식 FAQ에 따르면 "as of 2026, new user registration remains closed". 신규 통합은 사실상 불가능하므로 후보에서 제외.

5. **Microsoft SmartScreen은 공개 API가 없다.** Microsoft Q&A 공식 답변에서 "it seems there is no such API"로 확인된다. Edge가 내부적으로 `https://nav.smartscreen.microsoft.com/...` 등을 호출하지만 외부 개발자가 합법적으로 쓸 수 있는 엔드포인트가 아니다.

6. **게시판 vs 단건 글 판별은 단일 신호로는 불가능하다.** 실무에서는 ① **path 휴리스틱**(`/board/`, `/list/`, `/category/` vs `/post/{id}`, `/article/{id}`), ② **query string 패턴**(`?page=1`, `?bbsNo=` 같은 페이징 파라미터), ③ **Open Graph `og:type`**(`article`이면 단건 신호, `website`/누락이면 목록 가능성), ④ **RSS auto-discovery** (`<link rel="alternate" type="application/rss+xml">`가 있다면 사실상 목록형 콘텐츠가 있다는 강한 증거), ⑤ **DOM 신호**(반복되는 `<article>`/`<li>`/카드 5개 이상)를 가중치 합산한다. MediaCloud 같은 미디어 모니터링 프로젝트는 사이트별 수작업 휴리스틱 + 결정 트리 분류기 조합으로 실제 운영한다.

7. **웹 아카이브 서비스의 콘텐츠 타입 판별**: Internet Archive Wayback Machine은 capture 시점에 HTTP 응답 헤더의 `Content-Type`을 그대로 보존(`text/html`, `application/pdf` 등)하고, CDX API의 `mimetype` 필드로 노출한다. 즉 **첫 응답의 `Content-Type` 헤더가 가장 기본적이고 권위 있는 콘텐츠 타입 식별자**이며, 어떤 발견적 휴리스틱보다 우선해야 한다. 다만 일부 사이트가 `application/octet-stream`을 잘못 반환하기도 하므로, 헤더와 file signature(매직 바이트)를 함께 보는 것이 견고하다.

8. **RSS 구독 서비스(Feedly/Inoreader)의 등록 파이프라인**은 사실상 표준화되어 있다. 입력 URL이 들어오면 ① 응답 `Content-Type`이 `application/rss+xml`/`atom+xml`이면 그대로 채택, ② HTML이면 `<link rel="alternate" type="application/rss+xml">`/`type="application/atom+xml">` 태그를 검색(**RSS auto-discovery**), ③ 그래도 없으면 `/feed`, `/rss`, `/atom.xml` 같은 흔한 경로를 시도, ④ 여러 후보가 발견되면 사용자에게 선택지를 제시. Inoreader/Feedly가 다중 피드를 보여주는 이유다. **게시판 등록 봇도 동일한 다중 후보 노출 UX가 가장 견고하다.**

9. **Discord/Telegram 봇의 URL 검증 패턴**(오픈소스 봇 분석 종합): ① 메시지 내 URL 추출은 regex가 아니라 Discord/Telegram이 메시지 객체에 첨부하는 entities(`MessageEntity.URL`, Discord embed URL 필드)를 우선 사용. ② 모더레이션 봇(MEE6, Wick, Carl-bot, NotSoBot 등)은 자체 blocklist + Google Safe Browsing 또는 phishlist(Discord 본사가 운영하는 안티-피싱 리스트, 게시 URL: `https://phish.sinking.yachts/v2/all` 같은 커뮤니티 미러)로 1차 점검. ③ 봇이 직접 URL을 fetch하는 경우 반드시 SSRF 보호(사설 IP 차단), 응답 크기 제한(보통 1-5 MB), redirect 횟수 제한(보통 5회 이하)을 둔다.

10. **Zapier/Make(Integromat)의 웹훅·URL 입력 validation 패턴**: 사용자 시나리오에서 URL을 입력받을 때 ① 형식 검증(브라우저 URL 입력 필드와 동일한 HTML5 `type=url` 패턴), ② 호출 시점에 timeout(Zapier 30 s, Make 40 s), ③ 응답 크기 제한(Zapier는 webhook 응답 본문 6 MB), ④ retry with exponential backoff, ⑤ 결과 JSON 파싱 실패 시 raw 텍스트 fallback. **악성 URL 차단은 명시적으로 하지 않으며**, 대신 플랫폼 차원에서 abuse report 시 호출자 계정을 정지시키는 reactive 정책이다. 디스코드 봇이 사용자 입력 URL을 **자신의 서버에서** crawling하는 경우엔 이 reactive 모델로 부족하므로 proactive 차단(Safe Browsing 등)이 반드시 필요하다.

11. **차단해야 할 플랫폼(YouTube/SNS/파일 직링)은 호스트 화이트·블랙리스트가 가장 단순하고 견고하다.** SNS/YouTube 차단은 hostname suffix 매칭(`youtube.com`, `youtu.be`, `twitter.com`, `x.com`, `instagram.com`, `facebook.com`, `tiktok.com` 등)으로 처리하고, 파일 직링은 ① path 확장자(`.pdf`, `.zip`, `.jpg`, ...) ② HEAD 응답의 `Content-Type`이 `text/html`이 아닌 경우로 거른다.

12. **SSRF는 디스코드 봇의 실질적 위협이다.** 사용자가 `http://169.254.169.254/`(AWS metadata), `http://localhost:6379`, `http://10.0.0.1`을 입력하면 봇이 내부망에 요청을 보낸다. URL 검증 후 **DNS 해석을 직접 수행해 결과 IP가 private/loopback/link-local/multicast/reserved 대역이면 거부**해야 한다. `ipaddress` 모듈의 `is_private/is_loopback/is_link_local/is_reserved` 속성으로 한 번에 검사 가능하다.

13. **캐싱이 비용을 결정한다.** Slack은 unfurl 결과를 ~30분 글로벌 캐싱한다. 디스코드 봇도 동일 hostname에 대한 Safe Browsing/Web Risk 결과를 최소 1시간, 동일 정확 URL은 최소 24시간 Redis/SQLite에 캐싱해야 free-tier 안에서 운영 가능하다.

---

## Details

### 1. URL 형식 검증

**표준과 라이브러리 비교**

| 라이브러리 | 용도 | 특징 |
|---|---|---|
| `urllib.parse` (stdlib) | 분해만 | 검증 없음, 빈 host도 통과 |
| `validators` (python-validators) | 검증 boolean | dperini 정규식 기반, RFC 3986 fragment 검사 |
| `rfc3986` | 검증·구성 | `Validator()` 객체로 scheme/host/password 정책 강제, RFC 6874(IPv6 zone) 지원 |
| `yarl` | URL 객체 모델 | aiohttp와 친화적, encoding 안전 |
| `rfc3987` | IRI 지원 | GPL이라 라이선스 주의 |

**프로덕션용 검증 함수 (권장 구현)**

```python
import ipaddress
import socket
from urllib.parse import urlparse
from rfc3986 import uri_reference, validators

BLOCKED_HOSTS_SUFFIX = (
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "instagram.com", "facebook.com", "fb.com",
    "tiktok.com", "threads.net", "linkedin.com",
)
BINARY_EXT = (".pdf", ".zip", ".rar", ".7z", ".exe", ".dmg",
              ".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".gif", ".webp")

_validator = (validators.Validator()
              .allow_schemes("http", "https")
              .require_presence_of("scheme", "host")
              .forbid_use_of_password())

def validate_structure(url: str) -> tuple[bool, str]:
    try:
        _validator.validate(uri_reference(url))
    except Exception as e:
        return False, f"malformed: {e}"

    p = urlparse(url)
    host = (p.hostname or "").lower()

    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS_SUFFIX):
        return False, "blocked_platform"

    if p.path.lower().endswith(BINARY_EXT):
        return False, "binary_file"

    # SSRF 차단
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False, f"ssrf_blocked:{ip}"
    except socket.gaierror:
        return False, "dns_failed"

    return True, "ok"
```

**Slack/Notion/bit.ly 등의 실제 동작 요약**: bit.ly·TinyURL·t.co 같은 단축 서비스는 (1) 입력 시점에 형식 검증, (2) 자체 reputation DB + Safe Browsing류로 점검, (3) 단축 URL 클릭 시 redirect 단계에서 한 번 더 확인하는 이중 구조다. **Notion**과 **Confluence**는 임베드 시 oEmbed 프로토콜(`/oembed?url=...`)을 우선 시도하고 실패 시 OG fallback, 응답이 HTML이 아니면 단순 링크로만 표시한다. 공통적으로 **"전체 페이지를 다운받지 않는다"**(Range 헤더 또는 첫 N KB만 사용)는 점이 핵심 비용·보안 최적화다.

### 2. 악성 URL 탐지 상용 API 상세

#### Google Safe Browsing v4 (Lookup API)

- **요금**: 완전 무료. "All use of Safe Browsing APIs is free of charge"(developers.google.com/safe-browsing/v4/pricing).
- **라이선스**: **비상업 한정**("not for sale or revenue generating purposes"). 광고/구독 수익이 있으면 Web Risk로.
- **상태**: 공식적으로 deprecated, v5 마이그레이션 권고.
- **응답 속도**: 동기 HTTPS POST 1회, 글로벌 edge 캐시로 p50 ~100-300 ms 수준.

```python
import requests
GSB_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

def check_safe_browsing(url: str, api_key: str) -> bool:
    body = {
        "client": {"clientId": "my-discord-bot", "clientVersion": "1.0.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING",
                            "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    r = requests.post(GSB_URL, params={"key": api_key},
                      json=body, timeout=5)
    r.raise_for_status()
    return not r.json().get("matches")   # matches 비면 safe
```

#### Google Web Risk (상업용)

- **요금**: Lookup `uris.search` **월 10만 호출 무료**, 이후 SKU별 종량제. `threatLists.computeDiff`(Update API) 무제한 무료. Submission API는 영업 문의.
- **동작·응답 속도는 Safe Browsing과 동등**. 호출 코드도 거의 동일(엔드포인트만 `webrisk.googleapis.com`).

#### VirusTotal Public API v3

- **요금**: 무료. **상업용·신규 정보 미기여 워크플로 금지** 명시.
- **Rate limit**: **4 req/min, 500 req/day** (공식 docs.virustotal.com).
- **응답 속도**: 이미 분석된 URL은 GET `/api/v3/urls/{base64url}`로 200 ms 내. **신규 제출은 비동기**(`/urls` POST → analysis_id → `/analyses/{id}` poll, 30 s ~ 수 분).

```python
import base64, requests
def vt_check(url: str, api_key: str) -> dict:
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    r = requests.get(
        f"https://www.virustotal.com/api/v3/urls/{url_id}",
        headers={"x-apikey": api_key}, timeout=5)
    if r.status_code == 404:
        requests.post("https://www.virustotal.com/api/v3/urls",
                      headers={"x-apikey": api_key},
                      data={"url": url}, timeout=5)
        return {"status": "submitted"}
    stats = r.json()["data"]["attributes"]["last_analysis_stats"]
    return {"malicious": stats["malicious"], "suspicious": stats["suspicious"]}
```

#### Cloudflare URL Scanner v2

- **요금**: 무료(계정+토큰 필요), Enterprise 기능(지역 스캔) 유료.
- **Rate limit**: account quota, bulk 한 번에 최대 100 URL, bulk는 우선순위 낮음.
- **응답 속도**: **완전 비동기** — submit → UUID → `/v2/result/{scan_id}` poll(보통 10-30 s).
- 성공 스캔 12개월 보관, 실패 30일.

```python
import requests, time
def cf_scan(url, account_id, token):
    base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/urlscanner/v2"
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    uuid = requests.post(f"{base}/scan",
        json={"url": url, "visibility": "unlisted"}, headers=h,
        timeout=10).json()["uuid"]
    for _ in range(30):
        time.sleep(2)
        r = requests.get(f"{base}/result/{uuid}", headers=h)
        if r.status_code == 200:
            return r.json()["verdicts"]["overall"]   # {"malicious": bool, ...}
    return None
```

#### urlscan.io

- **요금**: 무료 가입 시 분/시간/일 quota. 초과 시 HTTP 429 + `X-Rate-Limit-Limit/Remaining/Reset` 헤더 반환.
- **응답 속도**: 비동기, 10-30 s.
- 무료 사용자는 regex 검색 등 일부 기능 제한.

```python
import requests
def urlscan_submit(url, api_key):
    r = requests.post("https://urlscan.io/api/v1/scan/",
        headers={"API-Key": api_key, "Content-Type": "application/json"},
        json={"url": url, "visibility": "unlisted"}, timeout=10)
    if r.status_code == 429:
        return {"throttled": True, "reset": r.headers.get("X-Rate-Limit-Reset")}
    return r.json()   # uuid, api(result URL)
```

#### PhishTank — 신규 통합 불가

운영자 Cisco Talos. 위키피디아 기준 **"as of 2026, new user registration remains closed"**. 기존 키 보유자만 사용 가능. **후보에서 제외**.

#### Microsoft SmartScreen — 공개 API 없음

Microsoft Q&A 공식 답변: "it seems there is no such API." Defender for Endpoint 라이선스 내부에서만 간접 활용 가능. **후보에서 제외**.

#### IPQualityScore (Malicious URL Scanner)

- **요금**: 무료 **5,000 lookup/month** (Proxy/Email/Device와 공유). 유료 월 단위.
- **응답 필드**: `risk_score`(0~100), `phishing`, `malware`, `parking`, `suspicious`, `domain_age`, `category`(70+ 분류). 카테고리는 게시판 식별 보조 신호로도 쓸 수 있다.
- **응답 속도**: 동기 200-500 ms.

```python
import urllib.parse, requests
def ipqs_check(url, key):
    enc = urllib.parse.quote(url, safe="")
    r = requests.get(
        f"https://www.ipqualityscore.com/api/json/url/{key}/{enc}",
        timeout=5).json()
    return {
        "risk": r["risk_score"],
        "phishing": r["phishing"],
        "malware": r["malware"],
        "category": r.get("category"),
    }
```

### 3. 게시판 목록 vs 단건 글 URL 판별

**휴리스틱별 권장 가중치**

| 신호 | 게시판 목록 | 단건 글 |
|---|---|---|
| path `/list`, `/board`, `/forum`, `/category`, `/topics`, `/posts` | +높음 | – |
| path 마지막이 숫자 ID (`/12345`, `/view?no=42`) | – | +높음 |
| query `page`, `pageNum`, `bbsNo`, `boardId` | +높음 | – |
| `og:type` = `article` | – | +매우높음 |
| `og:type` = `website` 또는 누락 | +약함 | 중립 |
| `<link rel="alternate" type="application/rss+xml">` 존재 | +매우높음 | 중립 |
| HTML 내 `<article>`/카드 반복 5개 이상 | +높음 | – |
| URL slug에 긴 한글/영문 단어 4개 이상 | – | +높음 |
| HEAD `Content-Type` ≠ `text/html` | reject (둘 다 아님) | |

**웹 아카이브가 콘텐츠 타입을 식별하는 방식**: Internet Archive Wayback Machine은 capture 시점의 HTTP `Content-Type` 헤더를 그대로 보존하고 CDX API의 `mimetype` 필드로 노출한다. 즉 **첫 응답 헤더가 가장 권위 있는 신호**이며, 휴리스틱은 그 위에서만 의미가 있다. 일부 잘못된 서버가 `application/octet-stream`을 반환하는 케이스를 위해 응답 본문 첫 512 bytes의 file signature(매직 바이트, 예: `<!DOCTYPE`/`<html`) 검사로 보강하는 것이 견고하다.

**RSS auto-discovery 활용**: 게시판/블로그는 관례적으로 `<head>`에 RSS 링크를 광고한다. 이 태그 발견은 사실상 "이 페이지가 목록형 콘텐츠를 가진다"는 매우 강한 증거다.

```html
<link rel="alternate" type="application/rss+xml" href="/feed.xml" title="RSS Feed">
<link rel="alternate" type="application/atom+xml" href="/feed.atom">
```

**구현 예시 (probe 전 경량 분류기)**

```python
import re, requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

SINGLE_PATH_RE = re.compile(r"/(post|article|view|read|news|story|content|item)s?/\d+", re.I)
LIST_PATH_RE   = re.compile(r"/(board|list|forum|category|topics|posts|articles|notice|gallery|community)(/|$)", re.I)
LIST_QUERY_KEYS = {"page", "pagenum", "pageno", "p", "bbsno", "boardid", "page_id"}

def classify(url: str) -> dict:
    score_list, score_single = 0, 0
    p = urlparse(url)

    if SINGLE_PATH_RE.search(p.path): score_single += 3
    if LIST_PATH_RE.search(p.path):   score_list   += 2

    qkeys = {k.lower() for k in parse_qs(p.query).keys()}
    if qkeys & LIST_QUERY_KEYS: score_list += 2

    last = p.path.rstrip("/").rsplit("/", 1)[-1]
    if last.isdigit() and len(last) >= 3: score_single += 2

    # Slack과 같은 32 KB Range GET
    try:
        r = requests.get(url, headers={"Range": "bytes=0-32767",
                                       "User-Agent": "MyBoardBot/1.0 (+contact)"},
                         timeout=4, allow_redirects=True)
        if not r.headers.get("Content-Type", "").startswith("text/html"):
            return {"verdict": "non_html"}
        soup = BeautifulSoup(r.text, "html.parser")

        og_type = (soup.find("meta", property="og:type") or {}).get("content", "")
        if og_type == "article":      score_single += 3
        elif og_type in ("website", "blog", ""): score_list += 1

        if soup.find("link", rel=lambda v: v and "alternate" in v,
                     type=re.compile(r"application/(rss|atom)\+xml")):
            score_list += 3

        if len(soup.find_all("article")) >= 5: score_list += 2
    except Exception:
        pass

    if score_single - score_list >= 2: return {"verdict": "single_article"}
    if score_list - score_single >= 2: return {"verdict": "list_page"}
    return {"verdict": "ambiguous"}
```

### 4. 실서비스 적용 사례 패턴 비교

#### Discord/Telegram 봇

- **URL 추출**: regex가 아니라 메시지 객체의 entities(`Message.embeds`, `Message.content` 파싱 시 Discord가 자동으로 인식한 링크, Telegram `MessageEntity` 타입 `URL`/`TEXT_LINK`) 우선.
- **모더레이션 봇**(MEE6, Wick, Carl-bot, NotSoBot 류): ① 자체 도메인 blocklist, ② 커뮤니티 anti-phish 리스트(예: `phish.sinking.yachts` 공개 리스트, Discord 안티-스캠 봇들이 표준으로 사용), ③ 옵션으로 Safe Browsing/VirusTotal 연동.
- **봇이 직접 URL을 fetch할 때 공통 패턴**: SSRF 보호(사설 IP 차단), 응답 크기 제한(1-5 MB), redirect 횟수 제한(보통 5), timeout 5-10 s.

#### RSS 구독 서비스(Feedly/Inoreader)

피드 추가 시의 사실상 표준 흐름:
1. 입력 URL에 GET 요청, `Content-Type` 확인.
2. `application/rss+xml`/`application/atom+xml`/`application/feed+json`이면 그대로 채택.
3. `text/html`이면 `<link rel="alternate" type="application/rss+xml">` / `application/atom+xml` 자동 발견(RFC 5005/관례).
4. 미발견 시 `/feed`, `/rss`, `/atom.xml`, `/index.xml` 등 흔한 경로 시도.
5. 여러 후보 발견 시 **사용자에게 다중 선택지 노출**(예: "이 사이트에서 5개 피드를 찾았어요").

→ **본 봇도 동일하게 다중 후보 노출 UX를 채택하면 ambiguous 케이스를 자연스럽게 처리**할 수 있다.

#### 웹훅 서비스(Zapier/Make)

- 사용자 정의 URL 입력 시: ① HTML5 URL 패턴 기반 형식 검증, ② 호출 시점 timeout(Zapier 30 s, Make 40 s), ③ 응답 크기 제한(Zapier webhook 응답 6 MB), ④ retry with exponential backoff, ⑤ JSON 파싱 실패 시 raw text fallback.
- **악성 URL 차단은 명시적으로 하지 않는다.** Reactive 모델(abuse report → 호출자 계정 정지). 디스코드 봇은 **자기 서버에서 직접 crawling**하므로 이 reactive 모델로는 부족하며 Safe Browsing류 proactive 차단이 필수다.

### 5. 권장 종합 파이프라인 (probe 전단)

```
사용자 입력 URL
   │
   ▼
[Stage 1] 구조 검증 (urllib.parse + rfc3986 Validator)
   ├ scheme ∈ {http, https}?
   ├ host 존재?
   ├ password 없음?
   └ malformed면 즉시 reject
   │
   ▼
[Stage 2] 정책 필터
   ├ hostname suffix 블랙리스트 (YouTube/SNS) → reject
   ├ 확장자 블랙리스트 (.pdf/.zip/...) → reject
   └ DNS resolve → private/loopback/link-local IP → reject (SSRF)
   │
   ▼
[Stage 3] 캐시 조회 (Redis: hash(url) → 24h 캐시)
   │
   ▼
[Stage 4] 악성 URL 검사 (Safe Browsing 1회 동기 호출)
   └ matches 있으면 즉시 reject + 로깅
   │
   ▼
[Stage 5] 콘텐츠 타입 판별 (32 KB Range GET)
   ├ Content-Type ≠ text/html → reject
   ├ og:type=article + RSS link 없음 → "단건 글로 보입니다" reject
   ├ RSS link 있음 또는 다중 <article> → 통과
   └ ambiguous → 봇이 사용자에게 confirm/다중 후보 제시
   │
   ▼
[Stage 6] (선택) 비동기 deep-scan
   └ Cloudflare URL Scanner 또는 VirusTotal 큐에 제출,
     결과 malicious면 등록 취소 + 사용자 알림
   │
   ▼
probe(크롤링 분석) 진행
```

**비용 시뮬레이션** (Stage 4 Safe Browsing 무료, 캐시 hit rate 70 % 가정):
- 일 1,000 URL 등록 → 외부 호출 300건/일 → 월 9,000건 ≪ 무료 한도.
- 상업화 후 Web Risk 종량제 전환해도 월 10만 무료 한도 안.

---

## Recommendations

**즉시(1주 내) 적용**
1. `urllib.parse` + `rfc3986.validators.Validator()`로 Stage 1·2 구현. scheme 화이트리스트는 `{"http", "https"}`만. password 금지, host 필수.
2. `ipaddress.ip_address(...).is_private/is_loopback/is_link_local/is_reserved`로 SSRF 차단. `socket.getaddrinfo()`로 모든 A/AAAA 레코드를 검사.
3. hostname suffix 블랙리스트(YouTube/SNS/주요 파일호스팅)와 확장자 블랙리스트를 봇 설정 파일로 외부화.

**1차 출시(2~3주)**
4. **Google Safe Browsing v4 Lookup API**로 시작. 비상업이면 무료 한도로 충분. 응답을 Redis에 hostname 단위 1시간 + 정확 URL 단위 24시간 캐싱.
5. Stage 5의 32 KB Range GET + BeautifulSoup OG/RSS 파싱 구현. User-Agent에 봇 식별자(`MyBoardBot/1.0 (+contact)`) 명시.
6. ambiguous 케이스에서 디스코드 봇이 Feedly 스타일의 **다중 후보 선택 UX** 또는 "이 URL이 게시판 목록 페이지가 맞나요? (Y/N)" 버튼 제시.

**스케일/상업화 단계(2개월+)**
7. 유료화/광고 도입 즉시 **Web Risk Lookup**으로 마이그레이션(엔드포인트만 교체).
8. 비동기 deep-scan으로 **Cloudflare URL Scanner**(무료) 또는 **VirusTotal**(4 req/min·500/day)를 큐(Celery/RQ)로 추가. 사용자 응답을 막지 않고 백그라운드에서 비판정 시 retro-active 차단.
9. 게시판 분류기를 결정 트리/소규모 ML로 진화. MediaCloud처럼 사이트별 수작업 휴리스틱 패턴을 settings에 누적하면 한국 주요 커뮤니티(디시·뽐뿌·클리앙·루리웹 등) 정확도가 빠르게 올라간다.

**판단 임계값(언제 다음 단계로 가야 하나)**
- Safe Browsing 호출량이 일 10,000건 이상 지속 → 캐시 hit rate 점검, 그래도 한도 위협 시 Web Risk(유료 종량제) 전환.
- ambiguous 비율이 30 % 이상 → 분류기 보강 또는 사용자 confirm UX 개선.
- 등록 후 retro-active malicious 판정이 주 5건 이상 → 비동기 deep-scan(Cloudflare/VirusTotal) 도입.

---

## Caveats

- **Safe Browsing v4 deprecation**: 공식 문서에 deprecation 경고가 있다. v5 또는 Web Risk 마이그레이션 일정을 처음부터 코드에 추상화 레이어로 둘 것.
- **VirusTotal/urlscan.io 라이선스**: 두 곳 모두 "비상업 한정" 또는 "신규 파일/URL 기여" 같은 조건. 상업화 시점에 반드시 라이선스 재검토.
- **Slack의 robots.txt 무시**는 그들의 정책 선택이며, 일반 봇이 그대로 따라하면 사이트 운영자와 마찰이 생긴다. 본 가이드의 32 KB Range GET 패턴은 **User-Agent 식별 + robots.txt 존중**으로 운영하는 것을 권장.
- **PhishTank, SmartScreen은 사실상 사용 불가**(전자는 신규 가입 중단, 후자는 공식 API 부재). 인터넷 자료에서 "추천"으로 묶여 등장하지만 2026년 현재 신규 통합 대상이 아니다.
- **게시판/단건 판별은 본질적으로 휴리스틱**이라 100 % 정확도는 불가능하다. False negative와 false positive를 모두 안전하게 회복할 수 있는 다중 후보 노출/사용자 confirm UX가 필수.
- **DNS rebinding**: SSRF 차단을 `getaddrinfo` 한 번으로 끝내면, 동일 hostname이 첫 검증 시 공인 IP를 반환했다가 실제 fetch 시 사설 IP를 반환하는 공격은 막을 수 없다. fetch 시점에도 connect 후 peer IP를 재검증하거나 IP-pinning을 적용할 것.
- **일부 수치**(Slack 30분 캐싱, fetch 32 KB, Safe Browsing 응답 p50)는 Slack 개발자 블로그 및 외부 분석가 측정에서 인용한 것이며 공식 SLA로 보장된 값은 아니다. Cloudflare/VirusTotal·urlscan.io의 비동기 응답 시간(10-30 s)도 일반적 관측치이며 큐 적체에 따라 변동될 수 있다. 운영 환경에 맞춰 보수적으로 설계할 것.