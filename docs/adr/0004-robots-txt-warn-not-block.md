# ADR 0004 — robots.txt `Disallow` 는 warn-and-proceed, block 아님

- Status: Accepted
- Date: 2026-05-20
- Deciders: 사용자 (poisonous60), grill-with-docs 세션
- Supersedes: 없음

## Context

`scripts/register.py` 는 등록 시 후보 사이트의 `robots.txt` 를 한 번 체크한다. 일반 crawler 관례 (Googlebot, archive.org 등) 는 `Disallow` 매칭되면 그 path 를 fetch 안 한다.

이 봇은 게시판 새 글 폴링 + Discord 알림. 알림 메시지에 글 링크 박혀 사용자가 클릭 → 사이트 방문. 즉 *traffic 송출* 기능.

선택지:
- A. 표준 honor — `Disallow` 매치하면 등록 거부.
- B. warn-and-proceed — 경고 출력하되 등록 진행. (현재 정책, `docs/크롤링 지침.md` §6 line 88 기술.)
- C. 완전 무시 — robots.txt 안 읽음.

## Decision

**B 채택.** `register.py` 가 `robots.txt` 읽어 `Disallow` 명시 경고를 *operator console + 로그* 에 출력하되 등록은 진행. `Disallow: /` (사이트 전체) 면 더 강한 경고. 자동 거부 X. operator (사용자) 가 보고 거절할지 결정.

## Rationale

### 사이트 traffic 으로 보상되는 fetch 비용

표준 robots.txt 가 가정하는 crawler = 콘텐츠 *수집·재배포·검색 인덱싱* 으로 사이트 trafic 을 *대체* 함. 봇이 글 본문 캐싱하면 사용자가 사이트 안 가도 됨 → 사이트 손해.

이 봇은 반대 패턴:
- Discord 알림 = "새 글 났다 + 링크" 만 (요약 정도). 본문 자체 재배포 X (`docs/크롤링 지침.md` §6 line 90 - "요약본만 푸시, 원문 재배포 금지" 정책).
- 알림 본 사용자 클릭 → 사이트 방문 → 사이트 광고·통계·comment 수익화 가능.
- fetch 빈도 = 일 1회 (대부분 사이트), 사람 1명 방문보다 작음.

→ robots.txt 가 막으려는 *피해 모델* 과 이 봇의 동작이 어긋남. 표준 honor 가 오히려 사이트 의도 (traffic 받기) 어긋남.

### Functionality 깨짐 비용 큼

게시판 사이트 중 `robots.txt` 에 board path Disallow 박은 곳 다수 (e.g., Discourse 기본 `/u/`, `/admin/` 박혀있고 일부 site 는 board 자체도 박음 — RSS 만 노출 의도). 표준 honor 시 *기능 자체* 가 동작 안 함.

`docs/사이트별 등록 시도 기록.md` 의 일부 실패 케이스 (확인 필요) 도 이 패턴.

### Trade-off

- ✅ traffic 송출 봇 정체성 보존.
- ✅ board 등록 가능 사이트 maximize (recall 우선).
- ❌ 사이트 owner 의 "안 fetch 해라" 명시 의도 무시.
- ❌ ToS / 법적 회색지대.
- ⚠️ 완화: warn 로그 + operator 확인 + 일 1회 한정 + `폴리트 슬립 2~5초` + `재시도 백오프` + UA 정상화 (현 정책 `docs/크롤링 지침.md` §2).

법적 완화 추가: 사람인 판례 (한국 대법 2020) 가 차단 트리거 = *고빈도 + 적극 우회*. 이 봇 일 1회 + 우회 자동 X (`LOGIN_REQUIRED` / `BLOCKED_*` 자동 거부, ToS 위반 path 안 박힘). 차단 우회 자동 X 는 ADR 0004 와 별개로 유지 — robots.txt warn 정책은 *honor 강제 안 함* 일 뿐 차단 발생 시 우회는 X.

### 대안 기각

**A. 표준 honor**:
- traffic 모델 어긋남 (위).
- recall 큰 손해 (board path 다수 Disallow).
- 사용자 명시 거부.

**C. 완전 무시**:
- warn 자체는 비용 0 + operator 정보 가치 (사이트 owner 의도 인지) + 미래 정책 변경 시 affected site 식별 가능.
- 완전 무시 → 정보 손실 + 향후 ADR revert 비용 ↑.

## Consequences

### Positive

- 기능 정상 동작 (board 사이트 다수 등록 가능).
- 사이트 traffic 송출 봇 정체성 일관.
- operator (사용자) 가 warn 보고 정책적 거절 가능 — 자동화 + 인간 판단 분리.

### Negative

- robots.txt honor 안 하는 봇 = 일부 사이트 owner 입장 "예의 없음" 가능. UA 평범한 Chrome (`docs/크롤링 지침.md` §2-3) 라 외부 식별 어렵지만 식별되면 reputational 비용.
- 회수 비용: 이미 등록된 사이트 중 disallow 명시인 게 있으면, 정책 revert 시 retro-actively 거부 처리해야 함. 회수 어렵진 않음 (마이그 1회) 이지만 사용자 알림 발생.

### Neutral

- `register.py` 의 robots.txt fetch 1회 + 파싱 코드 = 유지 (warn 출력 source). 제거 X.

## Implementation

이미 박혀 있음. `docs/크롤링 지침.md` §6 line 88 의 동작 정의 그대로. 이 ADR 은 *이유* 박는 doc — 코드 변경 X.

`configs/candidates/*.yaml` 의 entry 필터 (`scripts/register_batch.py` load 시) 도 robots.txt 무시. cross-catalog dedup + dead domain check 만.

## Future Review

다음 중 발생 시 재검토:
- 사이트 owner 명시 항의 (Discord owner DM, 또는 abuse 신고 등).
- 법적 자문 결과 변경.
- 봇 동작 모델 변경 (예: 본문 캐싱·재배포 시작) — 그 경우 traffic 송출 논거 깨짐.

## References

- `docs/크롤링 지침.md` §6 (현 정책 기술)
- `docs/크롤링 지침.md` §2 (전체 폴리트 룰)
- `docs/사이트 카탈로그 자동 등록 파이프라인 계획.md` §2 (catalog batch 비목표)
- grill-with-docs 세션, 2026-05-20 (Q12)
