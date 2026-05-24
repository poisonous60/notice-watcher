# N100 runtime 상태 백업 — Google Drive 일 1회 overwrite

## Context

봇·폴링·등록 결과는 전부 N100 한 대에 산다. 이 머신이 사라지면 (a) SSD 갑사, (d) 도난·화재 두 시나리오에서 *사용자에게 보이는 상태* 가 0 으로 리셋된다:

- `bot.sqlite3` — 누가 뭘 구독했나(`subscriptions`)·발송 시각·`jobs` 이력·`posts` 캐시. **사용자가 다시 `/watch` 해야 복구**.
- `output/poll_state/<slug>.json` — 사이트별 baseline(seen_post_ids). 잃으면 다음 폴링이 *모든* 옛 글을 새 글로 인식 → 사용자에게 옛글 폭탄.
- `output/learned_blacklist.json` — 학습된 거부 URL. 재학습 가능하나 LLM 호출 비용·latency 낭비.
- `usage.sqlite3` — LLM 사용량 통계. 손실해도 사용자 영향 0.

git 추적된 것(`configs/`·코드)은 새 N100 에 `git clone` 으로 즉시 복원. `.env`(Discord/Gemini/Safe Browsing token)는 잃어도 5분 안에 재발급. **runtime 상태만이 진짜 SPOF**.

지금까지 백업 0. `output/snapshot/` 은 dev box dashboard 가 `inspect_subs.py pull` 로 손-호출 시 떨구는 read-only mirror일 뿐 — 정기 X·destination N100 아님·재해 백업 X.

## Decision

위 4 파일/디렉토리를 N100 systemd `--user` 타이머가 일 1회 tar.gz 로 묶어 Google Drive 에 rclone 으로 올린다. `.env` 와 secrets 는 백업하지 않는다.

| 항목 | 값 |
|---|---|
| 범위 | `output/bot.sqlite3` + `output/usage.sqlite3` + `output/poll_state/` + `output/learned_blacklist.json` |
| 크기 | 현재 ~14MB raw → ~5MB tar.gz. 5년 worst ~17MB tar.gz |
| 빈도 | 일 1회 — `OnCalendar=*-*-* 04:30:00` (N100 system TZ = `Asia/Seoul`). `notice-poll.timer` 매시 :20 와 안 겹치는 시각. |
| Format | `tar.gz` 한 파일 (`notice-watcher-backup.tar.gz`, 날짜 suffix X — 매번 같은 이름) |
| Destination | Google Drive (rclone remote `gdrive:`, 폴더 `notice-watcher-backup/`) |
| Retention | **앱 측 코드 0** — 매번 같은 파일에 overwrite. Drive 가 binary 파일에 대해 30일/100 revision 자동 보관 후 purge(Google 기본 정책) → de facto 30일 rolling window 확보. (구 revision 의 quota 카운트 정책은 Google 측 변동·`keepForever` flag 등에 따라 달라질 수 있어 정확한 byte 부담은 보장 X — 어쨌든 free 15GB 의 작은 비율.) |
| Runner | N100 `systemd --user` (`notice-backup.timer` → `notice-backup.service`, linger 켜져있어 부팅 자동) |
| Monitoring | 없음. systemd journal 만 (`journalctl --user-unit notice-backup.service`). silent fail 흡수 = Drive 의 30일 revision window 가 보험 |
| 암호화 | 없음. tar.gz plaintext. 데이터에 Discord user_id·channel_id 들어가나 destination = 본인 Google account, OAuth scope folder-only |
| `.env` | 백업 X. 잃으면 Discord bot token / Gemini key / Safe Browsing key 재발급 (각 5분) |
| Restore | `docs/운영 메모.md §1c` 의 매뉴얼 절차 (OS setup → repo `git clone` → venv → rclone auth + `rclone copy` + `tar xzf` → `.env` 재작성 → systemd unit 배치 + enable → 검증) |

sqlite 는 `sqlite3 ... ".backup TARGET"` (online·lock-free) 로 떠 봇이 켜져있어도 안전. raw `cp` 는 WAL 중간 corrupt 위험.

## Consequences

- 사용자 visible 상태 (subscriptions·baseline) 가 N100 단일 머신 디스크 사망/도난 시점에서 **24시간 RPO** 로 복구된다. 그 24시간 사이에 `/watch` 한 사용자만 다시 등록 부탁.
- baseline 복구되므로 *옛글 폭탄 없음* — 가장 큰 사용자 영향 회피.
- "off-site" 보장은 Drive 가 본인 집/dev box 와 *물리적으로 다른 위치* 라는 가정 위에 선다 (Google 데이터센터). dev box mirror 가 아니므로 (d) 도난/화재 시나리오 흡수.
- Retention 을 코드로 짜지 않고 Drive 의 revision 정책에 위임 → **destination 이주 시 의도 깨질 수 있음** (예: S3-compat 로 옮기면 overwrite = 진짜 replace, 30일 window 사라짐). 이주 시 retention 정책 재검토 필수.
- Silent fail (rclone OAuth refresh 만료, 네트워크 30일+ 단절, Drive quota 초과) 시 모니터링 0 → 사용자가 N100 죽고 복구하려 보는 그 순간에 발견. 의식적으로 받아들인 risk — "혹시 몰라서 하는 보험" 성격.
- Drive quota 의 ~1% (15GB free 기준) 사용. 본인 Google account 의 Gmail/Photos 잉여에 의존.
- Discord user_id 등 식별자가 본인 Google account 에 plaintext 로 들어감. account 탈취 시 데이터 유출. account 의 2FA 가 사실상의 백업 데이터 보호 경계.
- `.env` 미백업 — 새 N100 setup 시 token 들 재발급·재작성 5분 매뉴얼 단계가 *반드시* 필요. restore 절차에 박혀있어야 시간 들어도 됨을 안다.

## Alternatives considered

- **S3-compat (Cloudflare R2 / Backblaze B2)**: overwrite 가 진짜 replace → 코드로 retention 짜면 진짜 5MB 고정. 비용 거의 0 ($0.015/GB·월 × 0.15GB). 하지만 카드 등록·새 계정·IAM 키 추가 setup. self-host 용 generic 패턴엔 더 깔끔하나 단일 사용자엔 over. 향후 셀프호스트 가이드에 옵션으로 documented 할 가치 있음.
- **GitHub private repo**: 사이즈 누적 → 1년 후 1GB+, GitHub free repo soft cap 위협. squash 코드 필요. 또 메인 repo (`notice-watcher`) 가 공개라 *별도* private repo 만들어야 — 실수로 메인에 push 하면 secrets 유출. 거부.
- **dev box scp pull**: dev box 노트북이면 매일 04:30 깨어있을 가능성 낮음 → fragile. 같은 방 가정이면 (d) 도난/화재 흡수 못함. off-site 보장 X. 거부.
- **30/60/365일 명시 rolling (앱 측 retention 코드)**: rclone `--min-age` 1줄로 쉽지만 Drive 의 revision 자동 보관과 *중복* — 같은 효과를 코드 + Drive 정책이 두 번 함. 단순화로 코드 측 제거. (destination 이주 시 재검토.)
- **gpg 암호화**: Drive account 노출 위험을 0 으로. 단 key 잃으면 백업 영원히 못 풂 (Discord bot 다시 만들어도 옛 user_id·subscriptions 복구 X). key 관리 비용 > 노출 risk(2FA 본인 account). 거부.
- **monitoring (systemd `OnFailure=` DM webhook / dashboard 카드 / heartbeat DM)**: silent fail 즉시 catch 하나 "신경 안 쓰고 싶다, 보험 성격" 과 모순. 알람 피로 + 코드 추가. 거부 — Drive 30일 revision window 가 흡수.
- **`.env` 백업 (plaintext / gpg)**: 토큰 재발급 5분 < 노출 risk. 거부.
- **dry-run restore 정기 테스트**: 복구 절차 bit rot 방지에 좋음. 1년에 0회 돌 가능성 → over. 거부 — 매뉴얼 절차만 박고 새 N100 setup 시 처음 돌려보는 게 사실상의 테스트.
- **백업 빈도 시간/분 단위**: 사용자 mutation (`/watch`) 빈도가 시간당 1건 이하라 5분/시간 RPO 의 가치 < 복잡도. 일 1회로 충분.
