# ADR 0018 — cron × commit race 가드 (deploy wrapper + git_sha 가시화)

작성: 2026-05-25
상태: accepted (사용자 결정 — 2026-05-25 incident 후속, 별도 ADR)
관련: 2026-05-25 incident doc §5a, ADR 0016, ADR 0017 (poll_runs.git_sha)

## 1. Context

2026-05-25 incident 의 직접 원인 (B):

> cron 폴링 (08:20:57) 이 cfecac3 commit (09:45) **전** 시작 → fix 가 적용 안 된 옛 코드로 폴링이 hang.

표준 deploy 사이클 (CLAUDE.md §2):

```
dev box: commit → push → (pre-push hook probe_smoke)
N100   : git pull --ff-only → systemctl --user restart notice-bot.service  (필요 시)
```

문제:

1. **cron timer (`notice-poll.timer`) 와 `git pull` 의 timing race**. 폴링이 *commit 전* 시작 + *그 사이에* fix 가 main 으로 push → 폴링이 *옛 코드* 로 끝까지 돈다. 이번 incident 처럼 옛 코드가 버그를 가지면 사용자 영향.
2. **언제·어떤 git_sha 로 폴링이 돌았는지 영속 안 남음**. journal grep 으로만 추적 가능 (TTL 짧고 휘발).

### 현 deploy 동작 분석

dev box (commit 직후):
- `git push` → origin/main 갱신.
- 메모리: `feedback-commit-auto-deploy` — Claude 가 자동 N100 deploy. 명령: `ssh n100 'cd ~/notice-watcher && git pull --ff-only'` 그리고 필요 시 `systemctl --user restart notice-bot.service`.
- `notice-poll.timer` 는 *재시작 안 함* — daily timer 라 다음날 08:20 까지 안 fire. 일반적으로 race 안 남.

race window 가 열리는 경우:
- (i) 08:20 cron 이 fire 한 *시점에* dev box 가 hotfix 푸시 → N100 의 pull 이 cron 진행 중 도착.
- (ii) cron unit 이 늦게 fire (예: N100 부팅 직후 `Persistent=true` 가 누락 시도) + 그 사이 push.
- (iii) `notice-poll.service` 가 *진행 중* 인데 `git pull` 이 코드 파일 (poll.py 등) 을 새 commit 으로 교체 — Python 은 이미 import 한 모듈을 다시 안 읽으므로 *현 process 만큼은 옛 코드 그대로*. 그러나 새 commit 의 *bug-fix 가 못 적용된 사고*가 발생 (이번 incident).

이번 incident 는 (i) 의 변형 + 옛 코드 버그가 결합. fix 1차 (ordering) 가 들어간 직후에도 cron 은 이미 옛 코드로 30분+ 돌고 있었음.

## 2. Decision

3-layer 가드 박음:

### G1. dev box → N100 deploy 시 cron timer atomic stop/start

`scripts/n100_deploy.sh` (N100 에서 실행) — `ssh n100 bash` 으로 호출.

```sh
#!/usr/bin/env bash
# ADR 0018 — cron × commit race 가드. N100 에서 실행 (dev 박스는 ssh 로 호출).
# git pull 동안 notice-poll.timer 일시 정지 → cron 진행 중인 폴링 위에 새 코드가 안 덮음.
# 이미 진행 중인 unit 은 *안 죽임* (--no-block / SIGTERM 아님). 다음 trigger 만 지연.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[deploy] git pull --ff-only…"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[deploy] already up to date ($LOCAL) — nothing to do."
    exit 0
fi

# poll.timer 만 stop (active service 는 손 안 댐 — 진행 중 폴링은 끝까지 돌게).
# Persistent=true 라 stop 사이의 missed trigger 는 start 직후 catch-up.
echo "[deploy] notice-poll.timer stop (active service 는 안 건드림)…"
systemctl --user stop notice-poll.timer

# 이미 active 인 폴링 service 가 있으면 끝날 때까지 대기 (최대 30분 — 정상 폴링 7-15분).
if systemctl --user is-active --quiet notice-poll.service; then
    echo "[deploy] notice-poll.service 진행 중 — 끝날 때까지 대기 (최대 1800s)…"
    deadline=$((SECONDS + 1800))
    while systemctl --user is-active --quiet notice-poll.service; do
        if [ $SECONDS -gt $deadline ]; then
            echo "[deploy] ⚠ poll.service 1800s 안 끝남 — git pull 강행 (옛 코드 process 는 그대로 진행)"
            break
        fi
        sleep 5
    done
fi

git pull --ff-only
NEW=$(git rev-parse HEAD)
echo "[deploy] $LOCAL → $NEW"

# requirements.txt 변경되면 pip install
if git diff --name-only "$LOCAL" "$NEW" | grep -q '^requirements\.txt$'; then
    echo "[deploy] requirements.txt 변경 — pip install"
    .venv/bin/pip install -r requirements.txt
fi

# 코드 변경 영역 따라 봇 재시작
NEED_BOT_RESTART=0
if git diff --name-only "$LOCAL" "$NEW" | grep -qE '^(bot/|adapters/|engine/|scripts/notify|scripts/deliver_due)'; then
    NEED_BOT_RESTART=1
fi

if [ "$NEED_BOT_RESTART" = "1" ]; then
    echo "[deploy] notice-bot.service restart"
    systemctl --user restart notice-bot.service
fi

echo "[deploy] notice-poll.timer start"
systemctl --user start notice-poll.timer

echo "[deploy] done. HEAD=$NEW"
```

dev box 의 자동 deploy (Claude memory `feedback-commit-auto-deploy`) 가 호출하는 패턴:

```
ssh $DEPLOY_HOST 'bash ~/notice-watcher/scripts/n100_deploy.sh'
```

기존 `ssh $DEPLOY_HOST 'cd ~/notice-watcher && git pull --ff-only'` 직접 호출은 deprecated — 이 wrapper 로 대체. `feedback-commit-auto-deploy` 메모도 같이 수정.

### G2. poll.py 가 git_sha 영속화 + dashboard surface

ADR 0017 의 `poll_runs.git_sha` 컬럼. `_run_inner` 진입 시 `subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT)` (1회) 로 sha 박음. dashboard `/runs` 페이지가 sha 표시 + sha 가 *이전 run 과 다르면* 색 표시.

`poll_runs.started_at` + `git_sha` 의 결합으로 "어느 cron run 이 어느 commit 으로 돌았나" 영구 추적. 이번 incident 같은 race 가 다시 났을 때 사후 분석 1분 안 끝남.

ADR 0017 안에 이미 컬럼 정의됨 — 이 ADR 은 *왜* 그 컬럼을 박는지의 동기 명시.

### G3. cron timer 의 race window 안내

`deploy/notice-poll.timer` 주석에 ADR 0018 ref + 운영 메모 §8 의 deploy 사이클 안내. 새 운영자가 직접 `git pull` 하지 않게 — `n100_deploy.sh` 를 unique entry point 로.

## 3. Consequences

### 긍정

- (i) (iii) race window 둘 다 봉합 — `git pull` 진행 중에 새 폴링 fire 안 됨. 진행 중 폴링 끝난 뒤 새 코드로 timer 재가동.
- (ii) 부팅 직후 catch-up 은 `Persistent=true` 가 보장. wrapper 가 fire 막은 사이 missed trigger 도 같은 메커니즘.
- git_sha 영속화 → 사후 분석 가능.

### 부정·위험

- `n100_deploy.sh` 안의 1800s 대기 — 정상 폴링 7-15 분, 비정상 hang 도 ADR 0016 의 systemd `TimeoutStartSec=1200` 가 죽임. 대기 deadline 1800s 면 safety net 안에 들어옴.
- 그래도 hang 못 죽으면 `[deploy] ⚠ poll.service 1800s 안 끝남 — git pull 강행`. 옛 process 는 옛 코드로 끝까지 (Python 모듈 동적 reload X). race window 가 그 사이 좁아짐 — 완벽 X.
- ssh 호출 = N100 의 bash 스크립트 실행. 사용자 PATH·환경 차이 위험 — 절대 경로 사용 + `set -euo pipefail`.

### 비-결정 (다음 ADR 후보)

- *코드 자체* 가 file 변경 감지 → graceful restart 하는 패턴 (예: watchdog) — over-engineering, 안 박음.
- N100 ↔ dev box 의 secret deploy key 갱신 — scope 외.

## 4. 영구 게이트 (CLAUDE.md §8a)

이 ADR + `scripts/n100_deploy.sh` 가 영구 게이트. 동시에:

- `CLAUDE.md §2` (표준 배포 사이클) 의 N100 단계 = `n100_deploy.sh` 호출 1줄로 바꿈. raw `git pull` 호출은 deprecated 명시.
- `deploy/notice-poll.timer` 주석에 ADR 0018 ref.
- `docs/운영 메모.md` 의 deploy 사이클 §8 에 wrapper 안내.

memory `feedback-commit-auto-deploy` 도 update — auto deploy = `ssh ... 'bash ~/notice-watcher/scripts/n100_deploy.sh'`.

## 5. 검증

- dev box: `bash scripts/n100_deploy.sh` 의 local dry-run (timer/service stop·start 명령 안 실행 — set -n 으로 syntax 만).
- N100 첫 배포: 직접 `ssh n100 bash ~/notice-watcher/scripts/n100_deploy.sh` 호출 → log 흐름 확인.
- 다음 daily cron (08:20) 후 dashboard `/runs` 에 git_sha visible 확인.
- 의도적 race test: dev box hotfix 푸시 + 동시에 N100 에서 wrapper 호출 → log 가 "active service 진행 중 → 대기" 보여주는지.

## 6. 향후

- 1주 운영 후 1800s deadline 조정 여부.
- `poll_runs.git_sha` 다른 run 과 sha 변하면 dashboard 색 표시 — ADR 0017 의 UI 작업에 흡수.
