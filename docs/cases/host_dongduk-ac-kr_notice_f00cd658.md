---
slug: host_dongduk-ac-kr_notice_f00cd658
url: https://www.dongduk.ac.kr/notice
status: "⚪ no_change - /notice returned empty shell; no board URL proven in artifact"
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys:
  - gen_fail:posts_nonempty
  - empty-shell
requested_by: kruniv-batch-2026-05-21
---

## Diagnosis

preflight: miss - no existing config before this hand-config pass.

N100 probe artifact was pulled with `python scripts/triage.py pull --slug host_hanyang-ac-kr_notice_cec27fd6`, which synced all current FAILED/probe artifacts including this slug.

The artifact shows HTTP 200 but no usable board content:

- `summary.txt`: `short body (478 bytes) - possible SPA shell`
- `list_candidates.json`: `html_repeating_patterns=[]`, `first_article_url=null`
- `list.html`: `<html><head></head><body></body></html>`

I also probed one likely guessed path, `https://www.dongduk.ac.kr/kor/edu/notice.do`; it returned HTTP 404. That was not enough evidence to substitute a different board URL for this slug.

## Outcome

No config was added. Creating a config here would be guessing a board outside the provided `/notice` evidence.

## No-change Requirements

- attempted action: pulled N100 artifact, inspected `summary.txt`, `diagnosis.json`, `list_candidates.json`, `list.html`, and tried one likely notice path.
- blocking signal: `list.html` is an empty body and candidates are zero; guessed path returned 404.
- real fix path: classify this as catalog noise or run a separate discovery task with a verified Dongduk notice board URL.

## Generalization Candidate

- pattern: short HTTP 200 shell with no article URL and no repeated rows.
- evidence: this slug is an empty shell; `host_gnue-ac-kr_notice_199024b6` is similar but returns an explicit HTTP Error page.
- fix layer candidate: C or A for stronger soft-error/not-found classification if these continue to enter gen_fail.
- next chunk action: yes, but outside this allow-list. A follow-up should improve screen-out so empty-shell `/notice` URLs become url_dead/gate-reject instead of gen_fail.

## Escalate (allow-list 밖 수정 필요)

Potential generic fix would touch classifier/probe/prompt behavior, not config-only files. This chunk records the evidence and stops.
