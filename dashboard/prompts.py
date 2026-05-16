"""Skill 트리거 프롬프트 빌더.

각 함수는 사용자가 클립보드에 복사한 뒤 VSCode Claude Code 창에 붙여넣을 텍스트를 반환한다.
키워드(`손 config 작성`, `report-triage` 등)는 해당 SKILL.md 의 트리거에 맞춰 잡힘 — Claude 가
자동으로 매칭 스킬을 실행.

복사 후 사용자는 [Enter] 만 누르면 됨.
"""
from __future__ import annotations

from typing import Optional


def hand_config_for_url(*, url: str, slug: Optional[str] = None,
                        fail_reason: Optional[str] = None,
                        job_id: Optional[int] = None) -> str:
    lines = ["다음 사이트 손 config 작성해줘 (skill: hand-config 모드 A).", ""]
    lines.append(f"URL: {url}")
    if slug:
        lines.append(f"slug: {slug}")
    if fail_reason:
        lines.append(f"실패 사유: {fail_reason}")
    if job_id is not None:
        lines.append(f"관련 잡: #{job_id}")
    lines.append("")
    lines.append("두 트랙 *동시* 진행 (한쪽 막는 게이트 X):")
    lines.append("  - 트랙 A (사용자 향 — 사이트 즉시 작동): 손-config / 손어댑터 작성 → configs/ → N100 배포.")
    lines.append("  - 트랙 B (미래 향 — 같은 패턴 자동 처리): 진단 중 분기 2a (인식기 확장) / 2b (--article-url) / "
                 "2c (probe 휴리스틱 + retry feedback hint) / 2d (probe artifact 수정) 후보 한 줄씩 enumerate. "
                 "매칭 있으면 그 자리도 같은 PR 에 박음. 매칭 0이면 case 파일에 이유 한 줄.")
    return "\n".join(lines)


def hand_config_redo_slug(*, slug: str, url: Optional[str] = None) -> str:
    lines = ["다음 사이트 손 config 재작성해줘 (skill: hand-config).", ""]
    lines.append(f"slug: {slug}")
    if url:
        lines.append(f"URL: {url}")
    lines.append(f"현재 config: configs.snapshot/{slug}.json (참고용 — dev 의 configs/ 가 진본)")
    lines.append("")
    lines.append("문제 진단 → 수정 → fetch 확인 → 배포.")
    return "\n".join(lines)


def hand_config_triage_queue(*, failed_slugs: list[str]) -> str:
    n = len(failed_slugs)
    lines = [f"FAILED 큐 일괄 처리해줘 (skill: hand-config 모드 B — triage). 총 {n}건.", ""]
    lines.append("대상 slug:")
    for s in failed_slugs:
        lines.append(f"- {s}  (output/snapshot/poll_state/{s}.FAILED.json)")
    lines.append("")
    lines.append("각 항목 두 트랙 *동시* 진행 (한쪽 막는 게이트 X):")
    lines.append("  - 트랙 A (사용자 향 — 사이트 즉시 작동): 손-config / 손어댑터 작성 → configs/ → N100 배포.")
    lines.append("  - 트랙 B (미래 향 — 같은 패턴 자동 처리): 진단 중 2a (인식기 확장) / 2b (--article-url) / "
                 "2c (probe 휴리스틱 + retry feedback hint) / 2d (probe artifact 수정) 후보 한 줄씩 enumerate. "
                 "매칭 있으면 같은 PR 에 박음. 0 이면 case 파일에 이유.")
    lines.append("우선순위 정렬 → 각 항목 처리 → 배포.")
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


def diagnose_slug(*, slug: str) -> str:
    """skill 아님 — 그냥 자연어 진단 요청. 사용자가 인터랙티브하게 파고들고 싶을 때."""
    return (
        f"slug `{slug}` 진단해줘.\n"
        f"- `python scripts/inspect_subs.py diagnose {slug}` 결과 살펴보고\n"
        f"- 필요하면 `python scripts/inspect_subs.py fetch {slug}` 로 fetch 결과 확인\n"
        f"- 깨졌으면 손 config 재작성 (hand-config skill) 까지 진행."
    )
