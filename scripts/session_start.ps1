# 동시 세션 격리 worktree 생성 (ADR 0015) — Windows PowerShell.
# usage: pwsh scripts\session_start.ps1 <tag>
#   <tag> = kebab-case 세션 식별자 (예: govedu-batch / dashboard-fix / debug-foo)
#
# 동작:
#   1. ..\nw-session-<tag>\ worktree + session-<tag> branch (main 기준)
#   2. .git\hooks\pre-push 카피 (worktree 별 hook dir 분리)
#   3. cd 경로 + 종료 명령 안내
#
# 1인 모드 (다른 세션 없음 사용자 명시) = wrapper skip, main 직접 편집 허용 (ADR 0015 §결정 2).
$ErrorActionPreference = 'Stop'

if (-not $args -or -not $args[0]) {
    Write-Host "[session_start] usage: pwsh scripts\session_start.ps1 <tag>" -ForegroundColor Red
    Write-Host "  <tag> = kebab-case 세션 식별자"
    exit 2
}

$TAG = $args[0]
if ($TAG -notmatch '^[a-zA-Z0-9-]+$') {
    Write-Host "[session_start] tag '$TAG' = kebab-case 만 (a-z A-Z 0-9 -)" -ForegroundColor Red
    exit 2
}

$ROOT = Resolve-Path (Join-Path $PSScriptRoot '..')
$PARENT = Split-Path $ROOT -Parent
$WT_PATH = Join-Path $PARENT "nw-session-$TAG"
$BRANCH = "session-$TAG"

if (Test-Path $WT_PATH) {
    Write-Host "[session_start] $WT_PATH 이미 존재 — drop 먼저: git worktree remove '$WT_PATH'; git branch -D $BRANCH" -ForegroundColor Red
    exit 1
}

Set-Location $ROOT

$existing = git rev-parse --verify $BRANCH 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[session_start] branch '$BRANCH' 이미 존재 — drop 먼저: git branch -D $BRANCH" -ForegroundColor Red
    exit 1
}

git worktree add $WT_PATH -b $BRANCH main
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$SH_HOOK = Join-Path $ROOT '.git\hooks\pre-push'
$WT_HOOK_DIR = Join-Path $ROOT ".git\worktrees\nw-session-$TAG\hooks"
if (Test-Path $SH_HOOK) {
    if (-not (Test-Path $WT_HOOK_DIR)) {
        New-Item -ItemType Directory -Force $WT_HOOK_DIR | Out-Null
    }
    Copy-Item $SH_HOOK (Join-Path $WT_HOOK_DIR 'pre-push') -Force
}

Write-Host ""
Write-Host "[session_start] worktree: $WT_PATH"
Write-Host "[session_start] branch  : $BRANCH (main 기준)"
Write-Host "[session_start] hook    : pre-push 카피됨 (probe_smoke --stage 3 --stage 5)"
Write-Host ""
Write-Host "다음 단계:"
Write-Host "  cd `"$WT_PATH`""
Write-Host "  # 작업 ..."
Write-Host "  git add <내가 만든·고친 파일>"
Write-Host "  git commit -m `"...`""
Write-Host "  git push -u origin $BRANCH      # 또는 main 으로 merge"
Write-Host ""
Write-Host "main 으로 merge (작업 완료):"
Write-Host "  cd `"$ROOT`""
Write-Host "  git merge-tree `$(git merge-base main $BRANCH) main $BRANCH | Select-String -Pattern conflict -SimpleMatch"
Write-Host "  git merge --no-ff $BRANCH"
Write-Host "  git push origin main"
Write-Host ""
Write-Host "폐기 (미커밋 변경 버림):"
Write-Host "  cd `"$ROOT`""
Write-Host "  git worktree remove `"$WT_PATH`""
Write-Host "  git branch -D $BRANCH"
