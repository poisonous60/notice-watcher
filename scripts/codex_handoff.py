"""codex 위임 프롬프트 빌더 + 런처 (#2 multi-skill, #4 entry=Claude/middle=codex).

ADR 0008: hand-config 등 *중간 orchestration* 을 codex CLI 로 위임 (Claude 토큰 0).
진입(triage entry)·검토(diff)·commit/push/배포 는 Claude 가 이 밖에서 한다.

이 모듈은 위임 프롬프트를 *생성* 한다 — HARD-STOP 제약(commit/push/배포 금지, push 전 STOP)을
모든 프롬프트에 강제로 박는다 (codex 가 멋대로 commit·배포 못 하게). `--launch` 시
scripts/codex_run.ps1 로 보이는 창에서 실행.

Usage:
  python scripts/codex_handoff.py handconfig --slug <slug> --url <url> [--board <b>] [--note <n>] [--launch]
  python scripts/codex_handoff.py bugfix --title <t> --repro <cmd> [--location <file:line>] [--launch]
  python scripts/codex_handoff.py generic --task-file <f> [--launch]

생성물: output/codex_<kind>_<tag>_prompt.txt (+ --launch 시 보이는 창 + output/..._prompt.result.md)
완료 감지: python scripts/codex_watch.py <result_file> --loop
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

# 모든 위임 프롬프트에 박는 공통 제약 — codex 가 commit/배포 못 하게 (Claude 가 검토 후 한다).
HARD_STOP = """\
## 절대 금지 (HARD STOP — 사람/Claude 검토 후 배포)
- `git add` / `git commit` / `git push` 금지.
- N100 ssh 으로 systemctl / git pull / 배포 금지. (단 N100 probe artifact 의 *read-only* tar pull 은 허용 — 아래 §게이트 1.)
- 변경은 working tree 에 남겨둬라. commit·배포는 검토 후 Claude 가 한다.
- triage 큐(output/triage_queue.*)·이미 등록된 configs/·poll_state/ 는 작업 대상 외엔 건드리지 마라.
- `scripts/cases_index.py` 실행 / `--backfill-db output/cases.sqlite3` / `docs/cases/INDEX.md` 갱신 **금지** — 공유 인덱스·DB 는 Claude 가 청크 수집 후 *직렬* backfill 한다. 병렬 codex 가 동시에 backfill 하면 SQLite lock race 로 case_runs row 가 유실된다. 너는 `docs/cases/<slug>.md` 파일만 만든다 (INDEX·DB 는 Claude 몫).

## 회피 게이트 (ALLOW-LIST 가 일반화 회피 핑계 X — 2026-05-24 박음)

ALLOW-LIST 는 *편집 권한 제한*이지 *분석 권한 제한*이 아니다. 다음 4종 punt 패턴은 task 위반 — 위반 시 Claude 가 review 단계에서 reject (worktree merge X).

**게이트 1 — "probe artifact 없음" defer 금지**
- task 에 `ssh aaaa@n100-noticewatcher 'tar czf - ...'` 류 N100 probe pull 명령이 있는데 *시도하지 않고* `no_change` defer = 위반.
- 다른 dev box 환경 (예: 사용자가 직접 본 슬러그 등) 에서 pull 이 명시 안 됐어도 `triage.py pull --slug <slug>` 또는 N100 tar pull 시도 1회 의무. 그 다음에도 artifact 못 받으면 그제서야 defer + 그 사실 case body 에 명시 ("ssh tar pull 시도 → 결과: <stderr 1줄>").
- 기존 등록된 다른 board 로 *URL 을 바꿔* 등록하는 건 **scope 오염** — 절대 금지 (사용자가 요청한 URL 의 board 만 등록).

**게이트 2 — 일반화 신호 발견 시 case body 에 의무 분석**
- 같은 청크 안에 2+ slug 가 같은 패턴(URL 누락 파라미터·JS detail 함수·TLS handshake 실패·platform CMS 동형 등) 보이면 → 일반화 후보 = case body `## 일반화 후보` 섹션에 다음 4줄 명시:
  - **패턴**: 1줄 (예: "KR egov: 제출 URL 에 `menuid`/`menuCd`/`mId` 누락 시 auth_redirect/empty shell")
  - **신호**: 같은 청크 내 같은 패턴 slug 목록
  - **fix layer 후보**: C (probe heuristic) / B (few-shot) / A (system prompt) / F (engine) 중
  - **이번 chunk 박을까**: yes (같은 PR 에 박음) / no (ALLOW-LIST 밖, escalate 필요)
- "사이트별 메뉴 매핑이라 일반화 X" 같은 1줄 punt 는 **2+ slug 동일 패턴인 경우 부적합** — 그건 *정의상* 일반화 가능. 진짜 site-specific 인 사유 (예: "이 사이트 전용 ID 체계 + 다른 사이트 0건") 면 그 1줄 정당화.

**게이트 3 — ALLOW-LIST 밖 필요하면 STOP + escalate (defer 아님)**
- 게이트 2 의 fix 가 ALLOW-LIST 밖 (engine/probe/prompts/recognizer 등) 이면 *그 패턴은 별도 chunk 로* Claude 가 처리. 너는:
  - 분석은 case body §일반화 후보 에 완전히 적기 (다음 chunk 가 그걸로 시작하게)
  - 단일 site config 는 ALLOW-LIST 안에서 작업 진행 (둘 다 하는 게 정상)
  - 결과 보고에 `## escalate (allow-list 밖 일반화 후보)` 섹션으로 모아 명시
- 단순히 "allow-list 밖이라 안 함" 1줄 = 위반. 후속 chunk 에 정보 전달 안 됨.

**게이트 4 — `no_change`/`deferred` outcome 정당화 의무**
- `outcome: no_change` 박을 때 case body 에 다음 3개 명시:
  - 시도한 정확한 작업 (probe pull 결과 / register 결과 1줄)
  - 정확한 차단 신호 (alert 문구 / HTTP 코드 / traceback 1줄 verbatim)
  - 진짜 해결 경로 (예: "사용자 catalog 수정 필요" / "engine TLS 강화 필요" — 무엇이 와야 풀리나)
- "config 작성 보류" 만 적고 차단 신호 verbatim 없으면 위반.

## 배포 환경 의무 (configs/ 작성 시 N100 = Linux headless 서버)

- `strategy: "playwright_html"` config 에 **`"headless": false` 박지 마라**. N100 (운영 서버) 는 X server 없는 Linux 데몬이라 headed Chrome 이 `TargetClosedError: Missing X server or $DISPLAY` 로 즉시 죽는다. dev 박스 (Windows) 에선 통과하지만 N100 배포 시 100% 실패. (2026-05-24 kruniv-cap 배치에서 한 차례 박힘.)
- anti-bot 우회는 **stealth library 단독 사용** (이미 `engine/strategies/playwright_html.py` 가 모든 context 에 `playwright_stealth` 자동 적용). 그래도 부족하면 `storage_state_path` (로그인 세션 재사용) 또는 별도 어댑터 — `headless: false` 는 선택지가 아니다.
- `headless` 키 생략하면 default = `true` (playwright_html.py:83). 명시 안 하면 안전.

## 마무리 (이 블록을 마지막 메시지로)
- 무엇을 진단/수정했나 (root-cause 1-2줄)
- 작성/수정한 파일 목록
- 검증 결과 (probe_smoke / 재현 명령 등 — pass/fail 그대로)
- **일반화 후보 escalate 모음** (있으면 — §게이트 3)
- 사람이 배포 전 확인할 점
"""

PLAYBOOK = """\
플레이북 = `.claude/skills/hand-config/SKILL.md` (`.agents/skills/hand-config` junction 으로 로드) + `AGENTS.md` §6.
그 절차를 따른다. 추측 X — 각 단계 산출물 확인하며 순서대로. CONTEXT.md 어휘를 SoT 로 (avoid 단어 금지)."""


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "task"


def build_handconfig(slug: str, url: str, board: str | None, note: str | None) -> str:
    probe_dir = f"output/probe/{slug}/"
    has_probe = (ROOT / "output" / "probe" / slug).is_dir()
    probe_line = (
        f"- 기존 probe 산출물 있음: `{probe_dir}` — 우선 읽어라 (재-probe 불필요할 수 있음)."
        if has_probe
        else f"- probe 산출물 없음 — 필요 시 `python scripts/probe.py \"{url}\"` (felt 느리면 --lite)."
    )
    return f"""너는 notice-watcher dev 박스에서 hand-config orchestration 을 수행하는 Codex 에이전트다.
{PLAYBOOK}

## 대상 (단일 board)
- slug: {slug}
- url: {url}
- board: {board or "(미지정 — probe/url 로 판단)"}
- 마커: output/poll_state/{slug}.FAILED.json (있으면 사유 확인)
{probe_line}
{f"- 힌트: {note}" if note else ""}

## 목표 (SKILL.md §0b preflight → §1 진단 → §2 분기 → §5 검증, commit 전까지)
1. preflight (§0b) — 이미 고쳐졌나 / 옆 작업이 큐 stale 화했나.
2. §1~§2 진단 (강제 인용 6개) → 추론 개선(probe/schema/prompt) 1순위, 안 되면 수동 config(단일/플랫폼)·손어댑터.
3. config 작성 + 검증: `python scripts/probe_smoke.py` 또는 make_adapter 스모크로 posts_nonempty 통과.
4. `docs/cases/{slug}.md` 작성 (그 파일만 — `cases_index.py`/`--backfill-db`/INDEX.md 는 돌리지 마라, Claude 직렬).
5. robots/polite_sleep 정책 준수 (docs/크롤링 지침.md).

{HARD_STOP}"""


def build_handconfig_batch(members: list[dict], group_key: str) -> str:
    """한 세션이 *겹침 없는* 여러 slug 를 순차 처리 (같은 플랫폼/host = 공유 fix 1번).

    members: [{slug, url, board}, ...]. group_key: 이 청크의 응집 근거 (host 또는 platform).
    """
    rows = "\n".join(
        f"  {i + 1}. slug={m['slug']}  url={m['url']}  board={m.get('board') or '?'}"
        f"  probe={'있음' if (ROOT / 'output' / 'probe' / m['slug']).is_dir() else '없음'}"
        for i, m in enumerate(members)
    )
    return f"""너는 notice-watcher dev 박스에서 hand-config orchestration 을 수행하는 Codex 에이전트다.
{PLAYBOOK}

## 이 세션의 청크 ({len(members)} slug — 응집 근거: {group_key})
이 slug 들은 *같은 플랫폼/host* 라 fix surface 가 겹친다. **한 세션에서 함께** 처리해라 —
공유 수정(recognizer/engine/probe)은 *한 번만* 하고 모든 멤버에 적용 (track B 일관).
다른 청크와 파일 충돌 없게, 이 청크 멤버의 slug 파일 + 이 플랫폼 recognizer 만 건드려라.

{rows}

## 절차 (각 slug 에 SKILL.md §0b→§1→§2→§5, 단 공유 fix 는 1회)
1. 첫 멤버로 §0b preflight + §1~§2 진단 → 공유 root-cause 파악.
2. 공유 수정(추론 개선 1순위: probe/schema/prompt/recognizer)을 *한 번* 박고, 나머지 멤버는 그 수정으로 재검증.
3. 멤버별 `configs/<slug>.json` (필요 시) + `docs/cases/<slug>.md`.
4. 검증: `python scripts/probe_smoke.py --stage 3 --stage 5` PASS + 각 멤버 make_adapter 스모크 posts_nonempty.
5. 거기까지만 — `cases_index.py`/`--backfill-db`/INDEX.md 는 돌리지 마라 (병렬 backfill = SQLite lock race, row 유실). Claude 가 청크 수집 후 직렬 backfill 한다.

{HARD_STOP}
- **공유 인덱스(INDEX.md·cases.sqlite3·사이트별 기록.md)·git commit 은 Claude 가 직렬 처리** — 너는 청크 멤버 파일만 만들고 STOP. (병렬 세션 레이스 방지)"""


def build_bugfix(title: str, repro: str, location: str | None) -> str:
    return f"""너는 notice-watcher dev 박스에서 bug-fix workflow 를 수행하는 Codex 에이전트다.
이건 hand-config 아님 — 코드 버그 (CONTEXT.md: bug-fix workflow, rc<0 .BUG). 추측 X — 재현→root-cause→수정→테스트.

## 버그
- 제목: {title}
{f"- 위치 단서: {location}" if location else ""}
- 재현 명령: `{repro}`

## 목표 (순서대로)
1. 재현 — 위 명령으로 실제 에러/traceback 띄워라. 전체 traceback 캡쳐.
2. root-cause — 어디서 왜 터지는지 규명 (최소 변경 지점).
3. 수정 — 최소 변경. 인접 코드 "개선" 금지 (CLAUDE.md surgical changes).
4. 테스트 — 재현 명령이 통과하는지 + `python scripts/probe_smoke.py --stage 3 --stage 5` PASS (회귀 0).

{HARD_STOP}"""


def build_generic(task: str) -> str:
    return f"""너는 notice-watcher dev 박스에서 작업하는 Codex 에이전트다.
{PLAYBOOK}

## 작업
{task}

## 검증
- 변경했으면 `python scripts/probe_smoke.py --stage 3 --stage 5` PASS 확인 (회귀 0).
- 어휘는 CONTEXT.md SoT — avoid 단어 쓰지 마라. `python scripts/vocab_lint.py` 통과.

{HARD_STOP}"""


def write_prompt(kind: str, tag: str, body: str) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / f"codex_{kind}_{_slugify(tag)}_prompt.txt"
    path.write_text(body, encoding="utf-8")
    return path


def launch(prompt_path: Path, title: str,
           profile: str = "", reasoning: str = "",
           worktree: bool = False, worktree_tag: str = "") -> Path:
    """codex_run.ps1 로 보이는 창에서 실행. 결과 파일 경로 반환.

    profile/reasoning = 속도 노브 (codex_run.ps1 로 전달). profile='light' = gpt-5.4-mini
    + low reasoning (기계적 청크 권장). reasoning='low'|'minimal' = default 모델 사고만 축소.
    worktree=True → codex 가 HEAD 에서 분리된 git worktree+branch(codex-wt/<tag>) 에서 실행 →
    edit 격리(병렬 codex/다중 세션 same-tree race 0). rc=0 시 변경이 그 branch 에 커밋됨 →
    Claude 가 `git diff main..codex-wt/<tag>` review + `git merge` 후 `git worktree remove`.
    """
    result = prompt_path.with_suffix(".result.md")
    ps1 = ROOT / "scripts" / "codex_run.ps1"
    cmd = ["powershell", "-NoProfile", "-File", str(ps1),
           "-PromptFile", str(prompt_path), "-ResultFile", str(result), "-Title", title]
    if profile:
        cmd += ["-CodexProfile", profile]
    if reasoning:
        cmd += ["-Reasoning", reasoning]
    if worktree:
        cmd += ["-Worktree"]
        if worktree_tag:
            cmd += ["-WorktreeTag", worktree_tag]
    subprocess.run(cmd, check=True)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="kind", required=True)

    p_hc = sub.add_parser("handconfig", help="hand-config orchestration 위임")
    p_hc.add_argument("--slug", required=True)
    p_hc.add_argument("--url", required=True)
    p_hc.add_argument("--board")
    p_hc.add_argument("--note")

    p_bf = sub.add_parser("bugfix", help="bug-fix workflow 위임")
    p_bf.add_argument("--title", required=True)
    p_bf.add_argument("--repro", required=True)
    p_bf.add_argument("--location")

    p_ge = sub.add_parser("generic", help="자유 작업 위임")
    p_ge.add_argument("--task-file", required=True, help="작업 설명 파일 (UTF-8)")

    for p in (p_hc, p_bf, p_ge):
        p.add_argument("--launch", action="store_true", help="codex_run.ps1 로 보이는 창에서 즉시 실행")
        p.add_argument("--profile", default="",
                       help="codex 속도 노브: 'light' = gpt-5.4-mini+low (기계적 청크 권장)")
        p.add_argument("--reasoning", default="",
                       help="codex reasoning_effort: low|minimal (default 모델 사고 축소)")
        p.add_argument("--worktree", action="store_true",
                       help="격리 git worktree+branch(codex-wt/<tag>) 에서 실행 — 병렬/다중세션 same-tree race 0. "
                            "rc=0 시 변경이 branch 에 커밋 → Claude 가 review+merge")
        p.add_argument("--worktree-tag", default="",
                       help="worktree branch/dir 태그 (기본: title)")

    args = ap.parse_args(argv)

    if args.kind == "handconfig":
        body, tag, title = build_handconfig(args.slug, args.url, args.board, args.note), args.slug, f"hand-config: {args.slug}"
    elif args.kind == "bugfix":
        body, tag, title = build_bugfix(args.title, args.repro, args.location), args.title, f"bugfix: {args.title}"
    else:
        task = Path(args.task_file).read_text(encoding="utf-8")
        body, tag, title = build_generic(task), Path(args.task_file).stem, "generic"

    path = write_prompt(args.kind, tag, body)
    print(f"[codex_handoff] prompt written: {path}")

    if getattr(args, "launch", False):
        result = launch(path, title, profile=getattr(args, "profile", ""),
                        reasoning=getattr(args, "reasoning", ""),
                        worktree=getattr(args, "worktree", False),
                        worktree_tag=getattr(args, "worktree_tag", "") or tag)
        print(f"[codex_handoff] launched. result file: {result}")
        print(f"  완료 감지: python scripts/codex_watch.py {result} --loop")
    else:
        print(f"  실행: pwsh scripts/codex_run.ps1 -PromptFile {path} -Title \"{title}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
