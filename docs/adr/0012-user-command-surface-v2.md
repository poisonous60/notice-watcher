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

### `/list` UI — Per-row Button + 페이지네이션 (RoboDanny 패턴)

처음 시도한 Select dropdown 패턴은 discord.py issue #7284 의 함정 — `SelectOption.default=True` 박은 항목을 사용자가 *같은 항목 재선택* 하면 `Select.values` 가 빈 list 로 callback 도착해 `int(values[0])` IndexError → silent → 무한로딩 "..." — 에 걸려 production 에서 죽었음. v2 재설계로 RoboDanny paginator 패턴 채택.

원칙:
- **View item set 은 `__init__` 에서 한 번만 add**. callback 마다 `clear_items() + add_item()` 안 함 (docs 권장 위반·race 위험).
- **`_refresh()` 가 *오로지* item.label·item.disabled mutate**. item 객체 reference 는 self 에 박혀있음.
- **`on_error` override + `interaction_check`** 둘 다 박음 (silent 함정 회피).
- **모든 write callback 첫 라인 `interaction.response.defer()`** — sqlite lock 시 3초 ack timeout 회피.
- **row 식별은 `subscriptions.id`** — 같은 slug 의 DM+채널 양쪽 구독 시 ✕ 가 한 행만 지움 (slug-only DELETE 함정 회피, codex 리뷰).

레이아웃 (ActionRow 5 한계 안):
- 4 sub-row × `[✎ <title>: <filter>][✕]` = 4 sub/page
- 1 nav row `[◀ 이전][다음 ▶]`
- 필터 라벨 truncate 80 chars
- 빈 자리 (sub 수 < PAGE_SIZE) = label="—" + disabled
- 페이지 1개뿐이면 nav 둘 다 disabled

필터 수정 = `[✎ <title>: <filter>]` 버튼 → `discord.ui.Modal` TextInput (현재 값 prefilled, paragraph style, 1000 chars).

해제 = `[✕]` 즉시 `db.remove_subscription_by_id(sub_id)` + view reload + embed refresh.

페이지 nav = ◀/▶ disabled state mutate, item 추가 X.

`SubscriptionListView(timeout=300s, ephemeral=True)`. 5분 후 버튼 dead → 사용자 재 `/list`.

> 결정 근거: discord.py 공식 examples/views/persistent.py + confirm.py, RoboDanny paginator (`cogs/utils/paginator.py`).

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
