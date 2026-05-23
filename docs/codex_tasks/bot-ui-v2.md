# Codex Task — 봇 UI v2 (사용자 명령 surface 정돈)

설계는 `docs/adr/0012-user-command-surface-v2.md` 참고. 이 문서는 *실행 명세* — 어떤 파일을 어떻게 바꾸나 + 검증 게이트.

## 컨텍스트

`notice-watcher` Discord 봇이 카페 공개 전 첫 인상 UI 다듬는 중. 일반 사용자 명령을 10→6 으로 줄이고 `/list`·`/setting` 을 Select+Button+Modal UI 로 재설계. dev box 에서만 작업 (CLAUDE.md §1). 손대는 파일: `bot/*.py`, `scripts/register.py`, `docs/봇 명령어.md`.

## 작업 1 — DB 마이그: `subscriptions.display_title`

`bot/db.py` 의 `_migrate(conn)` 또는 schema 생성 함수에 idempotent ADD:

```sql
ALTER TABLE subscriptions ADD COLUMN display_title TEXT
```

`PRAGMA table_info(subscriptions)` 로 컬럼 존재 검사 후 ADD (이 repo 의 다른 마이그 패턴 따라 — 같은 파일 안 다른 migration 참조).

`db.add_subscription(...)` 시그니처에 `display_title: Optional[str] = None` 추가. INSERT 에 컬럼 포함.

`db.list_subscriptions(...)` 가 반환하는 row dict 에 `display_title` 자동 포함 (SELECT * 면 알아서 들어옴).

## 작업 2 — register.py 의 HTML title 추출

`scripts/register.py` 가 board URL 페이지를 fetch 한 후 (이미 probe 단계에서 HTML 보유) `<title>...</title>` 추출:

- BeautifulSoup 또는 정규식 `re.search(r"<title[^>]*>(.*?)</title>", html, re.I|re.S)`.
- `html.unescape()` + `.strip()` + 최대 200자 truncate.
- 추출 실패·빈 문자열이면 None.
- 등록 성공 결과 dict (`scripts/register.py` 가 stdout JSON 으로 출력하는 그것) 에 `"display_title": <str | None>` 추가.

기존 result schema 어디서 정의하는지 grep 으로 찾아 — 이 repo 는 register subprocess 출력을 worker 가 `json.loads(stdout)` 한다.

## 작업 3 — worker 가 display_title 전달

`bot/worker.py` 의 register 잡 처리 코드에서 result dict 의 `display_title` 을 꺼내 `db.add_subscription(..., display_title=...)` 에 넘김.

`/watch` 의 *이미 등록된 사이트 즉시 add_subscription* path (`bot/main.py:202` 근처) 도 display_title 같이 넘김 — 이 경우 result 없음, 기존 `subscriptions` 행에서 *다른 사용자* 가 등록한 display_title 가져와 재사용 (`db.list_subscriptions(slug=slug)` 첫 행).

## 작업 4 — /list 전면 재작성

`bot/main.py` 의 `@tree.command(name="list")` 를 View 기반으로 교체:

- `discord.ui.View(timeout=180)`. `interaction_check` 로 본인만 조작 가능.
- ephemeral.
- 10 subs/page. embed 본문에 `1. <display_title or url_host_path> · 필터: <filter or "없음"> · <DM | #채널멘션>` 형식.
- ActionRow 1: `Select(placeholder="구독 선택 (편집/해제)")` — 현 페이지 10개 옵션. label=display_title (없으면 host+path), value=slug, description=필터 한 줄 잘림.
- ActionRow 2: `Button(label="✎ 필터 수정", disabled=True)` `Button(label="✕ 해제", style=danger, disabled=True)` — Select 콜백에서 enable.
- ActionRow 3: `Button("◀", disabled=page==0)` `Button("▶", disabled=page==max)` — 1페이지 이하면 row 자체 omit.

콜백:
- Select → 선택 slug 저장 (view state), 버튼 2개 enable, message edit.
- ✎ 필터 → `discord.ui.Modal` with `TextInput(label="필터", default=현재필터, required=False, max_length=500)`. submit → `db.update_subscription_filter(user_id, slug, new_filter)` (필요시 db.py 에 신규 함수 추가; 또는 `add_subscription` 의 upsert 동작 재사용 — check existing). 그 후 view rebuild + edit.
- ✕ 해제 → `db.remove_subscription(user_id=…, slug=…)`. embed/options 재계산, 빈 페이지면 이전 페이지로 fallback. 비어있으면 `msg("list_empty")` 로 메시지 교체 + view 비활성.
- ◀/▶ → page 증감, rebuild.

display_title 표시 헬퍼: `subscriptions.display_title` NULL 이면 `urllib.parse.urlparse(url).netloc + path` (긴 path 자르기).

## 작업 5 — /setting 신규

`bot/main.py` 에 `@tree.command(name="setting", description="발송·공지 설정")`:

- ephemeral, `View(timeout=180)`.
- DM 컨텍스트 (`interaction.guild is None`) → 채널 버튼 2개 row 안 만듦.
- guild 인데 `interaction.permissions.manage_channels` False → 채널 버튼 disabled.

ActionRow:
- Row1: `Button(label=f"📨 DM 공지: {ON|OFF}")` + (guild 면) `Button(label=f"📣 채널 공지: {ON|OFF}")`.
- Row2: `Button(label=f"⏰ DM 시각: {hhmm} ✎")` + (guild 면) `Button(label=f"⏰ 채널 시각: {hhmm} ✎")`.
- Row3: `Button(label="❌ 닫기", style=secondary)`.

콜백:
- 공지 토글 → `db.set_announce_optout(scope_kind, scope_id, opted_out=not current)`. label 갱신 + edit.
- 시각 ✎ → Modal `TextInput(label="발송 시각 (HH:MM)", default=현재, required=True)`. submit → `_normalize_hhmm` 검증 (실패 시 ephemeral 에러), `db.set_deliver_at`.
- 닫기 → `view.stop()` + `interaction.edit_original_response(view=None)` 또는 메시지 delete.

## 작업 6 — /report 시그니처 확장 (feedback 분리 유지)

기존 `/report` 시그니처:
```
slug: required (autocomplete own subs)
issue: required
```
→ 변경:
```
issue: required
slug: optional (autocomplete own subs — 본인 구독)
url: optional (https?:// 검증 — 게이트 거부된 사이트 / 임의 사이트 지원 요청)
```

검증 규칙 (인자 게이트):
- slug 도 url 도 없음 → ephemeral 거부 + 안내: "URL 없는 자유 의견은 `/feedback` 으로 보내주세요."
- slug 있고 본인 구독 아님 → 기존처럼 거부.
- url 형식 오류(`^https?://` 미매치) → 거부.
- slug 와 url 동시 제공 → slug 우선, url 은 부가 정보로 reports 본문에 같이 저장.

`db.add_report` 시그니처 확장 — `url: Optional[str] = None`, `slug` 도 nullable 로. DB schema 에 `url TEXT NULL` 컬럼 추가 (`_migrate` idempotent ADD). slug NULL allow.

owner DM 본문에 url 표시 추가. report-triage skill 입력원에 변화 없도록 slug 기준 동작은 유지.

**`/feedback` 명령·`feedback` 테이블 그대로 유지** — codex 1차 리뷰 후 결정. `/feedback` = 사이트 무관 자유 의견 전용, `/report` = URL 컨텍스트 있는 신고·지원 요청. 의미 분리. `/admin feedback`·`/admin reports` 그대로.

## 작업 7 — 명령 제거·이동

- `/unwatch` 핸들러 제거 + 자동완성 함수는 남김 (`/report` 가 slug autocomplete 로 재사용).
- `/announce` 핸들러 제거.
- `/notify-time` 핸들러 제거.
- `/feedback` **유지** (변경 없음).
- `/preview` 핸들러 → `bot/admin.py` 의 `build_admin_tree` 안 subcommand 로 이동 (ADMIN_GUILD_ID 길드만 노출). 함수 본체는 거의 그대로 — interaction → 큐 enqueue. admin guild 안에서 owner 외 사용자도 호출 가능 (테스트용) — `is_owner` 게이트 *없음*, guild 범위만 가드.

## 작업 8 — /help embed 갱신

`bot/messages.py` 의 `help_field_*` 메시지를 7개 명령 surface 로 재작성:
- 구독 관리: `/watch`, `/list`
- 설정: `/setting`
- 신고: `/report` (URL 기반)
- 의견: `/feedback` (자유)
- 상태: `/status`
- 기타: `/help`

## 작업 9 — docs 갱신

`docs/봇 명령어.md` 의 *일반 사용자* 섹션을 6명령으로 재작성. `/preview` 는 Owner 섹션으로 이동 (admin 명령 옆). `/list`·`/setting` UI 동작 1~2단락씩 묘사.

## 작업 10 — 명령 동기 sync 처리

`on_ready` 의 tree.sync 호출은 그대로 — 글로벌 명령 변경 후 자동 전파(~1h). dev guild(GUILD_ID 지정) 면 즉시 sync. 제거된 명령(unwatch/announce/notify-time/feedback)은 sync 후 사라짐. 추가 행동 불요.

## 검증 게이트 (반드시 통과)

1. `python -m py_compile bot/main.py bot/db.py bot/worker.py bot/admin.py scripts/register.py` 0 exit.
2. `python scripts/probe_smoke.py --stage 3 --stage 5` 0 exit (pre-push hook 동일).
3. 봇 import 동작 — `python -c "from bot import main"` 0 exit (top-level 에러 없는지).
4. `pytest tests/` 가 통과 → 통과해야 (현재 그린이면 그대로 그린; 봇 관련 테스트는 거의 없음).
5. 새 컬럼 마이그 idempotent — 같은 DB 두 번 connect 해도 OK.

## 작업 끝나면

- 변경 파일 list + 핵심 diff summary 출력.
- 작업 7-10 에서 빠뜨린 게 있나 self-check.
- commit 만들지 X — 사용자가 검토 후 직접 함 (Claude 가 후속).

## 금지

- pre-push hook 우회 (`--no-verify`) 금지. CLAUDE.md §7a.
- `git push --force` 금지.
- N100 SSH·코드 편집 금지 (CLAUDE.md §3). dev box 만.
- `db.py` 의 다른 테이블 schema 건드리지 X — `subscriptions` + `reports` 두 곳 컬럼 추가만.
- `engine/`, `probe/` 디렉터리 건드리지 X — 등록 파이프 본체 무관.
