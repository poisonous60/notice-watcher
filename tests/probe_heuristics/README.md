# probe heuristic unit tests

`probe/` 의 순수(외부 의존 X) 휴리스틱 함수들 단위 검증.

`scripts/probe_smoke.py --stage 5` 가 이 디렉토리의 `test_*.py` 를 자동 발견·실행 + `@heuristic` 데코레이터 등록 함수 ↔ fixture coverage 검증.

## 새 휴리스틱 추가 시

1. `probe/extract.py` (또는 `probe/hydration.py` 등) 에 함수 추가 + **`@heuristic` 데코레이터**:
   ```python
   from probe._heuristic import heuristic

   @heuristic
   def my_new_heuristic(html: str) -> str:
       ...
   ```
2. 이 디렉토리에 `test_<함수명>.py` 하나 추가:
   ```python
   def run() -> list[tuple[str, bool, str]]:
       """[(case_name, ok: bool, msg_if_fail: str), ...]"""
       from probe.extract import my_new_heuristic
       cases = []
       cases.append(("typical_input", my_new_heuristic("x") == "expected", ""))
       cases.append(("edge_empty", my_new_heuristic("") is None, ""))
       return cases
   ```
3. 끝. `probe_smoke.py` 가 다음 실행에서 자동 picked up + coverage 검증 통과.

## 규칙

- `run()` 만 반드시 정의. 다른 함수/상수는 자유.
- 순수 함수만. 네트워크·chromium·디스크 I/O 가 필요한 함수는 여기서 다루지 않음 (`@heuristic` 도 부착하지 않음).
- 한 함수당 1 파일 권장.
- 합본은 파일 안에 `covers = ["funcA", "funcB"]` 모듈 변수 선언 (private `_` 접두사 제외하고):
  ```python
  covers = ["find_list_in_json", "looks_like_row", "looks_rowish"]
  def run(): ...
  ```
  파일명 컨벤션 `test_X_and_Y.py` 도 인식되나 `covers` 가 더 명시적.
- 케이스 이름 = snake_case, 짧게. 실패 시 출력에 직접 나옴.

## coverage 검증

`scripts/probe_smoke.py --stage 5` 가 실행마다:
1. `probe/*` 의 `@heuristic` 데코레이터 등록 목록 수집
2. `tests/probe_heuristics/test_*.py` 파일들 import → `covers` 또는 파일명에서 함수 이름 추출
3. 차집합 = 누락 휴리스틱 → FAIL + 누락 함수 출력
