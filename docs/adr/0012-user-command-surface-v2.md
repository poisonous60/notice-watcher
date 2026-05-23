# 사용자 봇 명령 surface v2 — 카페 공개 전 정돈

카페에 봇 링크 공개 전 첫 인상 개선이 필요해, 사용자 향 슬래시 명령을 10개에서 7개로 줄이고 `/list`·`/setting` 을 Discord UI(Select·Button·Modal) 기반으로 재설계했다. 처음 보는 사용자가 명령어 하나만 외우면 그 다음은 UI 클릭으로 직관 조작하는 게 목적.

## 결정

사용자 향 슬래시 명령 7개로 한정:

| 명령 | 역할 |
|---|---|
| `/watch` | 등록 (변경 없음 — 기존 인자 유지) |
| `/list` | 구독 목록 + 인라인 편집·해제 UI |
| `/setting` | 발송 설정 (announce + notify-time 통합) |
| `/help` | 명령 안내 embed |
| `/report` | URL 기반 문제 신고·임의 사이트 지원 요청 (slug·url optional) |
| `/feedback` | 자유 의견 (slug·url 무관, 그대로 유지) |
| `/status` | 봇·폴링 상태 |

흡수·이동:
- `/preview` → `/admin preview` subcommand 로 이전 (일반 사용자 안 보임). 시드보드 *등록 전 미리보기* 는 `/watch` 응답의 "예시 알림" 으로 충분 — 별도 명령으로 노출하면 `/watch` 와 용도 겹쳐 혼란.
- `/announce` + `/notify-time` → `/setting` 1화면 UI 흡수.
- `/unwatch` → `/list` 의 ✕ 버튼 흡수.

분리 유지 (codex 1차 리뷰 후 결정):
- `/report` 와 `/feedback` 는 의미 분리: report = URL/사이트 컨텍스트 있는 문제 신고 (등록된 slug 든 게이트 거부 URL 이든 임의 URL 이든), feedback = 사이트 무관 자유 의견.
- `/report` 에 slug 든 url 든 *둘 중 하나는* 있어야 — 둘 다 비면 거부, `/feedback` 으로 안내.

### `/list` UI — Select dropdown + 액션 버튼 (관용 패턴)

MEE6·Hydra 등 흔한 봇 패턴: embed 에 N개 목록, Select 에서 항목 고르면 액션 버튼 활성. discord.py `View(timeout=180s)`, ephemeral.

- 페이지당 10개, embed 본문에 번호+`display_title`+필터+발송대상 표시.
- Slug 노출 X — `display_title` 표시 (없으면 URL host+path).
- ActionRow 1: Select(최대 25 옵션이나 페이지당 10) — 편집·해제할 구독 선택.
- ActionRow 2: `[✎ 필터 수정]` `[✕ 해제]` — Select 후 활성.
- ActionRow 3: `[◀]` `[▶]` — 페이지 nav (필요 시).
- 필터 수정 = Modal TextInput(현재 필터 prefilled), 저장 시 DB 갱신.
- 해제 = 즉시 `db.remove_subscription` + embed refresh.

### `/setting` UI — 1화면 전체

ActionRow 5 예산 안에 토글·시각 다 노출. ephemeral, View timeout 180s.

```
Row1: [📨 DM 공지: ON]    [📣 채널 공지: ON]
Row2: [⏰ DM 시각: 08:30 ✎]  [⏰ 채널 시각: 09:00 ✎]
Row3: [❌ 닫기]
```

- DM 컨텍스트 = 채널 버튼 2개 숨김.
- Manage Channels 권한 없음 = 채널 버튼 disabled.
- 시각 버튼 = Modal HH:MM TextInput, `bot/main.py:_normalize_hhmm` 재사용.
- 공지 토글 = `db.set_announce_optout` 즉시 호출 + 라벨 갱신.

### `display_title` 컬럼 신설

`subscriptions.display_title TEXT NULL`. `scripts/register.py` 가 등록 성공 시 board page HTML `<title>` 추출해 출력 JSON 에 포함, `bot/db.py:add_subscription` 가 저장. CONTEXT.md 의 `display_title` 항목 참고.

기존 sub = NULL → URL host+path fallback. 마이그 안 함 (대량 fetch 회피 — stale 자연 보정).

## 이유

- 명령 10개 = 슬래시 자동완성 노이즈. 첫 사용자가 "뭘 쳐야 하지" 멈춤. 6개면 한눈에.
- `unwatch`/`announce`/`notify-time` 따로 외울 필요 X — `/list` `/setting` 안에서 클릭.
- `display_title` = slug 가 `host_arca-live_b_2-aaaa1234` 같은 디버그 문자열이라 사용자에 무의미. 페이지 title("아카라이브 ㅁㅁ채널") 이 직관.
- Select 기반 = label-text 버튼(직접 클릭 1-step) 보다 우회적이나, Discord ActionRow 5 한계로 per-row 버튼은 4 sub/page 가 상한. 10/page 위해 표준 Select 패턴 채택.

## 결과

- DB 마이그: `subscriptions.display_title` 컬럼 ADD (idempotent `_migrate`).
- `bot/db.py`: `add_subscription` 에 `display_title` 인자, 기본 None.
- `scripts/register.py`: 성공 시 HTML `<title>` 추출(이미 fetched HTML 에서), 출력 JSON 에 추가.
- `bot/worker.py`: register 결과의 display_title 을 `add_subscription` 에 전달.
- `bot/main.py`:
  - `/watch` 의 즉시 add_subscription path (이미 등록된 사이트) 도 display_title 같이 넘김.
  - `/list` 전면 재작성 — `discord.ui.View` + Select + Buttons + Modal.
  - `/setting` 신규 — 위 UI.
  - `/unwatch` 제거 (자동완성 path 도 제거; `/list` 의 ✕ 가 대체).
  - `/preview` 를 admin tree subcommand 로 이동 (`bot/admin.py:build_admin_tree`).
  - `/announce`·`/notify-time` 제거 (`/setting` 로 흡수).
  - `/report` 에 `slug` optional + `url` optional 추가. 둘 다 비면 ephemeral 거부 + `/feedback` 안내.
  - `/feedback` 그대로 유지.
  - `/help` embed 7개 명령으로 갱신.
- `docs/봇 명령어.md` 갱신.
- 손-config 워크플로·report-triage 영향 없음 (slug 식별자 그대로).
