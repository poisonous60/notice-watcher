#!/bin/sh
# git hooks 설치 — scripts/pre-push.sh → .git/hooks/pre-push
# (`.git/hooks/` 는 git 추적 X 라서 dev 박스마다 한 번씩 실행 필요.)
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$ROOT/.git/hooks"
SRC="$ROOT/scripts/pre-push.sh"
DST="$HOOK_DIR/pre-push"

if [ ! -d "$HOOK_DIR" ]; then
  echo "[setup-hooks] $HOOK_DIR 없음 (repo 가 아닌가?) — 중단" >&2
  exit 1
fi

cp "$SRC" "$DST"
chmod +x "$DST"
echo "[setup-hooks] installed: $DST"
