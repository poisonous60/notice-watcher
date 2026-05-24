#!/bin/sh
# 동시 세션 격리 worktree 생성 (ADR 0015).
# usage: bash scripts/session_start.sh <tag>
#   <tag> = kebab-case 세션 식별자 (예: govedu-batch / dashboard-fix / debug-foo)
#
# 동작:
#   1. ../nw-session-<tag>/ worktree + session-<tag> branch (main 기준)
#   2. .git/hooks/pre-push 카피 (worktree 별 hook dir 분리)
#   3. cd 경로 + 종료 명령 안내
#
# 1인 모드 (다른 세션 없음 사용자 명시) = wrapper skip, main 직접 편집 허용 (ADR 0015 §결정 2).
set -e

if [ -z "$1" ]; then
  echo "[session_start] usage: bash scripts/session_start.sh <tag>" >&2
  echo "  <tag> = kebab-case 세션 식별자" >&2
  exit 2
fi

TAG="$1"
case "$TAG" in
  *[!a-zA-Z0-9-]*)
    echo "[session_start] tag '$TAG' = kebab-case 만 (a-z A-Z 0-9 -)" >&2
    exit 2
  ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
WT_PATH="$PARENT/nw-session-$TAG"
BRANCH="session-$TAG"

if [ -e "$WT_PATH" ]; then
  echo "[session_start] $WT_PATH 이미 존재 — drop 먼저: git worktree remove '$WT_PATH'; git branch -D $BRANCH" >&2
  exit 1
fi

cd "$ROOT"

if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "[session_start] branch '$BRANCH' 이미 존재 — drop 먼저: git branch -D $BRANCH" >&2
  exit 1
fi

git worktree add "$WT_PATH" -b "$BRANCH" main
SH_HOOK="$ROOT/.git/hooks/pre-push"
WT_HOOK_DIR="$ROOT/.git/worktrees/nw-session-$TAG/hooks"
if [ -f "$SH_HOOK" ]; then
  mkdir -p "$WT_HOOK_DIR"
  cp "$SH_HOOK" "$WT_HOOK_DIR/pre-push"
  chmod +x "$WT_HOOK_DIR/pre-push"
fi

cat <<EOF
[session_start] worktree: $WT_PATH
[session_start] branch  : $BRANCH (main 기준)
[session_start] hook    : pre-push 카피됨 (probe_smoke --stage 3 --stage 5)

다음 단계:
  cd "$WT_PATH"
  # 작업 ...
  git add <내가 만든·고친 파일>
  git commit -m "..."
  git push -u origin $BRANCH      # 또는 main 으로 merge

main 으로 merge (작업 완료):
  cd "$ROOT"
  git merge-tree \$(git merge-base main $BRANCH) main $BRANCH | grep -i conflict   # 사전 확인
  git merge --no-ff $BRANCH
  git push origin main

폐기 (미커밋 변경 버림):
  cd "$ROOT"
  git worktree remove "$WT_PATH"
  git branch -D $BRANCH
EOF
