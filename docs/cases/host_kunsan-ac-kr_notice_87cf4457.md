---
slug: host_kunsan-ac-kr_notice_87cf4457
url: https://www.kunsan.ac.kr/notice
status: "✅ registered - /notice landing routed to 공지사항 boardId=BBS_0000008"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys:
  - gen_fail:posts_nonempty
  - wrong-path:notice-landing
config_strategy: httpx_html
requested_by: kruniv-batch-2026-05-21
---

## Diagnosis

preflight: miss - no existing config before this hand-config pass.

N100 probe artifact was pulled with `python scripts/triage.py pull --slug host_hanyang-ac-kr_notice_cec27fd6`, which synced all current FAILED/probe artifacts including this slug.

The `/notice` artifact is a landing page, not the canonical notice list. Probe noted "정적 응답이 빈 shell" for static fetch and Playwright HTML contained many mixed landing-page sections. The initial list candidate included unrelated landing/news carousel links such as `boardId=BBS_0000021`, so using the first candidate directly would watch the wrong surface.

The same page menu contains `공지사항` pointing to:

- `/index.kunsan?menuCd=DOM_000000105001001000`
- live redirect target: `/board/list.kunsan?boardId=BBS_0000008&menuCd=DOM_000000105001001000&contentsSid=211&cpath=`

That board list has `table tbody tr` notice rows and `dataSid` detail links.

## Fix

Added `configs/host_kunsan-ac-kr_notice_87cf4457.json` with:

- `strategy=httpx_html`
- list URL `https://www.kunsan.ac.kr/board/list.kunsan?boardId=BBS_0000008&menuCd=DOM_000000105001001000`
- row selector `table tbody tr`
- required selector `td.tit a[href*='dataSid=']`
- post id from `dataSid`
- article content selector `div.bv_content`

## Verification

`python scripts/register.py --config configs/host_kunsan-ac-kr_notice_87cf4457.json`

Result: registered, baseline 10 posts.

Sample:

- `1380938` / `2026-05-22T00:00:00+09:00` / `[인권센터] 성범죄 예방 캠퍼스 안심 소식지 안내`

Regression surface: config-only change for one slug. No shared engine, probe, prompt, recognizer, or script file was touched.

## Generalization Candidate

- pattern: KR university `/notice` catalog URL is a landing page with mixed carousels; the actual notice board is behind a same-site menu URL with boardId/menuCd.
- evidence: this slug and `host_swu-ac-kr_notice_abcc7861` both needed same-site menu/iframe board endpoint discovery rather than first-candidate selection.
- fix layer candidate: C for probe digest signal, or B for config-writer examples, to detect "landing mixed rows" and prefer menu/iframe board endpoints.
- next chunk action: yes, but not in this allow-list chunk. A follow-up should generalize same-site notice menu extraction.

## Escalate (allow-list 밖 수정 필요)

Generic improvement would touch probe/prompt files. This chunk kept only the site-specific config and case documentation.
