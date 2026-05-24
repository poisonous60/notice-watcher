---
slug: host_gnue-ac-kr_notice_199024b6
url: https://www.gnue.ac.kr/notice
status: "⚪ no_change - /notice returned HTTP Error page; no board URL proven in artifact"
outcome: no_change
date: 2026-05-24
fix_layer: none
failure_keys:
  - gen_fail:posts_nonempty
  - soft-error-page
requested_by: kruniv-batch-2026-05-21
---

## Diagnosis

preflight: miss - no existing config before this hand-config pass.

N100 probe artifact was pulled with `python scripts/triage.py pull --slug host_hanyang-ac-kr_notice_cec27fd6`, which synced all current FAILED/probe artifacts including this slug.

The artifact is an error shell, not a notice board:

- `summary.txt`: `short body (953 bytes) - possible SPA shell`
- `list_candidates.json`: `html_repeating_patterns=[]`, `first_article_url=null`
- `list.html` title: `광주교육대학교`
- visible body includes `HTTP Error`

I also probed one likely guessed CMS board path, `https://www.gnue.ac.kr/kor/CMS/Board/Board.do?mCode=MN040`; it returned the same 967-byte error page. That was not enough evidence to substitute a different board URL for this slug.

## Outcome

No config was added. The current URL is best treated as catalog noise or unresolved URL discovery, not a hand-config target.

## No-change Requirements

- attempted action: pulled N100 artifact, inspected `summary.txt`, `diagnosis.json`, `list_candidates.json`, `list.html`, and tried one likely CMS board path.
- blocking signal: `HTTP Error` page with zero list candidates and no first article.
- real fix path: classify this as url_dead/soft-error, or run a separate discovery task with a verified GNUE notice board URL.

## Generalization Candidate

- pattern: KR university short HTTP 200 error page enters gen_fail because classifier/probe does not convert it to url_dead.
- evidence: this slug has explicit `HTTP Error`; `host_dongduk-ac-kr_notice_f00cd658` has a related empty shell with zero candidates.
- fix layer candidate: C or A for stronger soft-error/not-found classification.
- next chunk action: yes, but outside this allow-list. A follow-up should improve screen-out for HTTP Error and empty-shell `/notice` URLs.

## Escalate (allow-list 밖 수정 필요)

Potential generic fix would touch classifier/probe/prompt behavior, not config-only files. This chunk records the evidence and stops.
