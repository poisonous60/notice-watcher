---
slug: _generic_audit_race_guard
url: "(multi-slug generic fix)"
status: "✅ improved — agentic audit ignores clean git-pull HEAD advances"
outcome: improved
date: 2026-05-27
fix_layer: F
failure_keys: [register_audit_violation, audit_false_positive_git_pull]
engine_files_touched: [generate/codex_agentic.py]
tags: [audit, race-condition, infra, batch-safety]
trigger_slug: host_metacoregames-c_news_450fe577
---

## 증상

2026-05-27 batch `2026-05-24-games-mobile-casual` 에서
`host_metacoregames-c_news_450fe577` agentic register 가 `AUDIT_FAIL` 로 `.BUG` 처리됐다.
violations 로 찍힌 5개 파일은 dev box 에서 같은 날 이미 push 된 정상 변경이었다.

- `fca65d5` 10:54 KST: `scripts/dashboard.py`, `tests/dashboard/test_probe_har_view.py`
- `3794086` 13:19 KST: `docs/adr/0015-worktree-isolation-for-parallel-sessions.md`, `scripts/codex_batch.py`, `tests/dashboard/test_prompts.py`
- `cf505d0` 14:01 KST: `tests/dashboard/test_prompts.py`
- `cb1b5fe` 14:08 KST: `tests/dashboard/test_prompts.py`

agentic 시작 시각은 `2026-05-27T05:23:34Z` = 14:23 KST 였다. 즉 child agent 가 쓴 파일이 아니라,
N100 deploy wrapper 의 `git pull` 로 repo HEAD 가 agentic pre/post snapshot 사이에서 advance 한 race 로 보는 것이 맞다.

## 원인

`generate/codex_agentic.py:_audit_diff` 는 guarded dirs 의 SHA256+size snapshot 만 비교했다.
그 결과 agent write 와 git pull 로 들어온 정상 tracked file 변경을 구분하지 못했고,
batch worker 에서는 한 사이트의 race 가 batch 전체에 BUG marker 로 번지는 fragile path 가 됐다.

## 수정

F-layer 에서 audit 판정을 HEAD-aware 로 바꿨다.

- pre/post snapshot 과 함께 `git rev-parse HEAD` 를 저장한다.
- HEAD 가 같거나 HEAD 를 읽을 수 없으면 기존 snapshot diff 판정을 유지한다.
- HEAD 가 advance 하면 `git diff <pre_head>..<post_head> --name-only` 로 pull 변경 파일 집합을 계산한다.
- violation 후보가 그 집합에 있고, worktree 가 `post_head` 와 clean 하면 git pull race 로 보고 skip 한다.
- 같은 파일이라도 worktree 가 `post_head` 와 다르면 agent write 로 보고 violation 을 유지한다.
- pull 변경 집합 밖의 guarded file 변경은 기존처럼 violation 이다.

## 검증

`tests/codex_agentic/test_audit_race_guard.py` 가 아래 5개 경로를 fixture git repo 로 재현한다.

1. `pre_head == post_head` 에서는 content change 가 그대로 violation 이다.
2. `pre_head != post_head` 이고 변경 파일이 pull set 에 있으며 worktree 가 post HEAD 와 clean 하면 skip 한다.
3. 같은 파일이 pull set 에 있어도 agent 가 추가로 worktree 를 바꾸면 violation 이다.
4. HEAD 는 advance 했지만 pull set 밖의 guarded file 변경은 violation 이다.
5. git HEAD 를 읽을 수 없는 환경은 `[audit] HEAD snapshot unavailable` warn 후 기존 판정으로 fallback 한다.

## Track B 6-layer audit

- E miss: schema validator 로 막을 config shape 문제가 아니다.
- D miss: validate retry feedback 문제가 아니라 parent audit 판정 문제다.
- C miss: probe artifact/digest 신호와 무관하다.
- B miss: few-shot exemplar 로 해결할 생성 패턴 문제가 아니다.
- A miss: prompt 지시로 agent write 를 구분하는 문제가 아니다.
- F hit: `generate/codex_agentic.py` 의 audit engine 이 git HEAD advance 를 판별해야 한다.

## 남은 운영 리스크

`n100_deploy.sh` 는 active service wait 를 하지만 batch worker 의 child agentic audit window 까지 완전히 cover 하지 못한다.
이번 fix 는 그 남은 deploy/batch overlap 을 audit false-positive 로 만들지 않게 하는 방어선이다.
