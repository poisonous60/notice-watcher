"""generate.gemini._parse_json_loose — json_repair 2차 fallback 회귀 차단.

govinfo job#1702 (2026-05-24) 같은 codex 큰 응답의 `,` delimiter 누락을 회수해야 한다.
중요: repair 결과가 dict/list 이고 비어있지 않을 때만 채택 — 모델 환각으로 garbage 들어왔을 때
빈 dict 가 schema validate 를 통과해버리지 않도록.
"""
from __future__ import annotations

import sys
from pathlib import Path


def run() -> list[tuple[str, bool, str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from generate.gemini import _parse_json_loose
    from generate.llm_base import LLMParseError

    cases: list[tuple[str, bool, str]] = []

    # 1. 정상 JSON — 1차 json.loads 가 처리. repair 안 탐.
    try:
        r = _parse_json_loose('{"a": 1, "b": 2}')
        ok = r == {"a": 1, "b": 2}
        cases.append(("normal_json", ok, f"r={r!r}"))
    except Exception as e:  # noqa: BLE001
        cases.append(("normal_json", False, f"raised {e!r}"))

    # 2. ```json``` fence — 기존 path 보존.
    try:
        r = _parse_json_loose('```json\n{"a": 1}\n```')
        cases.append(("json_fence", r == {"a": 1}, f"r={r!r}"))
    except Exception as e:  # noqa: BLE001
        cases.append(("json_fence", False, f"raised {e!r}"))

    # 3. prose 둘러싼 JSON — 1차 fallback (outer brace cut) 처리.
    try:
        r = _parse_json_loose('here is the config: {"a": 1} done')
        cases.append(("outer_brace_cut", r == {"a": 1}, f"r={r!r}"))
    except Exception as e:  # noqa: BLE001
        cases.append(("outer_brace_cut", False, f"raised {e!r}"))

    # 4. 빠진 `,` delimiter — govinfo job#1702 핵심 케이스. repair 가 회수해야 함.
    broken_comma = (
        '{"version":1,"site":"www.govinfo.gov","strategy":"httpx_html",'
        '"list":{"url_template":"https://x/{board}","pagination":{"kind":"none"}'
        '"row_selector":"div.row"}}'  # ← `}` 와 `"row_selector"` 사이 `,` 누락
    )
    try:
        r = _parse_json_loose(broken_comma)
        ok = isinstance(r, dict) and r.get("version") == 1 and r.get("strategy") == "httpx_html"
        cases.append(("repair_missing_comma", ok, f"r keys={list(r.keys()) if isinstance(r, dict) else r!r}"))
    except LLMParseError as e:
        cases.append(("repair_missing_comma", False, f"LLMParseError: {e}"))

    # 5. trailing comma — repair 가 정리.
    try:
        r = _parse_json_loose('{"a": 1, "b": 2,}')
        cases.append(("repair_trailing_comma", r == {"a": 1, "b": 2}, f"r={r!r}"))
    except LLMParseError as e:
        cases.append(("repair_trailing_comma", False, f"LLMParseError: {e}"))

    # 6. 닫히지 않은 `}` — repair 가 닫음.
    try:
        r = _parse_json_loose('{"a": 1, "b": {"c": 2}')  # outer `}` 누락
        ok = isinstance(r, dict) and r.get("a") == 1 and isinstance(r.get("b"), dict)
        cases.append(("repair_unclosed_brace", ok, f"r={r!r}"))
    except LLMParseError as e:
        cases.append(("repair_unclosed_brace", False, f"LLMParseError: {e}"))

    # 7. 완전 garbage — repair 가 "" 반환. 빈 결과는 채택 X, LLMParseError raise.
    try:
        r = _parse_json_loose("totally not json at all")
        cases.append(("garbage_rejects", False, f"unexpectedly returned {r!r}"))
    except LLMParseError:
        cases.append(("garbage_rejects", True, "raised LLMParseError as expected"))

    # 8. 빈 dict 만 나오는 케이스도 거부 — repair 가 `{}` 만 던지면 schema 통과 위험.
    try:
        r = _parse_json_loose("{}")  # 정상 `{}` 는 1차 json.loads 가 dict 반환 — 이건 통과.
        cases.append(("empty_dict_from_strict_loads", r == {}, f"r={r!r}"))
    except LLMParseError as e:
        cases.append(("empty_dict_from_strict_loads", False, f"raised {e}"))

    # 9. repair 가 빈 dict 만 만들어내는 garbage — 거부돼야 함.
    # (json_repair 가 `"   "` 같은 거에 `{}` 만들어 줄 수 있음. dict 라도 비어있으면 채택 X 로 했음.)
    try:
        r = _parse_json_loose("   ")
        cases.append(("blank_rejects", False, f"unexpectedly returned {r!r}"))
    except LLMParseError:
        cases.append(("blank_rejects", True, "raised LLMParseError as expected"))

    return cases


if __name__ == "__main__":
    results = run()
    failed = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        print(f"  {'PASS' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print(f"\n{len(failed)} FAILED")
        sys.exit(1)
    print(f"\n{len(results)} passed")
