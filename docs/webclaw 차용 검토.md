# webclaw 차용 검토

[0xMassi/webclaw](https://github.com/0xMassi/webclaw) (Rust 기반 범용 웹 크롤러) 의 기술 중 본 프로젝트에 도입할 만한 부분을 정리한다.

본 프로젝트는 **"일 1회 폴링, 사이트별 어댑터, 차단 우회 금지"** 가 전제이므로 webclaw의 모든 기능을 그대로 가져올 수는 없다. 자기 규칙과 충돌하지 않는 선에서만 차용한다.

---

## 1. 차용하지 않을 것

### 1-1. TLS / HTTP2 fingerprint 위장 (`wreq` + BoringSSL)

webclaw의 핵심 셀링 포인트는 *"브라우저 없이 Chrome처럼 보이는 TLS·HTTP2 지문"* 으로 봇 탐지를 통과하는 것이다.

**도입 불가.** [크롤링 지침.md](크롤링%20지침.md) 와 [README.md:96](../README.md#L96) 의 **"차단 우회 직접 시도 금지 (사람인 판례)"** 와 정면 충돌한다. 차단되는 사이트는 지금처럼:
- Playwright stealth 로 합법적인 브라우저를 띄우거나
- 외부 유료 API ([reference/](../reference/)) 로 떠넘기거나
- 그 사이트는 그날 스킵

하는 쪽을 유지한다.

### 1-2. 한 호스트에 동시 다중 connection (5/10/20 thread)

webclaw가 자랑하는 "20 thread → 32.1 pages/sec" 같은 벤치마크는 **같은 호스트로 동시 요청을 쏟는 것**이라 [크롤링 지침.md "2-2. 요청 간 간격"](크롤링%20지침.md) 과 충돌한다.

**도입 불가.** 단, 아래 2-1 의 *"호스트가 다르면 동시 가능"* 은 별개 이야기.

---

## 2. 차용할 것

### 2-1. 사이트 단위 병렬화 ★

본 프로젝트의 가장 큰 효율 손실은 사이트가 N개로 늘어나면 수집 시간이 N배가 되는 것이다. 어댑터들이 모두 동기 (`httpx.Client`, Playwright sync) 라 자연스럽게 직렬로 돌게 되어있다.

**핵심 관찰**: `polite_sleep` / `Crawl-Delay` 는 **같은 호스트** 안에서만 의미가 있는 제약이다. endfield · dcinside · arca 는 서로 다른 호스트이므로 동시에 돌려도 어떤 사이트의 매너 규칙도 위반하지 않는다.

**도입 방식**:
- `concurrent.futures.ThreadPoolExecutor` 에 어댑터 1개 = task 1개로 submit.
- 어댑터들이 이미 동기 + context manager 구조이므로 asyncio 재작성 불필요.
- Playwright sync API 는 thread 별로 `sync_playwright().start()` 를 가지면 안전 (단 메모리 N배).
- 결과 `NoticePost` 리스트들을 모아서 합치고 다운스트림으로 전달.

**가드레일** (반드시 지켜야 함):
- **같은 호스트를 두 번 등록 금지.** 예: 디시 갤러리 두 개를 동시에 돌리면 30초 Crawl-Delay 가 무의미해진다.
- 호스트별 `threading.Semaphore(1)` 을 dict 로 두면 사고 방지 가능. 같은 host 로 가는 task 가 둘 이상 등록돼도 그 둘은 직렬화된다.
- `max_workers` 는 사이트 수 이하로 묶는다. CPU 가 아니라 동시 활성 어댑터 수 제한 목적.
- Playwright 어댑터가 섞여있으면 메모리 압박 주의 (어댑터당 Chromium 1개).

**예상 효과**: 사이트 N개에 대해 수집 시간이 *대략* `max(각 사이트 시간)` 으로 수렴. 가장 느린 사이트 (보통 Crawl-Delay 30초인 dcinside, 또는 Playwright 띄우는 arca) 가 전체 시간을 좌우한다.

### 2-2. snapshot diff (webclaw `--diff-with`)

webclaw 는 이전 수집 결과의 hash 와 비교해 변경분만 출력하는 옵션이 있다.

본 프로젝트는 공지 봇 특성상 **"새 글만 푸시"** 가 핵심 요구사항이고, `post_id` 기반 dedup 은 [skku-notice-bot/](../skku-notice-bot/) 등에서 이미 하고 있을 것으로 보인다. 여기에 한 단계 더 얹을 만한 부분:

- **본문 hash 비교**: `post_id` 가 같아도 본문이 수정된 글을 잡고 싶을 때. `content_html` 의 정규화된 hash 를 같이 저장.
- **제목 hash 비교**: 운영자가 제목만 바꾸는 경우 (예: `[모집중]` → `[마감]`).

저장 위치는 `output/state/<site>.json` 정도가 자연스럽다 (이미 [README.md:43](../README.md#L43) 에 storage_state 가 그 경로로 들어가는 패턴이 있음).

### 2-3. 구조화된 추출: JSON-LD / data island 우선

webclaw 는 readability 외에 React/Next.js 의 `__NEXT_DATA__`, `<script type="application/ld+json">` 같은 **이미 구조화된 JSON 데이터 island** 를 추출하는 경로를 가진다.

본 프로젝트의 어댑터는 현재 site별 CSS selector 하드코딩 ([dcinside.py:96](../adapters/dcinside.py#L96), [arca.py:34](../adapters/arca.py#L34) 등) 이라, selector 가 바뀌면 그날 수집이 망가진다. 많은 SSR 사이트 (특히 게임사 공식 사이트) 는 동일 정보를 더 깨끗한 JSON 형태로 페이지에 함께 박아둔다.

**도입 방식**: [사이트 어댑터 추가 가이드.md](사이트%20어댑터%20추가%20가이드.md) 의 어댑터 작성 단계에 *"selector 보다 JSON island 우선 시도"* 를 추가. [probe/hydration.py](../probe/hydration.py) 가 이미 hydration 후보를 뽑으므로 probe 출력에서 활용 가능.

**효과**: selector 변경에 대한 내성 ↑. 다만 사이트가 SPA 가 아닌 순수 서버 렌더 HTML 이면 의미 없음 (디시인사이드는 해당 없음).

### 2-4. (부분) readability 본문 추출 — fallback 용도로만

webclaw 의 multi-signal scoring (text density · semantic tag · link ratio) 은 **모르는 사이트에 처음 들어갔을 때** 가장 가치가 있다.

본 프로젝트의 어댑터는 본문 컨테이너를 이미 정확히 알고 있으므로 ([dcinside.py:224-228](../adapters/dcinside.py#L224-L228) 의 `div.write_div` 등) 모든 어댑터를 readability 로 갈아엎을 이유는 없다.

**도입 방식**: 새 사이트 정찰 단계 ([probe/extract.py](../probe/extract.py)) 에 trafilatura 또는 readability-lxml 을 보조로 추가. probe 출력의 `summary.txt` 에 *"readability 가 추출한 본문"* 을 같이 적어두면 selector 작성 시 정답지 역할을 한다.

런타임 어댑터에는 도입하지 않는다 (정확도가 site-specific selector 보다 떨어짐).

---

## 3. 우선순위

| 우선순위 | 항목 | 이유 |
|---|---|---|
| 1 | **2-1. 사이트 단위 병렬화** | 즉시 효과. 사이트 수에 비례한 시간 절감. 구조 변경 작음 (어댑터 수정 불필요, 러너만 추가). |
| 2 | **2-2. snapshot diff (본문 hash)** | 운영 안정성 향상. "수정된 글" 누락 방지. |
| 3 | **2-3. JSON island 우선** | 새 사이트 추가 시 안정성 ↑. 기존 어댑터 리팩터는 굳이 X. |
| 4 | **2-4. readability fallback (probe 한정)** | 정찰 단계 편의. 없어도 무방. |

---

## 4. 명시적 거부 항목 (재확인)

자기 규칙과 충돌하므로 webclaw 가 가졌더라도 도입하지 않는다:

- TLS / HTTP2 fingerprint 위장
- 같은 호스트로 동시 다중 connection
- 자동 로그인 ([README.md:95-96](../README.md#L95-L96): 사용자가 한 번 헤드풀로 로그인 → state.json 재사용 유지)
- 차단 사이트에 대한 우회 시도 — 차단되면 합법 브라우저 또는 외부 API 로 위임 ([크롤링 지침.md](크롤링%20지침.md))
