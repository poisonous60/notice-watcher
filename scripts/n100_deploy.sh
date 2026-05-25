#!/usr/bin/env bash
# ADR 0018 — cron × commit race 가드. N100 에서 실행 (dev box 는 ssh 로 호출).
#
# 흐름:
#   1. git fetch — 변경 없으면 즉시 종료.
#   2. notice-poll.timer 만 stop (active service 는 안 건드림).
#      → 이 시점 이후 EXIT trap 이 timer 를 무조건 다시 start (실패 path 포함).
#   3. 진행 중 폴링 service 가 있으면 끝날 때까지 대기 (최대 1800s).
#      ADR 0016 의 systemd TimeoutStartSec=1200 가 외곽 safety net.
#   4. git pull --ff-only.
#   5. requirements.txt 변경 시 pip install.
#   6. bot 코드 변경 영역 보고 notice-bot.service restart.
#   7. notice-poll.timer start (Persistent=true 가 missed trigger catch-up).
#      (정상 종료. EXIT trap 도 같은 start 시도 — idempotent 라 무해.)
#
# dev box 가 호출하는 표준 패턴:
#   ssh $DEPLOY_HOST 'bash ~/notice-watcher/scripts/n100_deploy.sh'
#
# raw `git pull` 직접 호출은 deprecated — race window (cron×commit) 가 안 닫힘.
#
# **최초 배포 (one-time bootstrap)** — 이 script 가 N100 에 아직 없을 때:
#   ssh $DEPLOY_HOST 'cd ~/notice-watcher && git pull --ff-only'
#   # 이 1회 만 raw pull 허용. 이후 모든 deploy 는 wrapper 사용.
#   ssh $DEPLOY_HOST 'chmod +x ~/notice-watcher/scripts/n100_deploy.sh'
#   ssh $DEPLOY_HOST 'bash ~/notice-watcher/scripts/n100_deploy.sh'   # 다음부터 wrapper

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[deploy] git fetch…"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[deploy] already up to date ($LOCAL) — nothing to do."
    exit 0
fi

# CRITICAL — timer stop 직후 EXIT trap 설치. 이후 어떤 path (git pull conflict, pip fail, restart fail
# 등) 에서 죽어도 trap 이 timer 를 다시 start 한다. trap 안 박았으면 timer 가 stopped 상태로 영구
# 정지 → daily poll 미수행 = 이번 incident 보다 더 나쁜 silent outage.
TIMER_STOPPED=0
restart_timer_on_exit() {
    rc=$?
    if [ "$TIMER_STOPPED" = "1" ]; then
        echo "[deploy] EXIT trap — notice-poll.timer 복구 시도 (rc=$rc)"
        systemctl --user start notice-poll.timer || \
            echo "[deploy] ⚠ EXIT trap timer start 실패 — 손-점검 필요"
    fi
    exit "$rc"
}
trap restart_timer_on_exit EXIT

echo "[deploy] notice-poll.timer stop (active service 는 안 건드림)…"
systemctl --user stop notice-poll.timer
TIMER_STOPPED=1

# 이미 active 인 폴링 service 가 있으면 끝날 때까지 대기 (최대 30분).
# 정상 폴링 7-15분. ADR 0016 의 systemd TimeoutStartSec=1200 가 외곽 safety net.
if systemctl --user is-active --quiet notice-poll.service; then
    echo "[deploy] notice-poll.service 진행 중 — 끝날 때까지 대기 (최대 1800s)…"
    deadline=$((SECONDS + 1800))
    while systemctl --user is-active --quiet notice-poll.service; do
        if [ "$SECONDS" -gt "$deadline" ]; then
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

# 코드 변경 영역 따라 봇 재시작 (CLAUDE.md §2 의 트리거 영역과 일치)
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
TIMER_STOPPED=0  # 정상 start 완료 → EXIT trap 의 재시도 skip

echo "[deploy] done. HEAD=$NEW"
