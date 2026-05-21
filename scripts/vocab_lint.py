"""CONTEXT.md 의 _Avoid_ 어휘가 context-feeding 문서로 새지 않았는지 검사.

이 lint 는 고위험 어휘만 막는다. `recognizer`, `batch`, `Gemini` 같은 단어는 코드 경로,
태그, 동적 fail_subkind 로도 정상 사용되므로 blanket grep 하지 않는다.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys


DEFAULT_TARGETS = (
    ".claude/skills",
    "AGENTS.md",
    "prompts",
    "generate/prompt.py",
    "docs/cases",
)

TEXT_SUFFIXES = {".md", ".txt", ".py"}

# CONTEXT.md 의 _Avoid_ 중 context-feeding 문서에 남으면 의미 drift 를 강하게 만드는 표현만.
# 너무 짧거나 구현명으로도 쓰이는 단어(recognizer, batch, Gemini, pending 등)는 제외한다.
HIGH_CONFIDENCE_TERMS = {
    "probe 개선 루프": "hand-config pipeline",
    "hand-config 워크플로": "hand-config pipeline",
    "자가개선 사이클": "hand-config pipeline",
    # "자가개선 인프라" 는 HIGH_CONFIDENCE 에서 제외 — CLAUDE.md §6 / ADR 0003 의
    # *인프라 자체* 를 지칭하는 정당 사용이 많다 (recognizer·batch 와 같은 이유).
    "즉답": "수동 config",
    "명시 config": "수동 config",
    "전용 config": "수동 config",
    "per-slug 손-config": "단일 config",
    "손-config": "수동 config",
    "recognizer 일반화": "플랫폼 config",
    "플랫폼 hand-config": "플랫폼 config",
    "reject-gate recognizer": "거부 필터",
    "사용자 응답": "ack 메시지 / 사용자 DM",
    "interaction 메시지": "ack 메시지",
    "관리자 알림": "OWNER DM",
    "candidate list": "catalog",
    "cohort": "catalog",
    "batch register": "catalog batch run",
    "bulk preview": "catalog batch run",
    "catalog batch": "catalog batch run",
    "fail_category": "fail_kind",
    "error_type": "fail_kind",
    "reject_kind": "fail_kind",
    "정책 거부": "policy_reject 또는 capability_blocked",
    "Gemini 호출": "LLM call_site",
    "LLM API 호출": "LLM call_site",
    "notify timer": "발송창",
    "digest flush": "발송창",
    "collected 재스캔": "posts 저장소",
}

ALLOWLIST_SUBSTRINGS = (
    # Canonical term 자체를 설명하는 SoT 와 lint 구현/테스트는 검사 대상에서 제외.
    "CONTEXT.md",
    "scripts/vocab_lint.py",
    "tests/vocab_lint/",
)

ALLOWLIST_LINE_SUBSTRINGS = (
    # 실제 문서 파일명. 파일명 rename 은 이 lint 의 범위가 아니다.
    "docs/자가개선 인프라 계획.md",
)


@dataclass(frozen=True)
class Rule:
    avoid: str
    canonical: str
    source_canonical: str


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int
    col: int
    rule: Rule
    line: str


def _split_avoid_items(text: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    quote = False
    paren = 0
    for ch in text:
        if ch == '"':
            quote = not quote
        elif ch == "(" and not quote:
            paren += 1
        elif ch == ")" and not quote and paren:
            paren -= 1
        if ch == "," and not quote and paren == 0:
            item = "".join(buf).strip()
            if item:
                items.append(item)
            buf = []
            continue
        buf.append(ch)
    item = "".join(buf).strip()
    if item:
        items.append(item)
    return items


def _term_from_avoid_item(item: str) -> str:
    item = item.strip().rstrip(".")
    m = re.match(r'^"([^"]+)"', item)
    if m:
        return m.group(1).strip()
    return item.split("(", 1)[0].strip()


def parse_context_rules(context_path: Path) -> list[Rule]:
    text = context_path.read_text(encoding="utf-8")
    canonical = ""
    rules: list[Rule] = []
    seen: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\*\*(.+?)\*\*(?:\s*\([^)]*\))?:", line)
        if m:
            canonical = m.group(1).strip()
            continue
        if not line.startswith("_Avoid_:"):
            continue
        for item in _split_avoid_items(line[len("_Avoid_:"):]):
            term = _term_from_avoid_item(item)
            if term in HIGH_CONFIDENCE_TERMS and term not in seen:
                seen.add(term)
                rules.append(
                    Rule(
                        avoid=term,
                        canonical=HIGH_CONFIDENCE_TERMS[term],
                        source_canonical=canonical,
                    )
                )
    return rules


def iter_target_files(root: Path, targets: list[str]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        p = root / target
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(x for x in p.rglob("*") if x.is_file() and x.suffix in TEXT_SUFFIXES)
    return sorted(set(files))


def _is_allowed(path: Path) -> bool:
    normalized = path.as_posix()
    return any(token in normalized for token in ALLOWLIST_SUBSTRINGS)


def scan_files(files: list[Path], rules: list[Rule]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        if _is_allowed(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(token in line for token in ALLOWLIST_LINE_SUBSTRINGS):
                continue
            for rule in rules:
                col = line.find(rule.avoid)
                if col >= 0:
                    if line.startswith("_Avoid_:"):
                        continue
                    if line[col:col + len(rule.canonical)] == rule.canonical:
                        continue
                    findings.append(Finding(path, line_no, col + 1, rule, line.strip()))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--context", default="CONTEXT.md", help="CONTEXT.md path, root-relative")
    parser.add_argument("targets", nargs="*", help="files/dirs to scan; default context-feeding set")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    rules = parse_context_rules(root / args.context)
    files = iter_target_files(root, args.targets or list(DEFAULT_TARGETS))
    findings = scan_files(files, rules)

    for f in findings:
        rel = f.path.relative_to(root)
        print(
            f"{rel}:{f.line_no}:{f.col}: avoid '{f.rule.avoid}' "
            f"-> use '{f.rule.canonical}' (CONTEXT.md: {f.rule.source_canonical})"
        )
        print(f"  {f.line}")

    if findings:
        print(f"[vocab_lint] FAIL: {len(findings)} avoid-term hit(s)", file=sys.stderr)
        return 1
    print(f"[vocab_lint] OK: scanned {len(files)} file(s), {len(rules)} high-confidence rule(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
