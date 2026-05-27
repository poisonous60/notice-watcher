"""Skill 트리거 프롬프트 빌더.

각 함수는 사용자가 클립보드에 복사한 뒤 VSCode Claude Code 창에 붙여넣을 텍스트를 반환한다.
키워드(`수동 config 작성`, `report-triage` 등)는 해당 SKILL.md 의 트리거에 맞춰 잡힘 — Claude 가
자동으로 매칭 스킬을 실행.

복사 후 사용자는 [Enter] 만 누르면 됨.
"""
from __future__ import annotations

from typing import Optional


def hand_config_for_url(*, url: str, slug: Optional[str] = None,
                        fail_reason: Optional[str] = None,
                        job_id: Optional[int] = None) -> str:
    lines = ["다음 `/preview` 실패 사이트 분석해줘 (skill: hand-config).", ""]
    lines.append(f"URL: {url}")
    if slug:
        lines.append(f"slug: {slug}")
    if fail_reason:
        lines.append(f"실패 사유: {fail_reason}")
    if job_id is not None:
        lines.append(f"관련 잡: #{job_id}")
    lines.append("")
    lines.append("목표: 사이트 분석 → Track B 일반화 후보 먼저 도출. `/preview <url>` command origin 이 ship evidence 이므로 ship default=true.")
    lines.append("Track B (1순위): canonical 6 자리 E/D/C/B/A/F 를 순서대로 audit "
                 "(schema 거부 / retry feedback / probe digest 신호 / few-shot / system 규칙 추가 / 새 엔진 코드). "
                 "한 자리라도 hit 면 그 일반화 개선을 우선 박음.")
    lines.append("Track A (optional): Track B 6 자리 all miss + `/preview` ship evidence hit 일 때만 수동 config/손어댑터 진입. "
                 "둘 다 아니면 park 가 valid terminal — 사이트 단위 ship 강제 X.")
    lines.append("")
    lines.append("§2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 강제 인용 "
                 "(**0 live 확인 — `curl -sI <URL>` 또는 browser 로 *지금* 사이트 직접 본 1줄 (stale probe artifact entry 금지)** / "
                 "1 last_feedback / 2 verdict / 3 근거 / 4a Track B 6-layer / 4b Track A 결정 / "
                 "4c context ship evidence(`/preview`) / 4d park 분기 / 5 cases_index / 6 preflight). "
                 "live 와 probe digest 모순이면 **live 우선**. 0번 = 항상 의무 (artifact 없는 §0 신규 case 도). "
                 "artifact 없는 §0 신규 case 는 1~5 만 예외. — SKILL.md \"§2 진입 전 강제 인용\" 박스.")
    return "\n".join(lines)


def hand_config_redo_slug(*, slug: str, url: Optional[str] = None) -> str:
    lines = ["다음 slug 재처리해줘 (skill: hand-config).", ""]
    lines.append(f"slug: {slug}")
    if url:
        lines.append(f"URL: {url}")
    lines.append(f"현재 config: configs.snapshot/{slug}.json (참고용 — dev 의 configs/ 가 진본)")
    lines.append("")
    lines.append("문제 진단 → Track B 일반화 후보(E/D/C/B/A/F) 먼저 audit → 필요 시 수정 → fetch 확인.")
    lines.append("slug redo 요청 자체가 이 사이트 ship evidence 이므로 ship default=true. "
                 "단 Track A(수동 config/손어댑터)는 Track B 6 자리 all miss 일 때만 optional 진입.")
    lines.append("")
    lines.append("§2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 강제 인용 "
                 "(**0 live 확인 — `curl -sI <URL>` 또는 browser 로 *지금* 사이트 직접 본 1줄 (stale probe artifact entry 금지)** / "
                 "1 last_feedback / 2 verdict / 3 근거 / 4a Track B 6-layer / 4b Track A 결정 / "
                 "4c context ship evidence(redo 요청) / 4d park 분기 / 5 cases_index / 6 preflight). "
                 "live 와 probe digest 모순이면 **live 우선**. — SKILL.md \"§2 진입 전 강제 인용\" 박스.")
    return "\n".join(lines)


def hand_config_triage_queue(*, failed_slugs: list[str]) -> str:
    """codex 위임 모드 kickoff (ADR 0008). 붙여넣으면 Claude 가 entry→codex 위임→리뷰→배포.

    절차 상세는 SKILL.md §0c — 여기선 트리거 + 청크 흐름 요약 + slug 데이터만.
    """
    n = len(failed_slugs)
    lines = [
        f"FAILED 큐 codex 위임 처리해줘 (skill: hand-config — triage, codex 위임 모드). 총 {n}건.",
        "",
        "ADR 0008 위임 하네스로 — 진입·diff 검토·commit·배포는 너(Claude), "
        "중간 orchestration(진단·fix·probe_smoke)은 codex 보이는 창 (Claude 토큰 0). "
        "전체 절차 = SKILL.md \"§0c codex 위임 모드\". 요약:",
        "",
        "1. `python scripts/triage.py pull --skip-later`  (FAILED + probe 받기)",
        "1b. **실전 경로 유지**: batch/FAILED 재시도는 현재 기본 `auto` 그대로 둔다 "
        "(api_loop_once → agentic). `--no-agentic` 은 cheap 가설 확인 전용이지 batch 성공률 판단에 쓰지 않는다. "
        "개선 포인트는 agent 호출 억제가 아니라 agent 입력 축소/품질 개선: `failure_packet`·curated examples·rules compact 를 확인한다.",
        "1c. **agentic-first / per-site codex 는 최후 수단** (SKILL.md §0c-0, 2026-05-26). "
        "default `auto` 가 agentic 까지 자동 타기 때문에 *2+ slug 가 같은 fail 신호* 면 그 generic 해결을 "
        "**agentic 입력/휴리스틱/프롬프트**(C/B/A/F-layer) 자리에 박는다 — 한 PR 봉합 → batch 재시도 시 agentic 자동 처리. "
        "per-site codex 는 *cross-site 일반화 0인 잔여만*. 위임 시에도 **각 task 에 같은 batch 동료 slug 의 (URL, fail_reason) 목록 박기 의무** — "
        "isolated brief 만 주면 codex 가 'site 전용' punt 하여 §0c-회피 게이트 2 무력화 (2026-05-26 games-indie 박힘).",
        "2. **청크 분할 = 분석 응집 단위** (`codex_batch.py plan` 은 단서). 같은 플랫폼/host/cohort 신호를 한 청크로 묶어 cross-site 패턴을 보게 한다. "
        "파일 소유 목록은 만들지 않는다 — Track B 후보를 사전에 막지 않기 위해서다.",
        "3. **병렬 launch (`--worktree`)** — 각 codex 프롬프트(`codex_handoff.py generic --task-file --launch --worktree`)는 격리 worktree 에서 실행. "
        "codex 는 필요한 repo 파일을 자유롭게 수정한다. 첫 batch/품질 미관측이면 관측-우선(1-2청크) 후 확대. 모델=gpt-5.5 medium 유지(속도노브 opt-in).",
        "4. 청크별 `python scripts/codex_watch.py <result_file> --loop` (백그라운드)  (완료 대기)",
        "5. **각 청크 git diff + result 검토 게이트 = 진짜 enforcement** — `git diff main...<codex-branch>` 로 codex 실제 변경만 보고, HARD-STOP 지켰나/진단 타당한가/"
        "Track B 를 처방-우선 task 때문에 미루지 않았나/auto-discovery semantic 충돌(probe_smoke --stage 5) 있나 확인. 문제면 worktree 버림·재위임.",
        "6. settled 트리 probe_smoke(--stage 3 --stage 5) → `cases_index --backfill-db` 직렬 → **검토 통과 파일만 명시 stage(`git add -A` 금지)** → push → N100 배포 → batch 후 `triage.py prune-orphans --execute`.",
        "6b. **모든 fail 의 종료 상태 박기 의무** (2026-05-26 박힘) — 보고 전 *각 미등록 slug* 가 4종 종료 중 하나에: "
        "① `registered` (config 박힘), "
        "② `Later` (capability_blocked auto-defer 또는 dev box `triage_later.json` 손-park, rc=5 류만), "
        "③ `gate-fail park` (분류기 개선 대기, `triage.py park-gate-fail <slug> --reason=…`), "
        "④ **`REJECTED`** (영구 거부 — N100 `.FAILED.json` → `.REJECTED.json`). "
        "**`.FAILED.json` 잔존 금지** (다음 batch/세션이 작업큐서 또 보임 + 응답 'failed=재시도 가능' 분류). dev box config 작동 하지만 N100 환경 한계(TLS reset / Chromium DNS / 정책상 우회 X) = `_save_rejected(slug, url, 'capability_blocked: <원인>', learn=False)` ssh remote 호출 (register.py 가 sibling cleanup·triage_queue prune 다 함, 응답 'rejected=영구'). "
        "dev box `triage_later.json` *만* 박는 건 X — 그건 dev box dashboard view 만, N100 봇·register 거동 영향 0. "
        "보고 시 종료 분포 명시 (`registered N / Later N / gate-fail-park N / REJECTED N / 정상거부 N = total`).",
        "6d. **terminal action freeze** — `REJECTED` 손-박기 / `park-gate-fail` / true-board Later / `no_change` 는 정리 작업이 아니라 terminal decision. "
        "실행 전 먼저 slug별 제안만 하라: `live 확인`(지금 직접 연 사이트·HTTP·렌더 구조), `probe artifact`(`triage.py show` + output/probe; stale snapshot 은 보조 근거), "
        "`terminal bucket`, `rollback` 4줄을 보여준다. **generic `진행해` 는 terminal 실행 승인 X** — 위 증거를 보인 뒤 받은 slug별 terminal action 승인만 실행. "
        "**raw 503/DNS/timeout 한 줄만으로 REJECTED 금지**; 첫 진단 pass 에서도 live 확인 + probe artifact + 현재 실전 경로 증거가 맞고 우회·개선하지 않을 capability 한계면 REJECTED 가능. 반복 재시도 의무가 아니라 stale snapshot/단발 관측 닫기 금지다.",
        "",
        "**gen_fail(rc=1) 은 §0b-2 screen-out 먼저** — '진짜 게시판 아님' 3종을 골라내 사이트별 작업 낭비 차단: "
        "(P1) content-as-list 오탐(단일 글이 index 로 통과 — `list_candidates` 반복 행 0~소수+단일 본문 → `prompts/classify.system.txt` content 측 보강), "
        "(P2) not-found shell 미분류(title/h1 not-found 인데 등록 진행 → 분류기 not_found 보강 `prompts/classify.system.txt`; 옛 _SOFT_404_PATTERNS regex 제거됨 ADR 0007 §확장), "
        "(P3) empty/fake feed(RSS 후보지만 item 0 또는 HTML shell → 분류기 보강 + gate-fail park). "
        "P1/P2 는 영구 게이트 봉합(§8a)+slug 거부, outcome=improved. 통과한 잔여만 hand-config 진단.",
        "",
        "**비-게시판인데 분류기가 이번 batch 에 자동거부 못 하면(classify `?`/미신뢰) → per-site 손-거부 X → "
        "`python scripts/triage.py park-gate-fail <slug> --reason=…`** (gate-fail 버킷, **Later 아님**). "
        "분류기/게이트 다음 개선 때 `sweep-gate-fail --execute` 로 일괄 재판정. "
        "Later 는 capability(cap_blocked·SPA·timeout) 전용 — 두 버킷 섞지 X (SKILL.md §1 표).",
        "",
        "대상 slug:",
    ]
    for s in failed_slugs:
        lines.append(f"- {s}  (output/snapshot/poll_state/{s}.FAILED.json)")
    lines.append("")
    lines.append("각 slug 기본 프레임: Track B 1순위 — canonical 6 자리 E/D/C/B/A/F "
                 "(schema 거부 / retry feedback / probe digest 신호 / few-shot / system 규칙 추가 / 새 엔진 코드) 를 먼저 audit. "
                 "batch/triage operator 흐름은 ship default=false.")
    lines.append("Track A(수동 config/손어댑터)는 Track B 6 자리 all miss + 특정 slug/URL 에 묶인 명시 ship 요청이 있을 때만 optional. "
                 "ship evidence = `Track A`·`수동 config`·`이 사이트 즉시 작동`·`ship 필요` + slug/URL 직결 문장. "
                 "`codex`·`agentic`·`generic improvement` 는 Track B 의도라 ship evidence 로 세지 X.")
    lines.append("Track A skip 시 park 가 valid terminal: classifier/gate fallthrough 는 `triage.py park-gate-fail`, "
                 "true board + ship 요청 0 은 `case_log no_change` + `triage_later.json` 손-park, cap_blocked 는 auto Later.")
    lines.append("REJECT 사이트라도 구조 분석해 Track B 개선이 1순위. 특수/tradeoff 명확할 때만 스킵 + case log 에 이유.")
    lines.append("각 slug §2 분기 *전*: 강제 인용 "
                 "(**0 live 확인 — `curl -sI <URL>` 또는 browser 로 *지금* 사이트 직접 본 1줄 (stale probe artifact entry 금지)** / "
                 "1 last_feedback / 2 verdict / 3 근거 / 4a Track B 6-layer / 4b Track A 결정 / "
                 "4c context ship evidence / 4d park 분기 / 5 cases_index / 6 preflight). "
                 "live 와 probe digest 모순이면 **live 우선** (probe = 캡쳐 시점 snapshot — 사이트는 변함). "
                 "— SKILL.md \"§2 진입 전 강제 인용\" 박스 (0번 = 2026-05-27 박힘).")
    return "\n".join(lines)


def report_triage_single(*, report_id: int, slug: Optional[str],
                         issue: Optional[str], reporter: Optional[str]) -> str:
    lines = [f"사용자 신고 #{report_id} 처리해줘 (skill: report-triage).", ""]
    if slug:
        lines.append(f"slug: {slug}")
    if reporter:
        lines.append(f"신고자: {reporter}")
    if issue:
        # backtick 살릴 필요 없음 — 일반 본문에 그대로 들어가야 Claude 가 읽기 편함
        lines.append("issue:")
        for ln in (issue or "").splitlines() or [""]:
            lines.append(f"  {ln}")
    lines.append("")
    lines.append("진단 → 수정 → 배포 → /admin resolve 까지.")
    return "\n".join(lines)


def report_triage_bulk(*, report_ids: list[int]) -> str:
    n = len(report_ids)
    ids = ", ".join(f"#{i}" for i in report_ids)
    lines = [f"open 신고 일괄 triage 해줘 (skill: report-triage). 총 {n}건.", ""]
    lines.append(f"대상 신고: {ids}")
    lines.append("")
    lines.append("각 신고 진단·수정·배포·resolve 까지 처리.")
    return "\n".join(lines)


def catalog_run_and_fix(*, catalog_name: str,
                        untried: int = 0, failed: int = 0, bug: int = 0) -> str:
    """catalog 1개 batch run + 결과 진단·수정 단일 프롬프트. dashboard `/candidates/<name>` 에서 복사.

    Claude 가 새 세션에서 받으면 register_batch 실행 → drain 대기 → fail 분류 → hand-config /
    bug-fix workflow 분기 → re-run `--failed` 까지 자율 진행.
    """
    lines = [f"catalog `{catalog_name}` batch 돌리고 결과 진단·수정해줘 (skill: hand-config — codex 위임 모드).", ""]
    lines.append(f"현재 분포: untried={untried} / failed={failed} / bug={bug}")
    lines.append("")
    lines.append("ADR 0008 위임 하네스로 — batch 실행·fail 분류·diff 검토·commit·배포는 너(Claude), "
                 "중간 진단·fix(gen_fail·capability_blocked·bug)는 codex 보이는 창 (Claude 토큰 0). "
                 "절차 = SKILL.md \"§0c codex 위임 모드\". codex 결과 맹신 X — 각 청크 diff 검토 게이트.")
    lines.append("")
    lines.append("절차:")
    lines.append(f"1. `python scripts/remote.py batch-register --catalog={catalog_name}` 호출 → untried entry 큐 enqueue.")
    lines.append("2. worker drain 대기 — `python scripts/remote.py logs bot --tail 50` 와 dashboard `/candidates/" + catalog_name + "` KPI 로 진행 확인.")
    lines.append("3. drain 완료 후 fail_kind 분포 확인 (dashboard 또는 jobs 테이블).")
    lines.append("3b. **실전 경로 유지**: batch/FAILED 재시도는 현재 기본 `auto` 그대로 둔다 "
                 "(api_loop_once → agentic). `--no-agentic` 은 cheap 가설 확인 전용이지 batch 성공률 판단에 쓰지 않는다. "
                 "개선 포인트는 agent 호출 억제가 아니라 agent 입력 축소/품질 개선: `failure_packet`·curated examples·rules compact 를 확인한다.")
    lines.append("3c. **agentic-first / per-site codex 는 최후 수단** (SKILL.md §0c-0, 2026-05-26 박힘). "
                 "default `auto` 가 agentic(codex) 까지 자동 타기 때문에 *같은 batch 의 2+ sites 가 같은 fail 신호* 면 "
                 "그 generic 해결을 **agentic 입력/휴리스틱/프롬프트** 자리(C/B/A/F-layer) 에 박는다 — "
                 "indie studio /news/ subpath, RSS feed 자동 detect, SPA shell row-count 분기 같은 cross-site 패턴은 "
                 "여기서 한 PR 로 봉합하면 batch 재시도 시 agentic 이 자동 처리. "
                 "per-site codex 위임으로 site 별 수동 config 찍어내는 건 *cross-site 일반화 0인 잔여만* — "
                 "위임 시에도 **각 task 에 같은 batch 동료 sites 의 (URL, fail_reason) 목록 박기 의무** "
                 "(없으면 codex 가 isolated brief 라 cross-site 패턴 못 보고 '이 사이트 전용' punt — §0c-회피 게이트 2 무력화). "
                 "위임 전 1분 rubric: '같은 fail_reason/신호/fix layer 가 2+ sites?' YES → agentic 자리. NO → per-site codex (동료 brief 포함).")
    lines.append("4. **아래 우선순위대로** 처리 (2026-05-21 사용자 결정 — SKILL.md §0a):")
    lines.append("   1) **bug** (rc=-1/-2/-3/-5/-99, `.BUG.json`): *무조건 fix*, 최우선. traceback → bot/scripts/engine 코드 수정 (bug-fix workflow). `register.py 실행 시간 초과(300s)` 류 timeout 도 여기 — root-cause.")
    lines.append("   2) **gate_reject** (rc=3): board_shape/nav_only/single-article 게이트 거부 + LLM index/content 분류기(veto)도 content 판정(ADR 0007). 게시판/비게시판 false-reject 봉합은 *분류기 layer 의 일* — 임의로 '의도된 거부'라 신뢰 X. **사용자에게 분포·샘플 보고하고 확인 대기**, 받으면 fix 순서 = ① `prompts/classify.system.txt`/모델 보강 (게이트 휴리스틱 추가 X) → ② SPA(정적 HTML 에 목록 없음)면 render 트랙. SKILL.md §0a-2.")
    lines.append("   3) **capability_blocked** (rc=5, `.FAILED.json`): captcha/anti-bot/cloudflare 차단 = *능력 부족(정책 아님)*. stealth/anti-detection 어댑터로 재도전 (§2e + `docs/크롤링 지침.md` §6 stealth 허용).")
    lines.append("   4) **gen_fail** (rc=1, `.FAILED.json`): **§0b-2 screen-out 먼저** — (P1) content-as-list 오탐(단일 글이 index 로 통과 → `prompts/classify.system.txt` content 측 보강) · (P2) not-found shell 미분류(title/h1 not-found 인데 등록 진행 → 분류기 not_found 보강 `prompts/classify.system.txt`; 옛 _SOFT_404_PATTERNS regex 제거 ADR 0007 §확장) · (P3) empty/fake feed(RSS 후보지만 item 0 또는 HTML shell): 진짜 게시판 아님. 통과한 잔여만 Track B 1순위 진단(heuristic/classifier/config_writer prompt/recognizer/engine); Track A 수동 config 는 ship 명시 요청 있을 때만 optional.")
    lines.append("   - **policy_reject** (rc=2, LOGIN_REQUIRED) · **url_dead** (rc=4, 404/cert·dns 깨짐) = 작업 X (정상 거부, `docs/크롤링 지침.md`). 우회 X.")
    lines.append("   - **실행 = codex 위임** (SKILL §0c): bug·gen_fail·capability_blocked 의 진단·fix 는 codex 보이는 창에 위임 "
                 "(`codex_handoff.py generic --task-file --launch --worktree`). worktree 격리 안에서 codex 는 필요한 repo 파일을 자유롭게 수정한다. "
                 "같은 플랫폼/host/cohort 신호를 한 청크로 묶어 분석하고, 첫 batch 는 관측-우선(1-2청크) 후 확대. 모델=gpt-5.5 medium. "
                 "청크별 `codex_watch.py <result> --loop` 완료 → **git diff main...branch + result 검토 게이트(HARD-STOP·Track B 회피·semantic 충돌)** → 검토 통과 파일만 직렬 stage/commit → 배포.")
    lines.append(f"5. 재시도: `python scripts/remote.py batch-register --catalog={catalog_name} --failed` (rc∈{{1,5,-1,-2,-3,-99}} — capability_blocked 포함).")
    lines.append("6. registered 100% 또는 root-cause 못 잡는 사이트만 남을 때까지 반복.")
    lines.append("6b. **모든 fail 의 종료 상태 박기 의무** (2026-05-26 박힘) — batch 끝났다 보고 전에 *각 미등록 slug* 가 다음 4종 종료 상태 중 하나에 들어가야 한다. `.FAILED.json` 그대로 놔두지 X (다음 batch/세션이 작업큐서 또 보임 + 응답 'failed=재시도 가능' 분류; *dashboard KPI 정리 목적 아님* — dashboard fail-kind 는 jobs row 기반 history):"
                 " ① `registered` (config 박힘),"
                 " ② `Later` (capability_blocked auto-defer 또는 dev box `triage_later.json` 손-park — rc=5 류만),"
                 " ③ `gate-fail park` (분류기 개선 대기, `python scripts/triage.py park-gate-fail <slug> --reason=…`),"
                 " ④ **`REJECTED`** (영구 거부, N100 `.FAILED.json`→`.REJECTED.json`. dev box config 작동 하지만 N100 환경 한계(TLS reset/DNS 환경/Chromium issue)·정책상 우회 X 인 경우 = capability_blocked 영구. ssh remote 로 `_save_rejected(slug, url, 'capability_blocked: <원인>', learn=False)` 호출 — register.py 가 sibling cleanup 다 함)."
                 " 보고 시 종료 분포 명시 (예: `registered 19 / Later 7 / gate-fail-park 0 / REJECTED 2 / 정상거부 72 = 100`).")
    lines.append("6c. **dev box `triage_later.json` 만 박는 건 X** — 그건 dev box `triage.py list --skip-later` filter 뿐, N100 봇·register 거동에 영향 0 (`is_blocked(slug)` 는 N100 marker REJECTED/FAILED/BUG 봄, `triage_later.json` 은 dev box gitignored). FAILED 만 있어도 봇 진입은 차단되지만 응답 'failed=재시도 가능' 이라 영구 거부 의미 아님. 영구면 N100 `.REJECTED.json` 까지 박아야 응답 'rejected=영구' + sibling cleanup.")
    lines.append("6d. **terminal action freeze** — `REJECTED` 손-박기 / `park-gate-fail` / true-board Later / `no_change` 는 정리 작업이 아니라 terminal decision. "
                 "실행 전 먼저 slug별 제안만 하라: `live 확인`(지금 직접 연 사이트·HTTP·렌더 구조), `probe artifact`(`triage.py show` + output/probe; stale snapshot 은 보조 근거), "
                 "`terminal bucket`, `rollback` 4줄을 보여준다. **generic `진행해` 는 terminal 실행 승인 X** — 위 증거를 보인 뒤 받은 slug별 terminal action 승인만 실행. "
                 "**raw 503/DNS/timeout 한 줄만으로 REJECTED 금지**; 첫 진단 pass 에서도 live 확인 + probe artifact + 현재 실전 경로 증거가 맞고 우회·개선하지 않을 capability 한계면 REJECTED 가능. 반복 재시도 의무가 아니라 stale snapshot/단발 관측 닫기 금지다.")
    lines.append("")
    lines.append("각 fail 기본 프레임: Track B 1순위 — canonical 6 자리 E/D/C/B/A/F "
                 "(schema 거부 / retry feedback / probe digest 신호 / few-shot / system 규칙 추가 / 새 엔진 코드) 를 먼저 audit. "
                 "catalog/batch operator 흐름은 ship default=false.")
    lines.append("Track A(수동 config/손어댑터)는 Track B 6 자리 all miss + 특정 slug/URL 에 묶인 명시 ship 요청이 있을 때만 optional. "
                 "ship evidence = `Track A`·`수동 config`·`이 사이트 즉시 작동`·`ship 필요` + slug/URL 직결 문장. "
                 "`codex`·`agentic`·`generic improvement` 는 Track B 의도라 ship evidence 로 세지 X.")
    lines.append("Track A skip 시 park 가 valid terminal: classifier/gate fallthrough 는 `triage.py park-gate-fail`, "
                 "true board + ship 요청 0 은 `case_log no_change` + `triage_later.json` 손-park, cap_blocked 는 auto Later.")
    lines.append("")
    lines.append("REJECT 사이트도 구조 분석 → probe 개선 시도. 특수 케이스나 tradeoff 명확하면 case log 이유 기록.")
    lines.append("")
    lines.append("각 slug §2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 강제 인용 "
                 "(**0 live 확인 — `curl -sI <URL>` 또는 browser 로 *지금* 사이트 직접 본 1줄 (stale probe artifact entry 금지)** / "
                 "1 last_feedback / 2 verdict / 3 근거 / 4a Track B 6-layer / 4b Track A 결정 / "
                 "4c context ship evidence / 4d park 분기 / 5 cases_index / 6 preflight). "
                 "live 와 probe digest 모순이면 **live 우선**. cross-site 패턴 (2+ slug 같은 live 신호) 보이면 §0c-0 agentic-first. "
                 "— SKILL.md \"§2 진입 전 강제 인용\" 박스 (0번 = 2026-05-27 박힘, stale snapshot terminal 분류 사고 차단).")
    return "\n".join(lines)


def recognizer_extension_cluster(*, host_or_template: str,
                                 members: list[tuple[str, str]]) -> str:
    """cluster 1개 → recognizer-extension 스킬 트리거. dashboard `/clusters` 또는 cluster_report 에서 복사.

    members = [(slug, url), ...] — 묶을 개별 config 멤버들.
    """
    n = len(members)
    lines = [f"이 cluster recognizer 로 승급해줘 (skill: recognizer-extension). 총 {n}개 멤버.", ""]
    lines.append(f"패턴: {host_or_template}")
    lines.append("멤버 (config + url):")
    for slug, url in members:
        lines.append(f"- configs/{slug}.json   ← {url}")
    lines.append("")
    lines.append("절차: 멤버 config 비교 → canonical 템플릿·변수 슬롯 판단 → "
                 "engine/recognizers/<platform>.py 작성 → round-trip 테스트(멤버 전부 재현) → "
                 "reject 충돌 검사 → cluster_report 봉합 확인 → reviewer → push → N100 배포.")
    lines.append("URL 에서 못 뽑는 변수 슬롯 있으면 그 멤버 빼고 보고. SKILL.md 절차 따름.")
    return "\n".join(lines)


def diagnose_slug(*, slug: str) -> str:
    """skill 아님 — 그냥 자연어 진단 요청. 사용자가 인터랙티브하게 파고들고 싶을 때."""
    return (
        f"slug `{slug}` 진단해줘.\n"
        f"- `python scripts/inspect_subs.py diagnose {slug}` 결과 살펴보고\n"
        f"- 필요하면 `python scripts/inspect_subs.py fetch {slug}` 로 fetch 결과 확인\n"
        f"- 깨졌으면 수동 config 재작성 (hand-config skill) 까지 진행."
    )
