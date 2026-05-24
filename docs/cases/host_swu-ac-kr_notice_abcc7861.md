---
slug: host_swu-ac-kr_notice_abcc7861
url: https://www.swu.ac.kr/notice
status: "✅ registered - /notice image-map landing routed to SWU board iframe endpoint"
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

The `/notice` artifact is an old image-map landing page. It has same-host notice links such as `/gopage/goboard5.jsp?bbsConfigFK=8&pkid=495392`, but the real list is exposed through the menu page `/www/noticea.html`, which embeds `/front/boardlist.do?bbsConfigFK=8`.

Live validation showed:

- `/www/noticea.html` returns a board page with an iframe.
- `/front/boardlist.do?bbsConfigFK=8` returns `table tbody tr` rows.
- each row title anchor uses `onclick=boardMove('/front/boardview.do','509948')`.

## Fix

Added `configs/host_swu-ac-kr_notice_abcc7861.json` with:

- `strategy=httpx_html`
- list URL `https://www.swu.ac.kr/front/boardlist.do?bbsConfigFK=8`
- row selector `table tbody tr`
- post id extracted from `boardMove(..., '<pkid>')`
- article URL template `https://www.swu.ac.kr/front/boardview.do?bbsConfigFK=8&pkid={post_id}`
- article content selector `div.contents`

## Verification

`python scripts/register.py --config configs/host_swu-ac-kr_notice_abcc7861.json`

Result: registered, baseline 13 posts.

Sample:

- `509948` / `2026-05-21T00:00:00+09:00` / `[보건실]심폐소생술 기본과정 50기 교육 안내`

Regression surface: config-only change for one slug. No shared engine, probe, prompt, recognizer, or script file was touched.

## Generalization Candidate

- pattern: KR university `/notice` catalog URL is a landing or image-map shell, while the actual board endpoint is reachable through a same-site menu/iframe.
- evidence: this slug and `host_kunsan-ac-kr_notice_87cf4457` both required moving from `/notice` to a concrete board endpoint discovered from page/menu structure.
- fix layer candidate: C for probe digest signal, or B for config-writer examples, to prefer same-site menu/iframe board endpoints over decorative landing rows.
- next chunk action: yes, but not in this allow-list chunk. A follow-up probe/prompt chunk should teach "notice landing -> same-site board iframe/menu endpoint" without hardcoding these domains.

## Escalate (allow-list 밖 수정 필요)

The general fix belongs outside this allow-list because it would touch probe digest and/or prompt examples. The site-specific config was completed inside the allow-list.
