---
slug: host_indiehackers-co_root_e4490db0
url: https://www.indiehackers.com/
status: ⏸️ 중단 (SPA/click-render, 현재 config 어휘로 안정 표현 불가)
outcome: no_change
date: 2026-05-21
fix_layer: none
failure_keys: [posts_nonempty, spa_no_static_rows, click_render_required]
config_strategy: none
adapters_changed: []
engine_files_touched: []
tags: [indiehackers, spa, ember, click-render, batch-2026-05-21-misc]
vocab_candidates:
  - candidate: click_rendered_list
    confidence: med
    evidence:
      - output/probe/host_indiehackers-co_root_e4490db0/article_click.json
      - case_feedback: "posts_nonempty 0; static candidates only scripts/meta/link; click resolved a real /post URL"
    reasoning: "목록 글 링크가 정적 후보에는 없고 Playwright click 후에만 실제 post URL 이 확정된다. 현재 선언형 config 는 click-derived list rows/API 없이 안정 표현하기 어렵다."
    analysis_date: 2026-05-21
    deferred: true
---

## 무엇이 일어났나

자동 생성은 `playwright_html` 로 `article`, `a[href*='/product/']`,
`div:has(a[href*='/product/'])` 방향을 시도했지만 전부 `posts_nonempty: 0건` 이었다.

probe 상태:

- 정적 반복 후보는 `script`, `meta`, `link` 뿐이다.
- `article_click.json` 은 실제 클릭으로
  `/post/what-if-your-linkedin-outreach-only-went-to-people-who-were-already-paying-attention-aa3b7c179f`
  까지 resolve 됐음을 보여준다.
- 이 작업 폴더의 probe artifact 에는 분석 가능한 `traffic.har`/`traffic.article_click.har` 파일이
  남아 있지 않았다.

## 판단

현재 허용 범위의 config 어휘만으로는 안정적인 목록을 만들 근거가 부족하다. 사용자가 요청한 대로
XHR/JSON이 확인되면 `httpx_json` config 를 만들 수 있지만, 저장 artifact 에는 JSON API 후보가 없고
HAR 파일도 없어 endpoint/list_path 를 검증할 수 없다.

## 조치

config 를 작성하지 않고 case 로 중단 기록만 남긴다. future work 는 둘 중 하나다.

- probe artifact 에 HAR 가 보존되는 환경에서 XHR/JSON endpoint 를 확인한 뒤 `httpx_json` config 작성.
- click/scroll 기반 목록 수집이 필요하면 새 어휘 또는 handwritten adapter 검토.

## 검증

- 변경 파일 없음.
- `register.py --config` 미실행.

## 트랙 B

`click_rendered_list` vocab 후보를 deferred 로 기록했다. 같은 SPA/click-render 목록 사례가 반복되면
config 어휘 또는 hand adapter 쪽으로 별도 설계를 검토한다.
