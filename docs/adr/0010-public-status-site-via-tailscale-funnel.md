# N100 공개 현황 사이트 — Tailscale Funnel 정적 서빙

## Context

dashboard(`scripts/dashboard.py`)는 의도적으로 dev박스 전용이다 — `127.0.0.1` 바인딩, "외부에 절대 0.0.0.0 쓰지 말 것", N100 미배포(CLAUDE.md §2). 운영 데이터를 외부에 안 내보내는 게 원칙이었다.

그런데 프로젝트 진행 현황을 *외부인에게* 보여주고 싶다는 요구가 생겼다 (수업 쇼케이스/포폴). dashboard 를 공개로 돌리는 건 위 원칙과 정면 충돌이고, 운영용 내부 도구라 민감정보(user/channel ID·URL·slug·selector)가 그대로 노출된다.

미래 독자가 N100 에 공개 서비스가 떠 있는 걸 보고 "외부 노출 안 한다며?" 라고 의아해할 것이므로 *이게 dashboard 와 다른 별개 artifact 라는 점*과 *왜 Funnel 인지*를 기록한다.

## Decision

dashboard 와 **별개**의 정적 사이트(**공개 현황 사이트**)를 만들어 **Tailscale Funnel** 로 공개한다.

- **분리**: dashboard(dev 전용·내부·전체 데이터)는 그대로. 공개 사이트는 N100·익명화·읽기 전용 정적 HTML 한 장. 코드 경로·노출처 완전 분리.
- **생성**: `scripts/generate_site.py`(코드 → dev박스 작성·push → N100 pull → N100 실행, poll.py 와 같은 모델). N100 라이브 데이터를 읽어 `output/site/index.html` 로 굽는다. stdlib 만 — 새 의존성 0, CDN 0, JS 0 ("작게" 의도). 논문풍 CSS + 인라인 SVG figure.
- **익명화(공개 안전)**: 노출 = 집계 통계 + 최근 활동 타임라인 + 감시 대상 도메인/이름. 숨김 = user ID·channel ID·Discord 정보·URL·slug·selector. 익명화는 generator 의 책임(공개면에 raw 데이터 안 감).
- **재생성**: `deploy/notice-site.{service,timer}`(system-level oneshot+timer, `notice-poll` 패턴 복사, 주기 ~10분). poll 과 분리된 독립 타이머.
- **서빙**: `tailscale funnel <output/site dir>` — Tailscale 이 정적 디렉토리를 직접 HTTPS 서빙(별도 nginx/python 서버 없음). 공개 URL `https://<n100>.<tailnet>.ts.net`. 링크 아는 사람 누구나(받는 쪽 Tailscale 계정 불필요), robots 로 검색 색인은 막힘.
- **출력 위치**: `output/site/` — git-ignored(output/ 룰). 코드/unit 은 git 추적.

## Consequences

- N100 에 *의도적* 공개 면이 생긴다 — dashboard 의 "외부 노출 X" 원칙은 dashboard 에 한정, 이 사이트는 예외(익명화로 안전 확보).
- 공개 활성화는 *바깥 노출* 동작이라 사람 승인 게이트 2개: ① tailnet admin 에서 N100 노드 Funnel 활성화(ACL Funnel attribute + HTTPS 인증서), ② N100 에서 `tailscale funnel --bg` 1회 + `systemctl enable --now notice-site.timer`. Claude Code 자율 실행 X.
- 익명화 누락 = 공개 유출. generator 의 노출 필드 화이트리스트가 보안 경계 — 새 통계 추가 시 raw ID/URL 새지 않게 검토.
- 공개 URL 은 한 번 배포·공유되면 회수 어려움(캐시·공유). Funnel off 로 즉시 차단은 가능.

## Alternatives considered

- **Cloudflare Tunnel + 커스텀 도메인**: 진짜 인터넷 공개(검색 노출·예쁜 도메인) 되나 cloudflared 데몬 + CF 계정 + 더 무거운 설정. 쇼케이스엔 과함 — Funnel 이 포트포워딩/DDNS 없이 충분. 검색 노출·도메인이 필요해지면 재고.
- **dashboard 를 공개로**: 민감정보 노출 + "외부 노출 X" 원칙 파괴. 거부 — 별개 익명화 사이트.
- **GitHub Pages**: 무료·무보안부담이나 "N100 에서 돌린다" 요구 위반, N100 라이브 데이터 → git push 왕복 필요. 거부.
- **nginx/python http 서버 + Funnel**: `tailscale funnel <dir>` 가 정적 디렉토리 직접 서빙하므로 불필요한 컴포넌트. 거부.
- **봇 worker 이벤트마다 재생성 / poll piggyback**: 더 신선하나 hot path 결합·코드 의존 증가. 거부 — 독립 타이머가 관심사 분리.
