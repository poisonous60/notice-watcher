# git hooks 설치 — scripts\pre-push.sh → .git\hooks\pre-push
# Windows PowerShell. .git/hooks/ 는 git 추적 X 라 dev 박스마다 한 번씩 실행.
$ErrorActionPreference = 'Stop'

$ROOT = Resolve-Path (Join-Path $PSScriptRoot '..')
$HOOK_DIR = Join-Path $ROOT '.git\hooks'
$SRC = Join-Path $ROOT 'scripts\pre-push.sh'
$DST = Join-Path $HOOK_DIR 'pre-push'

if (-not (Test-Path $HOOK_DIR)) {
    Write-Error "[setup-hooks] $HOOK_DIR 없음 (repo 가 아닌가?) — 중단"
    exit 1
}

Copy-Item $SRC $DST -Force
Write-Host "[setup-hooks] installed: $DST"
# Git for Windows 는 sh hook 을 자동으로 sh.exe 로 실행 — chmod 불필요.
