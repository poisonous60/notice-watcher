#!/bin/bash
# N100 runtime state backup → Google Drive (rclone). ADR 0014, docs/운영 메모.md §6b.
#
# 백업 범위 (사용자 visible 상태 + 비싼 학습 결과):
#   - output/bot.sqlite3   (subscriptions·user_settings·jobs·posts·deliveries)
#   - output/usage.sqlite3 (LLM 사용량 통계)
#   - output/poll_state/   (사이트별 baseline — 없으면 옛글 폭탄)
#   - output/learned_blacklist.json
#
# 백업 안 됨: .env (잃으면 token 재발급), configs/ (git clone 으로 복구).
#
# 호출자: deploy/notice-backup.service (systemd --user oneshot, 일 1회 04:30 KST).
# 수동 1회: systemctl --user start notice-backup.service  또는 직접 bash 이 스크립트.
# 복구: docs/운영 메모.md §1c.

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/notice-watcher}"
OUTPUT_DIR="$REPO_ROOT/output"
STAGING_DIR="${BACKUP_STAGING:-/tmp/notice-backup-staging}"
ARCHIVE_PATH="${BACKUP_ARCHIVE:-/tmp/notice-watcher-backup.tar.gz}"
RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-gdrive:notice-watcher-backup/notice-watcher-backup.tar.gz}"

log() { printf '[backup_runtime] %s\n' "$*"; }
fail() { printf '[backup_runtime] ERROR: %s\n' "$*" >&2; exit 1; }

trap 'rm -rf "$STAGING_DIR" "$ARCHIVE_PATH"' EXIT

[ -d "$OUTPUT_DIR" ] || fail "OUTPUT_DIR 없음: $OUTPUT_DIR"
command -v rclone >/dev/null 2>&1 || fail "rclone 미설치 (apt install rclone 또는 curl https://rclone.org/install.sh | sudo bash)"
command -v sqlite3 >/dev/null 2>&1 || fail "sqlite3 미설치"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

log "stage sqlite (lock-free .backup)"
for db in bot.sqlite3 usage.sqlite3; do
  src="$OUTPUT_DIR/$db"
  if [ -f "$src" ]; then
    sqlite3 "$src" ".backup '$STAGING_DIR/$db'"
    log "  $db ($(stat -c%s "$STAGING_DIR/$db") bytes)"
  else
    log "  $db 없음 — skip"
  fi
done

log "stage filesystem state"
if [ -d "$OUTPUT_DIR/poll_state" ]; then
  cp -a "$OUTPUT_DIR/poll_state" "$STAGING_DIR/poll_state"
  log "  poll_state ($(ls "$STAGING_DIR/poll_state" | wc -l) files)"
fi
if [ -f "$OUTPUT_DIR/learned_blacklist.json" ]; then
  cp "$OUTPUT_DIR/learned_blacklist.json" "$STAGING_DIR/learned_blacklist.json"
  log "  learned_blacklist.json ($(stat -c%s "$STAGING_DIR/learned_blacklist.json") bytes)"
fi

log "create archive"
tar -czf "$ARCHIVE_PATH" -C "$STAGING_DIR" .
archive_size=$(stat -c%s "$ARCHIVE_PATH")
log "  $ARCHIVE_PATH ($archive_size bytes)"
[ "$archive_size" -gt 1024 ] || fail "archive 너무 작음 ($archive_size bytes) — staging 비었을 가능성"

log "upload → $RCLONE_REMOTE"
rclone copyto "$ARCHIVE_PATH" "$RCLONE_REMOTE"

log "done"
