# auto 등록 대상 = "새 글 올라오는 곳" 만 — 카탈로그/목록은 거부(수동 허용)

## Context

2026-05-21-code batch(개발 생태계 100 사이트) 에서 드러남: **패키지 레지스트리·제품 카탈로그가 index 로 *정상* 등록**됨. classify(ADR 0007)가 합리적으로 통과시킨 결과 — 예 `crates.io` (conf 0.96, "쇼핑 목록형 진입 페이지"), `hub.docker.com`(이미지), `pub.dev`(인기 패키지), `pypi.org/rss`(패키지 RSS). 66 registered 감사 결과 ~12건이 이런 *아티팩트 카탈로그*, 추가로 ~10건은 nav/메뉴/연도-아카이브를 글-행으로 오추출한 false-accept(예 `openbsd.org/` `nav>ul>li` → goals/plat/security, `netbsd.org/changes` → 2025/2024/2023).

근본 원인: classify 의 `index` 정의가 "게시판 / 공지목록 / 포럼 / **카테고리 / 피드**" 로 넓어 상품-카테고리·패키지-레지스트리·소셜갤러리까지 쓸어담는다. 더 깊게는 **notice-watcher 의 *auto 등록 대상 정의* 가 글로서리에 없었다** — "갱신되는 목록이면 다 등록" → 폴링 junk(패키지명·제품) 가 폴링 대상으로 박힘.

**이 ADR 의 대상은 *범위(scope)* 축뿐** — "항목이 글이냐 카탈로그-아티팩트냐"(~12건). 같이 관측된 nav/메뉴/연도-아카이브 *오추출*(~10건) 은 **별개의 추출-버그**(글-board 인데 row_selector 가 nav 를 가리킴) 로, 구조 게이트(layer E/D) 후속 작업이지 이 ADR 이 막는 범위가 아니다.

사용자(2026-05-22 grill-with-docs)는 직접 만든 `humblebundle.com/software`(소프트웨어 딜 카탈로그) 를 예로 "이런 건 갱신돼도 *글*이 올라오는 게 아니다 — 수동으로 만들고 싶다" 고 범위를 명시.

## Decision

auto 등록 대상을 **"새 글 올라오는 곳"** 으로 한정한다. 멤버십 테스트(classify·게이트가 묻는 질문):

> **"여기에 새 글(읽으라고 쓴 제목 + 읽을 본문)이 *최신순*으로 올라오나?"**

- **IN — "새 글 올라오는 곳"**: 항목이 *글* (공지·기사·포스트·포럼토픽·릴리스노트) **AND** 최신순 누적(폴러가 목록 top diff 로 새 것 감지 가능). *형태*(게시판·소셜피드·블로그·RSS-of-글·카드그리드) 는 무관 — 같은 개념의 옷.
- **OUT — "카탈로그/목록"**: 항목이 *글이 아닌 아티팩트*(패키지·제품·이미지·gem·도커이미지) 거나, *비-최신순*(인기·큐레이션·관련순: 핀터레스트, pub.dev 인기) 으로 모은 목록. → **auto REJECTED** (사유 "새 글 올라오는 곳 아님").
- **수동 허용 (hard-blacklist X)**: OUT 도 영구 차단 아님 — 유저가 명시 요청하면 *수동 config*(`register.py --config` / hand-config §2e) 허용. 카탈로그/제품/검색 워칭은 별도 향후 **item-watcher** 영역(google 검색·humble 류)으로 둔다.

**경계 — 릴리스노트(IN) vs 패키지 publish(OUT)**: forgejo/php/gradle/sqlite 의 릴리스/뉴스는 *프로젝트가 쓴 발표글*(변경노트 본문 + 헤드라인) 이라 IN. crates.io/pypi-rss 의 새 패키지는 *레지스트리의 publish 이벤트*(아티팩트 레코드 — 이름+버전, 읽을 발표 본문 없음) 라 OUT. 갈림 = "사람이 읽으라고 쓴 발표글이냐, 아티팩트 색인 레코드냐" — 둘 다 "릴리스" 라 불려도 다르다.

"feed"·시각 레이아웃(네모 카드 vs 줄)은 **IN/OUT 판정에 안 쓴다** — feed 는 형태(RSS 전송포맷·소셜형태)일 뿐, 같은 RSS 라도 글을 나르면 IN, 패키지를 나르면 OUT. 판정은 *항목이 글이냐 + 최신순이냐* 뿐.

**거부 매핑·임계는 이 ADR 에서 확정 안 함 (구현 트랙)**: classify 의 page-type 정의(ADR 0007 §확장 multi-class)를 이 멤버십 테스트로 보강 — `index` 정의에서 "카테고리/피드" 의 무조건 IN 을 제거하고 "글 + 최신순" 으로 좁힌다. 단 카탈로그를 *어느 거부 채널로* 보낼지(현 4-class 에 `catalog` 차원 추가 / `content` 로 매핑 / 별도 veto)·*어느 신뢰도 임계*로 거부할지(ADR 0007 의 비대칭 reject conf≥0.7 와 연결, 단 자가보고 conf 는 소형모델서 anti-calibrated — research 2026-05-22)·*목록만 보고 판정할지 detail fetch 가 필요한지* 는 구현 작업에서 결정. nav/연도-아카이브 *오추출* 차단은 직교한 별도 구조 게이트(layer E/D).

## Considered alternatives

- **카탈로그도 auto 등록 (feed 로 취급)** — 기각. 폴링 junk·노이즈(분당 수십 패키지 publish), item-watcher 와 기능 중복, 사용자 범위 명시와 충돌.
- **호스트 hard-blacklist** (crates.io/npmjs.com/... 목록) — 기각. 수동 요청을 막고, 목록 밖 미지 카탈로그를 못 잡음. 결정적이지만 일반성 0.

## Consequences

- **득**: 카탈로그 false-accept(폴링 junk 등록) 차단. notice-watcher 의 *대상 정의* 가 글로서리(CONTEXT.md)에 명문화 — 이후 batch 의 in/out 판단 근거.
- **실**: "글 vs 아티팩트" 가 분류기 의미판단에 의존 — 경계(릴리스노트 vs 패키지 publish)가 흔들릴 여지. "최신순" 판정엔 별도 신호(항목 날짜 내림차순 등) 필요할 수 있음.
- **미해결(별도 트랙)**: ① 멤버십 테스트의 *구현 메커니즘* — classify 정의 보강만으로 충분한가 vs 구조 신호(날짜 내림차순·RSS pubDate·sort label·detail fetch) 추가, 거부 채널·임계(위 Decision 참조). ② 수동 허용 배관 — OUT REJECTED 마커가 `register.py --config` 수동 경로를 막지 않는지 확인(`is_rejected` 가 수동 등록 차단하면 안 됨). ③ **기존 등록 정리** — 이번 batch 에 카탈로그로 *이미 등록된* ~12건(crates.io·hub.docker·pub.dev·pypi-rss 등) + nav/아카이브 오추출 ~10건의 `configs/`·`output/poll_state/`·구독을 sweep(거부 전환)할지 보존할지 결정 필요. ④ item-watcher 는 미구현 향후 기능 — 이 ADR 은 그 의존을 만들지 않음(OUT 은 그냥 수동 config, item-watcher 없어도 동작).

cross-ref: ADR 0007(classify veto / multi-class page-type), CONTEXT.md(**새 글 올라오는 곳** / **카탈로그·목록** / **형태**).
