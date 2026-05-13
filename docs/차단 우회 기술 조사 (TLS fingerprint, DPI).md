# 차단 우회 기술 조사 — TLS fingerprint / HTTP2 fingerprint / DPI

Playwright stealth 로도 통과하지 못하는 사이트를 만났을 때 시도해볼 수 있는 기술들을 조사한다. **본 문서는 조사·교육 목적이며, 실제 도입 여부는 별도 판단**. [크롤링 지침.md](크롤링%20지침.md) 의 "차단 우회 직접 시도 금지 (사람인 판례)" 와 충돌할 수 있다.

---

## 0. 전제: 차단은 3개 계층에서 일어난다

Playwright 가 막혔다 = 막힘의 원인을 먼저 분리해야 한다. 원인이 어느 계층이냐에 따라 도구가 완전히 다르다.

| 계층 | 차단 주체 | 증상 | 해결 도구 |
|---|---|---|---|
| **L7 — 봇 탐지** | 사이트 (Cloudflare/DataDome/Akamai) | 200 OK 인데 "Just a moment...", captcha, 빈 본문 | TLS/HTTP2 fingerprint 위장 (webclaw, curl_cffi) |
| **L4 — 네트워크 DPI** | ISP / 국가 방화벽 | TCP handshake timeout, RST, SNI 검사로 끊김 | GoodbyeDPI, Zapret, ESNI/ECH |
| **L3 — IP/지역** | 사이트 또는 ISP | 한국 IP 만 거부, 지역 블록 | 프록시, residential IP, VPN |

세 계층은 **독립적**이다. webclaw 의 fingerprint 위장은 L7 만 다루고, GoodbyeDPI 는 L4 만 다룬다. 둘은 서로의 문제를 풀 수 없다.

게임 공지/디시/아카 같은 본 프로젝트의 타깃 사이트는 거의 전부 **L7 문제** (Cloudflare 등) 이다. L4 DPI 가 문제되는 건 한국에서 https-warning 차단 (성인/도박/저작권) 정도이며, 본 프로젝트와 거리가 있다.

---

## 1. Layer 7 — TLS fingerprint (JA3/JA4) 위장

### 1-1. 원리

TLS handshake 의 첫 패킷 `ClientHello` 에는 다음이 노출된다:
- TLS version
- cipher suite 목록과 **순서**
- extension 목록과 **순서**
- elliptic curves, signature algorithms, ALPN

이 값들의 조합을 hash 한 게 **JA3 fingerprint**, 개선판이 **JA4** ([JA3/JA4 설명 — Scrapfly](https://scrapfly.io/web-scraping-tools/ja3-fingerprint), [TLS Fingerprinting — ProxyHat](https://proxyhat.com/blog/tls-fingerprinting-explained)).

핵심: **`User-Agent` 헤더가 "Chrome 124" 라고 주장해도, ClientHello 가 Python `requests`/`httpx` 의 OpenSSL 서명을 가지면 즉시 봇으로 판별된다.** TLS 는 HTTP 보다 *먼저* 일어나고 JS 보다 *훨씬* 먼저 일어나므로, 헤더 위조나 stealth.js 로는 손댈 수 없다 ([Rayobyte](https://rayobyte.com/blog/tls-fingerprinting/)).

### 1-2. webclaw 의 방식

[webclaw](https://github.com/0xMassi/webclaw) 는 `wreq` + `boring-sys2` (BoringSSL = Chrome 의 TLS stack) 를 써서 **Rust 안에서 직접 Chrome ClientHello 를 재생** 한다. 추가로 HTTP/2 layer (다음 절) 까지 위조.

단 webclaw 자체 README 도 *"bot 보호 사이트는 cloud API 사용"* 이라고 명시 — self-hosted 바이너리만으로는 모든 Cloudflare 사이트를 통과하지 못한다는 뜻.

### 1-3. Python 에서 쓸 수 있는 도구

본 프로젝트는 Python 스택이므로 Rust 의 `wreq` 를 그대로는 못 쓴다. Python 대안:

| 도구 | 방식 | 특징 |
|---|---|---|
| **[curl_cffi](https://github.com/lexiforest/curl_cffi)** | curl-impersonate fork 의 Python binding | Chrome/Firefox/Edge 의 JA3·HTTP2·akamai fingerprint 모두 위조. `requests` API 호환. **현실적으로 가장 강력** |
| **curl-impersonate** | C 바이너리 | 위 도구의 backend. CLI 로 직접 실행도 가능 |
| **tls-client (Python)** | Go 의 utls 를 wrapping | Chrome/Safari fingerprint 위조 |

**JA3 vs JA4 주의** ([proxies.sx 2026 가이드](https://www.proxies.sx/use-cases/privacy/tls-fingerprint)): Chrome 110+ 은 TLS extension 순서를 매번 randomize 하므로 JA3 hash 가 매번 바뀐다. 모던 사이트는 JA4 (extension 정렬 후 hash) 를 쓰며, JA4 위조는 라이브러리가 자동으로 처리.

### 1-4. 무엇을 막을 수 있나

| 보호 시스템 | TLS fingerprint 위조만으로 통과? |
|---|---|
| Cloudflare (basic) | 대체로 ○ |
| Cloudflare Turnstile/JS challenge | △ — JS 실행 필요 → Playwright 와 결합 |
| DataDome | △ — behavioral signal 도 봄 |
| PerimeterX | × — JS 핑거프린팅 비중 높음 |
| Akamai Bot Manager | × — JS sensor data 필수 |
| reCAPTCHA / hCaptcha | × — 별도 captcha solver 필요 |

**즉, fingerprint 위조 ≠ 만능**. JS 기반 챌린지가 있으면 Playwright 가 여전히 필요하고, 그때는 Playwright 를 patched Chromium 으로 띄워 fingerprint 까지 일치시키는 조합 (`undetected-chromedriver`, `rebrowser-patches`, Playwright 의 `chrome` channel) 이 쓰인다.

---

## 2. Layer 7 — HTTP/2 fingerprint

JA3/JA4 가 통과돼도, **HTTP/2 frame 패턴** 으로 또 한 번 분류한다 ([Akamai HTTP/2 fingerprinting 정리 — fluxzy](https://www.fluxzy.io/resources/blogs/impersonate-network-fingerprint)).

검사 항목:
- `SETTINGS` frame 의 파라미터 값과 순서
- `WINDOW_UPDATE` 초기 크기
- `HEADERS` frame 의 pseudo-header 순서 (`:method`, `:authority`, `:scheme`, `:path`)
- `PRIORITY` frame 패턴

Python `httpx` (h2 라이브러리) 와 Chrome 은 이 패턴이 다르다. curl_cffi 가 이 영역까지 같이 위조해주므로 별도 도구는 보통 필요 없음.

---

## 3. Layer 4 — DPI 우회 (GoodbyeDPI 등)

### 3-1. 어떤 문제를 푸는가

ISP 또는 국가 방화벽이 패킷을 들여다보고 (Deep Packet Inspection) **TLS ClientHello 의 SNI 필드** 를 읽어서 도메인을 보고 끊는 케이스. 한국에서는 https warning 페이지 (성인/도박/저작권 차단) 가 이 방식. 러시아/이란/중국에서는 광범위한 사이트 차단의 주력.

이건 사이트의 봇 탐지와 **무관**하다. TCP handshake 자체가 ISP 단에서 끊긴다.

### 3-2. GoodbyeDPI 원리

[ValdikSS/GoodbyeDPI](https://github.com/ValdikSS/GoodbyeDPI) ([Wikipedia](https://en.wikipedia.org/wiki/GoodbyeDPI)) — Windows 전용 (WinDivert 드라이버), Linux 는 [wickstudio/GoodbyeDPI-Linux](https://github.com/wickstudio/GoodbyeDPI-Linux) 포팅 또는 Zapret.

기법:
1. **TCP fragmentation**: ClientHello 를 작은 조각으로 쪼개 보냄 → DPI 가 SNI 를 재조립 못함.
2. **Reverse fragmentation**: 조각을 역순으로 보내서 segmented TLS 를 못 다루는 DPI 통과.
3. **Fake packets with low TTL**: ISP 의 DPI box 까지만 도달하고 만료되는 가짜 패킷을 섞어서 DPI 를 혼란시킴. 진짜 패킷은 그대로 도달.
4. **TCP checksum/seq 변조**: DPI 는 거부, 진짜 서버는 무시하는 invalid 패킷.

### 3-3. 본 프로젝트와의 관련성

**거의 없다.** 타깃 사이트 (gryphline.com, dcinside.com, arca.live) 는 한국에서 정상 접속된다. DPI 우회가 의미 있는 경우는:
- 일본/중국 게임사 사이트가 한국 ISP 단에서 지연·차단되는 경우
- 추후 .onion 또는 IP 차단된 사이트로 확장하는 경우

이런 경우조차도 **VPN/프록시가 더 단순하고 합법적**이다 (DPI 우회는 ISP 약관 위반 소지).

### 3-4. 비교: GoodbyeDPI vs VPN vs 프록시

| 도구 | 다루는 계층 | 합법성 | 본 프로젝트 적합성 |
|---|---|---|---|
| GoodbyeDPI / Zapret | L4 (패킷 조작) | ISP 약관 위반 가능 | × |
| VPN (Wireguard 등) | L3 (IP 변경) | 일반적으로 합법 | △ (지역 블록 사이트만) |
| Residential proxy | L3 (IP 변경) | 합법, 비쌈 | △ (대량 호출 시) |
| TLS fingerprint 위조 | L7 (handshake) | 회색 | △ (Cloudflare 사이트만) |

---

## 4. 통합 전략 — 막혔을 때 시도 순서

Playwright stealth 도 막힌 사이트에 대해 *조사 단계에서* 시도해볼 순서:

```
1. probe 로 진단
   ├─ TCP handshake 가 안 되면 → L4 문제 (희귀) → VPN 시도
   ├─ TLS handshake 가 끊기면 → L4 SNI 차단 → GoodbyeDPI 또는 VPN
   ├─ HTTP 200 인데 "Just a moment..." → L7 → curl_cffi
   └─ HTTP 200 인데 captcha → L7 + JS challenge → Playwright + patched Chrome

2. 가장 약한 통과 방법 선택 (probe/diagnose.py 의 fallback chain 과 동일)
   httpx → httpx + 캡처 헤더 → curl_cffi → Playwright stealth → 외부 유료 API
```

본 프로젝트의 [probe/diagnose.py:45-65](../probe/diagnose.py#L45-L65) 가 이미 비슷한 fallback chain 을 가지고 있는데, **여기 사이에 `curl_cffi` 단계를 끼워넣는 것** 이 가장 자연스러운 도입 지점이다 (`httpx` 와 Playwright 사이).

---

## 5. 도입 시 검토할 위험

본 프로젝트에 도입할 경우:

| 항목 | 비고 |
|---|---|
| **법적 위험** | 사람인 판례는 *"고빈도 + 우회"* 조합에서 트리거. 일 1회 폴링 + fingerprint 위장은 회색 지대. |
| **TOS 위반** | 대상 사이트의 robots.txt 와 이용약관에 "자동화된 접근 금지" 가 있으면 그 자체로 약관 위반. |
| **유지보수** | curl_cffi 의 Chrome impersonation 은 Chrome 버전이 올라가면 라이브러리 업데이트가 필요. |
| **돌파 후 폭주 위험** | fingerprint 가 통과되면 사이트가 "사람" 으로 인식 → 실수로 빠른 호출 시 IP ban 위험 ↑. polite_sleep 더 강하게 적용 필요. |
| **GoodbyeDPI** | Windows 드라이버 단에서 모든 트래픽 영향. 다른 앱이 영향받음. 서버 배포 환경 (Linux) 에서는 Zapret 으로 대체. |

---

## 6. 결론 (조사 한정)

- **현실적으로 본 프로젝트가 실제로 시도할 만한 한 가지** = `curl_cffi` 도입. Python 친화적이고, Cloudflare basic 통과율 높고, [probe/](../probe/) 의 fallback chain 사이에 끼워 넣기 쉽다. 도입 시 [probe/fetch_static.py](../probe/fetch_static.py) 옆에 `fetch_impersonate.py` 추가하는 형태가 자연스럽다.
- **GoodbyeDPI 류 DPI 우회는 본 프로젝트 타깃 사이트와 무관**. 조사 차원에서 알아두되 도입 우선순위 최하.
- **TLS fingerprint 위조 ≠ 만능.** JS challenge 사이트는 여전히 Playwright + patched Chromium 조합이 필요.
- **도입 전 반드시** [크롤링 지침.md](크롤링%20지침.md) 의 "차단 우회 직접 시도 금지" 와의 정합성 재검토.

---

## 참고 자료

**TLS fingerprint**
- [JA3/JA4 설명 — Scrapfly](https://scrapfly.io/web-scraping-tools/ja3-fingerprint)
- [TLS Fingerprinting — ProxyHat](https://proxyhat.com/blog/tls-fingerprinting-explained)
- [JA4+ Fingerprinting Guide 2026 — proxies.sx](https://www.proxies.sx/use-cases/privacy/tls-fingerprint)
- [Overcoming TLS Fingerprinting — Rayobyte](https://rayobyte.com/blog/tls-fingerprinting/)
- [Network fingerprint impersonation — fluxzy](https://www.fluxzy.io/resources/blogs/impersonate-network-fingerprint)

**도구**
- [curl_cffi (Python)](https://github.com/lexiforest/curl_cffi) — JA3/HTTP2 위조 가능한 Python HTTP 클라이언트
- [curl-impersonate](https://github.com/lwthiker/curl-impersonate) — 위 라이브러리의 C 백엔드
- [webclaw 0xMassi](https://github.com/0xMassi/webclaw) — Rust, `wreq` + BoringSSL

**DPI 우회**
- [ValdikSS/GoodbyeDPI](https://github.com/ValdikSS/GoodbyeDPI) — Windows DPI 우회
- [GoodbyeDPI Wikipedia](https://en.wikipedia.org/wiki/GoodbyeDPI)
- [GoodbyeDPI-Linux 포팅](https://github.com/wickstudio/GoodbyeDPI-Linux)
