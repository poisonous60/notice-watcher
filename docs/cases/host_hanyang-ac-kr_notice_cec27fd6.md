---
slug: host_hanyang-ac-kr_notice_cec27fd6
url: https://www.hanyang.ac.kr/notice
status: "✅ registered - Liferay notice portlet rows parsed with httpx_html"
outcome: handcrafted
date: 2026-05-24
fix_layer: none
failure_keys:
  - gen_fail:posts_nonempty
config_strategy: httpx_html
requested_by: kruniv-batch-2026-05-21
---

## Diagnosis

preflight: miss - no existing config before this hand-config pass.

N100 probe artifact was pulled with `python scripts/triage.py pull --slug host_hanyang-ac-kr_notice_cec27fd6`. The local artifact shows HTTP 200 and "정적 HTTP로 충분". The useful board rows are:

- `div.hyu-list-body-inner > div.hyu-list-body-item`, child_count=20
- detail links contain `_kr_ac_hanyang_noticeBoard_web_portlet_NoticeBoardPortlet_entryId=...`
- first actual row title: `[서울 학부]2026학년도 1학기 기말 강의평가 실시 안내`

The failed generator picked nearby structure but did not produce a working selector/result. This is a site-specific Liferay notice-board portlet config, not an engine change.

## Fix

Added `configs/host_hanyang-ac-kr_notice_cec27fd6.json` with:

- `strategy=httpx_html`
- row selector `div.hyu-list-body-inner > div.hyu-list-body-item`
- required detail selector `h4 a[href*='entryId=']`
- `entryId` as `post_id`
- `div.hyu-list-body` as article content fallback

## Verification

`python scripts/register.py --config configs/host_hanyang-ac-kr_notice_cec27fd6.json`

Result: registered, baseline 20 posts.

Sample:

- `107902` / `2026-05-22T00:00:00+09:00` / `[서울 학부]2026학년도 1학기 기말 강의평가 실시 안내`

Regression surface: config-only change for one slug. No shared engine, probe, prompt, recognizer, or script file was touched.

## Generalization Candidate

- pattern: KR university Liferay custom portlet rows where the post id is held in a namespaced `entryId` query parameter.
- evidence: this slug only in the current 5-site chunk; no second same-platform slug in this allow-list.
- fix layer candidate: B or A if repeated, by adding a few-shot/rule for namespaced Liferay portlet query ids.
- next chunk action: no for this chunk; record as single-site handcrafted config unless 2+ more Liferay notice-board misses appear.

## Escalate (allow-list 밖 수정 필요)

None. This site was solved inside the allow-list with a single config.
