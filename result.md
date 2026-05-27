## 결과
- registered (smoke OK): host_bethesda-net_news_29303712, host_bethesda-net_news_c5aa2960, host_store-epicgames_news_16cc8b8f, host_epicgames-com_news_4655a152, host_deadbydaylight-_news_7eed0155
- registered (smoke FAIL, but config 작성): none
- 못 한 것 (capability/structural): none

## generic 개선
- prompts/config_writer.system.txt: generated CSS/MUI/jss selector를 그대로 복사하지 말고 href prefix 기반 selector와 Gatsby/Next/page-data JSON 후보를 우선하도록 보강.
- generate/validate.py 및 engine: `probe_grounding_list_row_selector` 실패 피드백에 top probe selector/href/sample/first_article_url 포함. `article.fetch_kind:"json"`을 html/playwright list strategy에서도 실행하도록 보강.

## 검증
- schema validation: 5/5 `schema OK`.
- per-site smoke: 5/5 list >= 5 and body chars > 100. Body chars: Bethesda www 12106, Bethesda non-www 12106, Epic Store 5508, Epic www 5508, Dead by Daylight 2799.
- `python scripts/probe_smoke.py --stage 3 --stage 5`: exit 0; summary `PASS 1739 FAIL 0 WARN 1 SKIP 0`.
- `python scripts/vocab_lint.py`: exit 0; `OK: scanned 406 file(s), 23 high-confidence rule(s)`.
- hand-config-reviewer: reported missing `docs/cases/INDEX.md`, but this is intentionally deferred because task hard-stopped `cases_index.py` / backfill / INDEX work.

## 다음 batch retry 명령
- `python scripts/remote.py batch-register --catalog=2026-05-24-games-us --failed gen`

## 변경 파일
- configs/host_bethesda-net_news_29303712.json
- configs/host_bethesda-net_news_c5aa2960.json
- configs/host_store-epicgames_news_16cc8b8f.json
- configs/host_epicgames-com_news_4655a152.json
- configs/host_deadbydaylight-_news_7eed0155.json
- prompts/config_writer.system.txt
- generate/validate.py
- engine/strategies/httpx_html.py
- engine/strategies/playwright_html.py
- docs/cases/host_bethesda-net_news_29303712.md
- docs/cases/host_bethesda-net_news_c5aa2960.md
- docs/cases/host_store-epicgames_news_16cc8b8f.md
- docs/cases/host_epicgames-com_news_4655a152.md
- docs/cases/host_deadbydaylight-_news_7eed0155.md
- docs/cases/_generic_agentic_selector_grounding_2026-05-28.md
