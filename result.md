# krpublic batch audit result

## A. URL missing parameter
- Change: added `detect_url_missing_param_pattern` in `probe/extract.py`.
- Scope: detects KR egov/CMS board URLs with a board id but missing menu-ish params (`menuid`, `menuCd`, `mId`, `mid`, `mnSeq`) when the page looks like auth redirect, empty shell, or empty rows.
- Output surface: diagnostic helper is covered by tests. I did not add a new `diagnosis.json` top-level key because that requires changing probe artifact contract files outside the task allow-list.
- Prompt: `prompts/config_writer.system.txt` now tells the config writer to preserve suggested menu params for same URL family boards.

## B. JS detail URL
- Change: added `extract_js_detail_template` in `probe/extract.py`.
- Scope: extracts simple inline functions such as `goView(seq) { location.href = '/view?seq=' + seq + '&menuCd=...' }`.
- Output surface: `html_repeating_patterns` rows with JS hrefs can now carry `detail_url_template`.
- Prompt: config writer now prefers `detail_url_template` before falling back to row `data-*` or handwritten handling.

## C. KIEP classifier false-reject
- Change: updated `prompts/classify.system.txt`.
- Scope: KR public/research CMS board family URLs such as `.es?mid=...&bid=...`, `/bbs/list.do`, and `/selectNttList.do` should remain `index` when rows are readable notices/bids/posts, even with only one visible row.
- No site-specific allow-list was added.

## D. TLS handshake fallback
- Change: added `engine/_http.py` and routed `httpx_html` / `httpx_json` through shared TLS-aware GET helper.
- Schema: `list.tls_fallback` accepts `"playwright"` or `"none"`.
- Behavior: TLS transport failures get a legacy OpenSSL retry by default. If `list.tls_fallback` is `"playwright"`, the engine raises an explicit escalation message to use `playwright_html`.

## Regression
- `python scripts/probe_smoke.py --stage 3 --stage 5` PASS: 241 / 241 configs OK, 969 heuristic cases, 0 FAIL.
- `python scripts/vocab_lint.py` PASS.
- Config diff: 0 files under `configs/`.
- N100: read-only probe artifact pull attempted and completed for the named audit slugs; no service, git, or deployment command run.

## Escalate
- Full `diagnosis.json.url_missing_param` wiring is intentionally not implemented here because it needs `probe/diagnose.py`, `probe/report.py`, and `probe/_contract.py`, which are outside the allow-list.
- I did not run `register.py --reuse-probe` for target sites because it can write configs/poll_state; the task explicitly forbids config and triage-state changes.
