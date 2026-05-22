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
    lines = ["다음 사이트 수동 config 작성해줘 (skill: hand-config 모드 A).", ""]
    lines.append(f"URL: {url}")
    if slug:
        lines.append(f"slug: {slug}")
    if fail_reason:
        lines.append(f"실패 사유: {fail_reason}")
    if job_id is not None:
        lines.append(f"관련 잡: #{job_id}")
    lines.append("")
    lines.append("두 트랙 *동시* 진행 (한쪽 막는 게이트 X):")
    lines.append("  - 트랙 A (사용자 향 — 사이트 즉시 작동): 수동 config / 손어댑터 작성 → configs/ → N100 배포.")
    lines.append("  - 트랙 B (미래 향 — 같은 패턴 자동 처리): 진단 중 분기 2a (인식기 확장) / 2b (--article-url) / "
                 "2c (probe 휴리스틱 + retry feedback hint) / 2d (probe artifact 수정) 후보 한 줄씩 enumerate. "
                 "매칭 있으면 그 자리도 같은 PR 에 박음. 매칭 0이면 case 파일에 이유 한 줄.")
    lines.append("")
    lines.append("§2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 4개 강제 인용 "
                 "(last_feedback `[FAIL]` 줄 / diagnosis verdict / 매칭 §번호 / 분기 후보+이유). "
                 "artifact 없는 §0 신규 case 만 예외. — SKILL.md \"§2 진입 전 강제 인용\" 박스.")
    return "\n".join(lines)


def hand_config_redo_slug(*, slug: str, url: Optional[str] = None) -> str:
    lines = ["다음 사이트 수동 config 재작성해줘 (skill: hand-config).", ""]
    lines.append(f"slug: {slug}")
    if url:
        lines.append(f"URL: {url}")
    lines.append(f"현재 config: configs.snapshot/{slug}.json (참고용 — dev 의 configs/ 가 진본)")
    lines.append("")
    lines.append("문제 진단 → 수정 → fetch 확인 → 배포.")
    lines.append("")
    lines.append("§2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 4개 강제 인용 "
                 "(last_feedback `[FAIL]` 줄 / diagnosis verdict / 매칭 §번호 / 분기 후보+이유). "
                 "— SKILL.md \"§2 진입 전 강제 인용\" 박스.")
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
        "2. **disjoint 파일소유 청크 분할** (`codex_batch.py plan` 은 단서). 공유 충돌파일=`scripts/register.py`(detect dispatch)+`probe/extract.py`(detect_*): "
        "path-match recognizer·수동 config=공유파일 0=병렬안전, probe-detect 플랫폼(root-URL)=한 청크만 소유·나머지 직렬. 소유 기록 output/codex_file_claims.json.",
        "3. **병렬 launch (ALLOW-LIST 박아서)** — 각 codex 프롬프트(`codex_handoff.py generic --task-file`)에 '이 파일만 편집, 나머지 금지' 제약. "
        "file-isolated 청크는 **다발 동시 launch**, 공유파일 청크는 소유자 1개+나머지 직렬. 첫 batch/품질 미관측이면 관측-우선(1-2청크) 후 확대. 모델=gpt-5.5 medium 유지(속도노브 opt-in).",
        "4. 청크별 `python scripts/codex_watch.py <result_file> --loop` (백그라운드)  (완료 대기)",
        "5. **각 청크 git diff + result 검토 게이트 = 진짜 enforcement** (ALLOW-LIST 는 soft) — codex HARD-STOP 지켰나/진단 타당한가/"
        "파일셋이 ALLOW-LIST 내인가(over-edit·타청크 침범)/auto-discovery semantic 충돌(probe_smoke --stage 5). 문제면 revert·재위임.",
        "6. settled 트리 probe_smoke(--stage 3 --stage 5) → `cases_index --backfill-db` 직렬 → **청크별 commit(`git add <청크 파일만>`, -A 금지)** → push → N100 배포 → batch 후 `triage.py prune-orphans --execute`.",
        "",
        "**gen_fail(rc=1) 은 §0b-2 screen-out 먼저** — '진짜 게시판 아님' 2종을 골라내 수동 config 낭비 차단: "
        "(P1) content-as-list 오탐(단일 글이 index 로 통과 — `list_candidates` 반복 행 0~소수+단일 본문 → `prompts/classify.system.txt` content 측 보강), "
        "(P2) not-found shell 미분류(title/h1 not-found 인데 등록 진행 → 분류기 not_found 보강 `prompts/classify.system.txt`; 옛 _SOFT_404_PATTERNS regex 제거됨 ADR 0007 §확장). "
        "둘 다 영구 게이트 봉합(§8a)+slug 거부, outcome=improved. 통과한 잔여만 hand-config 진단.",
        "",
        "대상 slug:",
    ]
    for s in failed_slugs:
        lines.append(f"- {s}  (output/snapshot/poll_state/{s}.FAILED.json)")
    lines.append("")
    lines.append("각 slug 두 트랙 *동시* (codex 프롬프트에 박힘): A(사이트 즉시 작동) + "
                 "B(추론 개선 — probe 휴리스틱/schema/prompt 로 미지 유형 자동화, 수동 config 의존도 ↓).")
    lines.append("REJECT 사이트라도 구조 분석해 probe 개선이 1순위. 특수/tradeoff 명확할 때만 스킵 + case log 에 이유.")
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
    lines.append("4. **아래 우선순위대로** 처리 (2026-05-21 사용자 결정 — SKILL.md §0a):")
    lines.append("   1) **bug** (rc=-1/-2/-3/-5/-99, `.BUG.json`): *무조건 fix*, 최우선. traceback → bot/scripts/engine 코드 수정 (bug-fix workflow). `register.py 실행 시간 초과(300s)` 류 timeout 도 여기 — root-cause.")
    lines.append("   2) **gate_reject** (rc=3): board_shape/nav_only/single-article 게이트 거부 + LLM index/content 분류기(veto)도 content 판정(ADR 0007). 게시판/비게시판 false-reject 봉합은 *분류기 layer 의 일* — 임의로 '의도된 거부'라 신뢰 X. **사용자에게 분포·샘플 보고하고 확인 대기**, 받으면 fix 순서 = ① `prompts/classify.system.txt`/모델 보강 (게이트 휴리스틱 추가 X) → ② SPA(정적 HTML 에 목록 없음)면 render 트랙. SKILL.md §0a-2.")
    lines.append("   3) **capability_blocked** (rc=5, `.FAILED.json`): captcha/anti-bot/cloudflare 차단 = *능력 부족(정책 아님)*. stealth/anti-detection 어댑터로 재도전 (§2e + `docs/크롤링 지침.md` §6 stealth 허용).")
    lines.append("   4) **gen_fail** (rc=1, `.FAILED.json`): **§0b-2 screen-out 먼저** — (P1) content-as-list 오탐(단일 글이 index 로 통과 → `prompts/classify.system.txt` content 측 보강) · (P2) not-found shell 미분류(title/h1 not-found 인데 등록 진행 → 분류기 not_found 보강 `prompts/classify.system.txt`; 옛 _SOFT_404_PATTERNS regex 제거 ADR 0007 §확장): 둘 다 영구 게이트 봉합+거부(진짜 게시판 아님). 통과한 잔여만 hand-config 진단 → 수동 config 또는 probe/prompt 개선 (두 트랙 동시).")
    lines.append("   - **policy_reject** (rc=2, LOGIN_REQUIRED) · **url_dead** (rc=4, 404/cert·dns 깨짐) = 작업 X (정상 거부, `docs/크롤링 지침.md`). 우회 X.")
    lines.append("   - **실행 = codex 위임** (SKILL §0c): bug·gen_fail·capability_blocked 의 진단·fix 는 codex 보이는 창에 위임 "
                 "(`codex_handoff.py generic --task-file --launch`, ALLOW-LIST 박음). **disjoint 파일소유로 병렬** — "
                 "path-match recognizer·수동 config=병렬안전, probe-detect 플랫폼(register.py+extract.py 공유)=직렬. 첫 batch 관측-우선(1-2청크) 후 확대. 모델=gpt-5.5 medium. "
                 "청크별 `codex_watch.py <result> --loop` 완료 → **git diff+result 검토 게이트(파일셋 ALLOW-LIST 내·HARD-STOP·semantic 충돌)** → 직렬 commit(청크별 git add) → 배포.")
    lines.append(f"5. 재시도: `python scripts/remote.py batch-register --catalog={catalog_name} --failed` (rc∈{{1,5,-1,-2,-3,-99}} — capability_blocked 포함).")
    lines.append("6. registered 100% 또는 root-cause 못 잡는 사이트만 남을 때까지 반복.")
    lines.append("")
    lines.append("각 fail 두 트랙 *동시* 진행 (한쪽 막는 게이트 X):")
    lines.append("  - 트랙 A (사용자 향 — 사이트 즉시 작동): 수동 config / 손어댑터 → configs/ → 배포.")
    lines.append("  - 트랙 B (미래 향 — 같은 패턴 자동 처리): probe 휴리스틱 / 인식기 / prompt 개선 → 같은 패턴 자동.")
    lines.append("매칭 있으면 같은 PR 에 박음. 매칭 0이면 case 파일에 이유.")
    lines.append("")
    lines.append("REJECT 사이트도 구조 분석 → probe 개선 시도. 특수 케이스나 tradeoff 명확하면 case log 이유 기록.")
    lines.append("")
    lines.append("각 slug §2 분기 *전*: `triage.py show <slug>` 출력 받은 다음 메시지에서 4개 강제 인용 "
                 "(last_feedback `[FAIL]` 줄 / diagnosis verdict / 매칭 §번호 / 분기 후보+이유). "
                 "— SKILL.md \"§2 진입 전 강제 인용\" 박스.")
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
