"""@heuristic 데코레이터 — probe 안의 순수 휴리스틱 함수 표시.

표시된 함수는:
- 외부 의존 X (네트워크·chromium·디스크 I/O 없이 입력→결정적 출력)
- `tests/probe_heuristics/test_<함수명>.py` 의 unit fixture 가 있어야 함
- `scripts/probe_smoke.py --stage 5` 가 fixture 누락을 coverage 검사로 감지

새 휴리스틱 추가 워크플로:
1. probe/<file>.py 에 함수 추가 + `@heuristic` 데코레이터
2. tests/probe_heuristics/test_<함수명>.py 에 fixture 작성 (`run() -> list[(name, ok, msg)]`)
3. `python scripts/probe_smoke.py` 통과 확인

데코레이터는 함수 동작을 바꾸지 않는다 — import 시 HEURISTICS 레지스트리에만 등록.
"""
from __future__ import annotations

from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable[..., object])

# (module, qualname) 튜플 리스트 — probe_smoke stage 5 가 읽어 coverage 검사.
HEURISTICS: list[tuple[str, str]] = []


def heuristic(func: F) -> F:
    """순수 휴리스틱 마커. 함수 동작 그대로, 레지스트리에만 추가."""
    HEURISTICS.append((func.__module__, func.__qualname__))
    return func


def loaded_heuristics() -> list[tuple[str, str]]:
    """현재 HEURISTICS 스냅샷. 호출 전에 probe.* 모듈들이 import 되어야 채워짐."""
    return list(HEURISTICS)
