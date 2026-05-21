---
slug: host_canva-com_whats-new_1e430553
url: https://www.canva.com/whats-new/
status: ✅ 등록 (Canva public newsroom whats-new articles)
outcome: handcrafted
date: 2026-05-21
fix_layer: F
failure_keys: [capability_blocked, cloudflare, login_redirect, canva_whats_new]
config_strategy: handwritten
adapters_changed: [adapters/canva_whats_new.py]
engine_files_touched: []
tags: [manual-config, handwritten-adapter, anti-bot, cloudflare, sitemap]
requested_by: unknown
---

## 트리거

`https://www.canva.com/whats-new/` 자동 등록 실패. 사용자 제공 요약은 `rc=5 capability_blocked` 계열이며, anti-bot/Cloudflare 차단 때문에 stealth 또는 Chrome impersonation 재도전 대상이었다.

로컬 worktree에는 기존 `.FAILED.json`/probe artifact가 없어서 fresh dev-box probe로 재현했다.

## 진단

preflight: `miss — host_canva-com_whats-new_1e430553`.

- `configs/host_canva-com_whats-new_1e430553.json` 없음.
- `engine.recognizers.recognize("https://www.canva.com/whats-new/")` 결과 `None`.
- 로컬 `.FAILED.json`/기존 probe artifact 없음.

fresh probe 결과:

- 정적 GET `S1.H2/H3/H4/Hcap`: 403 `BLOCKED_BOT`, `cf-mitigated: challenge`.
- Playwright headless `S4`: 200이지만 `https://www.canva.com/login/?redirect=%2Fwhats-new%2F`로 이동해 `LOGIN_REQUIRED`.
- `list_candidates.json`의 first article은 실제 글이 아니라 로그인 페이지 nav 링크 `https://www.canva.com/ko_kr/posters/`.
- `diagnosis.json verdict`: `분류 보류`.

robots.txt 확인: `/whats-new/`, `/newsroom/news/`, `landing_page_sitemap_1.xml`은 명시 `Disallow` 대상이 아니고 Crawl-Delay는 없다.

## 픽스

단일 handwritten config와 Canva 전용 adapter를 추가했다.

- `configs/host_canva-com_whats-new_1e430553.json`
- `adapters/canva_whats_new.py`
- `adapters/__init__.py` export 추가
- `requirements.txt`에 `curl_cffi` 추가

`/whats-new/` 자체는 로그인 리다이렉트라 직접 목록으로 쓸 수 없다. 대신 robots가 노출하는 공개 sitemap `https://www.canva.com/landing_page_sitemap_1.xml`에서 `/newsroom/news/` 하위의 `whats-new` URL만 추려 목록을 만든다. 개별 newsroom 글은 `curl_cffi` Chrome impersonation으로 fetch하고, `h1`/`main`에서 제목과 본문 HTML을 채운다.

`curl_cffi` 선택 이유: 같은 URL이 `httpx`에서는 Cloudflare 403을 반환하지만 `curl_cffi` Chrome impersonation에서는 sitemap과 newsroom 글이 200으로 열린다. 프록시, CAPTCHA solving, 공격적 재시도는 쓰지 않았다. adapter는 5-8초 `polite_sleep`를 둔다.

## 트랙 B 후보

- **2a (인식기 PATTERNS 확장)**: X — Canva 단일 사이트 전용이고 재사용 가능한 플랫폼 URL 형태가 아니다.
- **2b (--article-url)**: X — 첫 글 오인이 아니라 원 목록 URL 자체가 로그인/Cloudflare 경계에 걸린다.
- **2c (probe heuristic)**: X — probe에 보이는 신호는 Cloudflare/login 경계뿐이며, generic selector 추론으로 해결되지 않는다.
- **2d (probe artifact 수정)**: X — artifact 추출 문제가 아니라 fetch 능력 문제다.

일반화 안 되는 이유: `curl_cffi`로 공개 sitemap을 읽는 것은 Canva의 공개 newsroom sitemap 구조에 의존하는 단일 사이트 패치다. capability_blocked 누적은 많지만, 이 케이스는 범용 anti-bot 우회가 아니라 공개 대체 source로 우회한 handcrafted adapter다.

## 회귀 검증

영향 범위는 새 adapter class, adapter export, 새 config, 새 dependency로 제한된다. 기존 engine/probe/prompt/recognizer는 변경하지 않았다.

검증:

```text
python scripts/register.py --config configs/host_canva-com_whats-new_1e430553.json
→ ✅ 등록 완료 — baseline 13건
```
