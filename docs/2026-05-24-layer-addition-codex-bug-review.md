## 1. 종합 verdict

- verdict: **버그 확인**
- 핵심 버그는 `scripts/poll.py` 의 lastmod observe task 가 실제로 poll latency 를 최대 5초까지 늘릴 수 있는 경로다.
- 데이터 손상 버그는 확인하지 못했다.
- `engine/digest.py` 의 새 digest key 2개는 현재 확인한 소비자 기준 strict shape validation 을 깨는 경로가 없다.
- `scripts/register.py` reject 문구 변경은 기존 `board_shape` fail 분류 문자열을 보존한다.

검토 대상:

| 파일 | 범위 | 판정 |
|---|---:|---|
| `engine/_mdr_candidates.py` | 전체 | 구체 버그 없음 |
| `engine/digest.py` | 변경부 포함 전체 흐름 | 구체 버그 없음 |
| `scripts/poll.py` | 변경부 포함 관련 흐름 | MED 1건, LOW 1건 |
| `scripts/register.py` | `_board_shape_check` reject message 부근 | 구체 버그 없음 |

품질 기준 대응:

| 기준 | 결과 |
|---|---|
| no regressions | lastmod observe latency regression 가능 경로 있음 |
| no data corruption | 확인된 데이터 손상 없음 |
| correctness bugs only | latency/compute 경로만 보고, 추정성 race 는 finding 에서 제외 |

## 2. 파일별 버그 표

| file:line | 카테고리 | 심각도(HIGH/MED/LOW/INFO) | 설명 |
|---|---|---:|---|
| `scripts/poll.py:301` | async/latency | MED | `_check_sitemap_lastmod(st)` 를 `asyncio.create_task` 로 시작한다. 여기까지만 보면 fetch 와 병렬이다. |
| `scripts/poll.py:305` | async/latency | MED | 실제 list fetch 는 `async with sem` 안에서 `_fetch_one(...)` 로 수행된다. |
| `scripts/poll.py:314` | async/latency | MED | fetch 가 끝난 뒤 `obs = await lastmod_task` 를 무조건 기다린다. lastmod 요청이 아직 끝나지 않았으면 observe-only 가 아니라 wall-clock latency 에 붙는다. |
| `scripts/poll.py:125` | async/latency | MED | lastmod HTTP client timeout 이 `5.0` 이다. fetch 가 1초에 끝나고 sitemap 이 timeout 까지 걸리면 사이트 1개 처리 시간이 약 5초까지 늘어날 수 있다. |
| `scripts/poll.py:125` | compute/network | LOW | `Range: bytes=0-2047` 를 보내지만 응답 body 크기를 코드에서 강제하지 않는다. 서버가 Range 를 무시하고 큰 sitemap 을 주면 `r.text` 가 전체 응답을 디코딩한다. |
| `scripts/poll.py:128` | compute/network | LOW | `_LASTMOD_RE.search(r.text)` 가 응답 전체 문자열을 대상으로 돈다. Range 미준수 서버에서는 observe helper 가 의도보다 큰 parse 비용을 낼 수 있다. |
| `scripts/poll.py:320` | data growth | INFO | `output/sitemap_lastmod_log.jsonl` 에 append 만 있고 rotation 이 없다. 즉시 correctness bug 는 아니지만 운영 데이터 증가 지점이다. |
| `scripts/poll.py:323` | state | INFO | `sitemap_lastmod_last_seen` 은 lastmod 관측값이 있을 때만 state 에 저장된다. fetch 실패와 독립적으로 기록될 수 있지만 observe-only 상태키라 데이터 손상 경로는 확인되지 않았다. |

`engine/_mdr_candidates.py` 이상 없음:

| file:line | 확인 내용 | 판정 |
|---|---|---|
| `engine/_mdr_candidates.py:40` | public helper 는 `mdr_candidate_xpaths(html, top_k=10, encoding="utf8")` 하나다. | OK |
| `engine/_mdr_candidates.py:49` | `str` 입력을 지정 encoding 으로 encode 한다. | OK |
| `engine/_mdr_candidates.py:51` | `lxml.etree.HTMLParser(..., recover=True)` 를 사용한다. | OK |
| `engine/_mdr_candidates.py:55` | parser fallback 도 recover parser 다. | OK |
| `engine/_mdr_candidates.py:57` | parse 실패 시 빈 list 를 반환한다. measurement field 이므로 fail-soft 방향은 맞다. | OK |
| `engine/_mdr_candidates.py:61` | text node 기반 후보 ancestor 를 센다. | OK |
| `engine/_mdr_candidates.py:76` | 상위 후보만 `top_k` 만큼 반환한다. | OK |
| `engine/_mdr_candidates.py:84` | `row_with_link` 는 직접 자식 중 link 포함 여부를 센다. | OK |
| `engine/_mdr_candidates.py:89` | 반환 schema 는 `{xpath, score, child_count, row_with_link}` 이다. | OK |

`engine/digest.py` 이상 없음:

| file:line | 확인 내용 | 판정 |
|---|---|---|
| `engine/digest.py:25` | `engine._mdr_candidates` 신규 import. | OK |
| `engine/digest.py:34` | `_mdr_candidates_safe` helper 는 optional html 을 받는다. | OK |
| `engine/digest.py:38` | 내부에서 `mdr_candidate_xpaths(html)` 만 호출한다. | OK |
| `engine/digest.py:40` | 예외를 빈 list 로 누른다. measurement-only field 라면 digest 생성 실패 방지 목적에 부합한다. | OK |
| `engine/digest.py:48` | `_sitemap_only_fit_signal` 은 sitemap 후보 list 를 signal dict 로 요약한다. | OK |
| `engine/digest.py:51` | 후보가 30개 미만이면 `enough_volume=False` 로 조기 반환한다. | OK |
| `engine/digest.py:66` | URL parse 실패는 해당 URL 만 skip 한다. | OK |
| `engine/digest.py:83` | ratio 계산은 `n >= 30` 이후라 0 division 경로가 없다. | OK |
| `engine/digest.py:450` | digest 는 일반 dict literal 이다. | OK |
| `engine/digest.py:471` | 기존 `sitemap_candidates` key 는 유지된다. | OK |
| `engine/digest.py:475` | 신규 `mdr_candidates` 는 별도 key 로 추가된다. | OK |
| `engine/digest.py:478` | 신규 `sitemap_only_fit_signal` 은 별도 key 로 추가된다. | OK |
| `prompts/config_writer.system.txt:94` | prompt 는 `sitemap_candidates` 를 읽으라고 지시한다. 신규 key 를 강제로 읽는 변경은 아니다. | OK |

digest shape regression 검토:

| 근거 | 결론 |
|---|---|
| `engine/digest.py:450` 의 digest 는 strict dataclass/schema 가 아니라 dict literal 이다. | extra key 추가 자체가 Python level break 를 만들지 않는다. |
| `prompts/config_writer.system.txt:94` 는 기존 `sitemap_candidates` 만 설명한다. | prompt 동작 변화는 직접 발생하지 않는다. |
| repo 검색에서 `mdr_candidates` / `sitemap_only_fit_signal` 소비자는 현재 `engine/digest.py` 변경부 외 확인되지 않았다. | shape validator break 는 확인되지 않았다. |

`scripts/register.py` 이상 없음:

| file:line | 확인 내용 | 판정 |
|---|---|---|
| `scripts/register.py:621` | comment 는 sitemap 후보를 자동 retry 하지 않는다고 명시한다. | OK |
| `scripts/register.py:623` | `digest.get("sitemap_candidates") or []` 로 후보를 읽는다. | OK |
| `scripts/register.py:625` | 후보가 dict 일 때만 URL 을 뽑는다. | OK |
| `scripts/register.py:627` | 안내 URL 은 상위 3개로 제한된다. | OK |
| `scripts/register.py:628` | 안내 문구만 추가한다. 자동 등록/자동 retry 로직은 없다. | OK |
| `scripts/register.py:629` | 기존 메시지 prefix `게시판 형식이 아닌 것 같다` 를 유지한다. | OK |
| `bot/fail_taxonomy.py:292` | `board_shape` subkind label 은 `게시판 형식 아님` 이다. | OK |
| `bot/fail_taxonomy.py:294` | 분류 matcher 는 `게시판 형식 아님` 문자열을 찾는다. | OK |

reject-message regex 상호작용:

| 항목 | 확인 |
|---|---|
| `_board_shape_check` 반환 메시지 | `scripts/register.py:629` 에서 기존 "게시판 형식이 아닌 것 같다" 문구 유지 |
| `_save_rejected` reason | `scripts/register.py:2172` 에서 `board_shape_check 거부 (게시판 형식 아님)` 유지 |
| bot fail taxonomy | `bot/fail_taxonomy.py:294` 가 `게시판 형식 아님` 을 찾음 |
| 결론 | sitemap hint append 가 fail taxonomy 를 깨는 구체 경로 없음 |

보고하지 않은 항목:

| 항목 | 이유 |
|---|---|
| JSONL append intra-process race | `scripts/poll.py:320-322` 블록 안에 `await` 가 없어 같은 event loop task 사이 interleave 경로를 확인하지 못했다. |
| JSONL cross-process race | HYPOTHESIS. 동시에 poll 프로세스 2개가 뜨는 운영 조건이 필요하다. 이번 코드만으로 concrete bug 로 보지 않았다. |
| `_mdr_candidates_safe` broad except | measurement-only digest field 이고 실패 시 빈 후보가 목적에 맞다. |
| `_check_sitemap_lastmod` broad except | observe-only helper 이며 error 를 obs dict 에 담는다. 단, latency 문제와는 별개다. |

## 3. observe-only 검증

결론:

| 질문 | 답 |
|---|---|
| lastmod 는 fetch 와 병렬로 시작되는가? | 예. `scripts/poll.py:301` 에서 `asyncio.create_task(_check_sitemap_lastmod(st))` 로 먼저 시작한다. |
| 완전히 observe-only 인가? | 아니오. `scripts/poll.py:314` 에서 fetch 이후 task 완료를 기다린다. |
| latency 가 additive 인가? | fetch 가 lastmod 보다 빨리 끝나는 경우 additive 가 된다. |
| 최대 추가 지연 근거 | `scripts/poll.py:125` 의 `httpx.AsyncClient(timeout=5.0)` |

구체 실행 경로:

| 순서 | line | 동작 |
|---:|---|---|
| 1 | `scripts/poll.py:301` | lastmod task 생성 |
| 2 | `scripts/poll.py:305` | site semaphore 진입 |
| 3 | `scripts/poll.py:306` | `_fetch_one(...)` await |
| 4 | `scripts/poll.py:314` | fetch 완료 뒤 `await lastmod_task` |
| 5 | `scripts/poll.py:125` | lastmod HTTP timeout 은 5초 |

예시:

| 조건 | 결과 |
|---|---|
| `_fetch_one` 0.8초 완료, sitemap endpoint 5초 timeout | `_process_site` 는 약 5초까지 종료 지연 |
| `_fetch_one` 10초 완료, sitemap endpoint 5초 timeout | lastmod task 는 이미 끝났을 가능성이 높아 추가 지연 없음 |
| sitemap file 없음 | `_check_sitemap_lastmod` 가 `scripts/poll.py:108` 에서 `None` 반환하므로 추가 지연 없음 |

chromium/state race 검토:

| 항목 | 근거 | 결론 |
|---|---|---|
| chromium lock | lastmod helper 는 `httpx` GET 만 수행한다 (`scripts/poll.py:123`). | chromium lock 과 직접 충돌 없음 |
| state write | state 저장은 `_process_site` 마지막 쪽 `scripts/poll.py:393` 에서 한 번 수행된다. | 같은 site state 안에서 write race 확인 안 됨 |
| lastmod state key | `scripts/poll.py:323` 에서 `current_lastmod` 존재 시만 저장한다. | 기존 key 덮어쓰기 외 데이터 손상 없음 |

## 4. log rotation / lxml 비용 검증

log rotation:

| 항목 | 값 |
|---|---:|
| 대상 파일 | `output/sitemap_lastmod_log.jsonl` |
| 경로 상수 | `scripts/poll.py:45` |
| append 위치 | `scripts/poll.py:320-322` |
| rotation 코드 | 확인 안 됨 |

연간 크기 추정:

| 가정 | 계산 | 추정 |
|---|---:|---:|
| 100 sites, hourly cron | `100 * 24 * 365` | 876,000 lines/year |
| line 평균 400 bytes | `876,000 * 400` | 약 350 MB/year |
| line 평균 700 bytes | `876,000 * 700` | 약 613 MB/year |
| line 평균 1 KB | `876,000 * 1024` | 약 897 MB/year |

평가:

| 관점 | 판정 |
|---|---|
| 즉시 correctness bug | 아님 |
| 운영 hygiene | rotation 또는 retention 필요 후보 |
| data corruption | append-only 라 기존 state/config 를 망가뜨리는 경로는 아님 |

lxml 비용:

| 항목 | 근거 | 결론 |
|---|---|---|
| lxml parse 위치 | `engine/_mdr_candidates.py:51` |
| 호출 위치 | `engine/digest.py:475` |
| 입력 | `raw_list_html`, `engine/digest.py:440` |
| digest 생성 위치 | `engine/digest.py:397` 의 `build_digest(...)` |
| normal poll path | `scripts/poll.py` 검색 기준 `build_digest` 호출 없음 |
| 결론 | 현재 확인 범위에서는 매 poll cycle 이 아니라 register/digest 생성 경로 비용이다. |

추가 compute risk:

| file:line | 내용 | 평가 |
|---|---|---|
| `scripts/poll.py:125` | Range header 로 2KB 만 요청하려는 의도 | 서버가 지키면 비용 작음 |
| `scripts/poll.py:128` | 응답 전체 `r.text` 에 regex | 서버가 Range 무시하면 큰 sitemap 비용 가능 |

## 5. CLAUDE.md §5 / N100 restart

dev-box / configs hygiene:

| 항목 | 확인 |
|---|---|
| production code 직접 수정 여부 | 이번 review 작업에서는 수정하지 않음 |
| 대상 변경 파일 상태 | `engine/digest.py`, `scripts/poll.py`, `scripts/register.py` 수정됨, `engine/_mdr_candidates.py` 신규 |
| configs 변경 | `git status --short -- ... configs` 확인에서 `configs/` 변경 출력 없음 |
| output 변경 | 이번 review 작업에서는 생성하지 않음 |
| 작성 파일 | 이 문서 `docs/2026-05-24-layer-addition-codex-bug-review.md` 1개 |

N100 restart:

| 근거 | 판단 |
|---|---|
| 변경 파일에 `engine/digest.py` 포함 | 배포 시 running service 가 engine module 을 import 하고 있으면 restart 필요 |
| 변경 파일에 `scripts/poll.py` 포함 | poll 이 long-running service/process 안에서 실행되는 구조라면 restart 필요 |
| AGENTS.md 운영 원칙 | engine/bot 계열 변경은 dev box commit/push 후 N100 pull, 필요 시 service restart |
| 결론 | N100 반영 시 `git pull --ff-only` 후 `notice-bot.service` restart 권장. engine 변경이 있어 실운영 반영 관점에서는 restart 필요 쪽으로 보는 게 안전하다. |

주의:

| 항목 | 내용 |
|---|---|
| 이 review 는 배포를 수행하지 않음 | ssh, pull, restart 모두 실행하지 않았다. |
| bot/poll/register 실행 여부 | 실행하지 않았다. |
| benchmark 실행 여부 | 실행하지 않았다. |

## 6. commit 분류

| 파일 | 권장 | 비고 |
|---|---|---|
| `engine/_mdr_candidates.py` | commit-OK | register/digest 시 measurement 후보를 만드는 helper 로 보이며 구체 버그 없음. |
| `engine/digest.py` | commit-OK | 새 key 추가는 extra dict field 이고 기존 `sitemap_candidates` 유지. strict shape break 확인 안 됨. |
| `scripts/poll.py` | 보강 후 commit | lastmod observe 가 fetch 완료 뒤 최대 5초 latency 를 추가할 수 있음. Range 미준수 서버의 큰 body 비용도 보강 후보. |
| `scripts/register.py` | commit-OK | reject 안내만 append. 기존 board_shape fail taxonomy 문자열 유지. |

수정 권장 최소 범위:

| 우선순위 | 대상 | 제안 |
|---:|---|---|
| 1 | `scripts/poll.py:314` | fetch 완료 시점에 lastmod task 가 끝났을 때만 consume 하거나, 아주 짧은 drain timeout 을 둔다. |
| 2 | `scripts/poll.py:125-128` | response size cap 을 실제로 강제한다. Range header 만 믿지 않는다. |
| 3 | `scripts/poll.py:320-322` | JSONL retention/rotation 정책을 별도 follow-up 으로 둔다. |

최종 판단:

| 항목 | 결론 |
|---|---|
| 버그 없이 그대로 commit 가능한가 | 아니오. `scripts/poll.py` 는 보강 후 commit 권장 |
| 데이터 손상 위험 때문에 즉시 drop 해야 하나 | 아니오. 확인된 문제는 latency/compute 쪽이다 |
| production code 수정 필요 여부 | 이 review 문서는 수정하지 않음. 수정은 별도 task 로 분리 필요 |
