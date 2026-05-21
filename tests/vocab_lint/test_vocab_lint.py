from __future__ import annotations

from pathlib import Path
import importlib.util
import sys


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("vocab_lint", _ROOT / "scripts" / "vocab_lint.py")
assert _SPEC and _SPEC.loader
vocab_lint = importlib.util.module_from_spec(_SPEC)
sys.modules["vocab_lint"] = vocab_lint
_SPEC.loader.exec_module(vocab_lint)


def _write_context(root: Path) -> None:
    (root / "CONTEXT.md").write_text(
        "\n".join(
            [
                "**hand-config pipeline**:",
                "_Avoid_: probe 개선 루프 (probe 만이 아님), hand-config 워크플로 (실행 단위 강조 부족), 자가개선 인프라 (인프라 자체와 혼동).",
                "",
                "**수동 config** (= 자동이 커버 못 해 직접 박은 config):",
                '_Avoid_: "즉답"(구 이름), "명시 config"(의도적 설계 어감), "전용 config"(중립 어감).',
                "",
                "**catalog**:",
                '_Avoid_: "batch" (실행 단위 아님), "candidate list" (어휘 떠다님), "cohort" (분류 의도 X).',
                "",
                "**catalog batch run**:",
                '_Avoid_: "batch register" (`/preview` 와 같은 단어라 헷갈림), "bulk preview" (정확하지만 어휘 떠다님), "catalog batch" (단위/동작/흐름 혼동).',
                "",
                "**provider**:",
                '_Avoid_: "Gemini" 단독 (현재 notify path 는 codex), "백엔드" (모호).',
            ]
        ),
        encoding="utf-8",
    )


def test_vocab_lint_flags_high_confidence_avoid_terms(tmp_path: Path) -> None:
    _write_context(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "이 작업은 hand-config 워크플로 문서다.\n"
        "old candidate list 를 참고한다.\n",
        encoding="utf-8",
    )

    rules = vocab_lint.parse_context_rules(tmp_path / "CONTEXT.md")
    findings = vocab_lint.scan_files([target], rules)

    assert [(f.rule.avoid, f.rule.canonical) for f in findings] == [
        ("hand-config 워크플로", "hand-config pipeline"),
        ("candidate list", "catalog"),
    ]


def test_vocab_lint_ignores_low_confidence_implementation_words(tmp_path: Path) -> None:
    _write_context(tmp_path)
    target = tmp_path / ".claude" / "skills" / "hand-config" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "`engine/recognizers/` path 는 구현명이다.\n"
        "catalog batch run 은 canonical 이라 괜찮다.\n"
        "batch tag 도 blanket 금지하지 않는다.\n"
        "Gemini 라우팅 예전 로그처럼 단독 구현 언급은 이 lint 에서 제외한다.\n",
        encoding="utf-8",
    )

    rules = vocab_lint.parse_context_rules(tmp_path / "CONTEXT.md")
    findings = vocab_lint.scan_files([target], rules)

    assert findings == []
