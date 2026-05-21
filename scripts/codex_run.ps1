<#
.SYNOPSIS
  codex 위임 launcher — codex exec 를 *보이는* PowerShell 창에서 실행 (사용자가 진행 관전).

.DESCRIPTION
  ADR 0008 의 "확정 경로 = codex CLI 직접" 을 재사용 가능한 형태로 박은 것.
  - 진입(triage·진단 entry)·검토(diff 리뷰)·commit/push/배포 = Claude (이 스크립트 밖).
  - 중간 orchestration(probe 읽기·fix 작성·probe_smoke) = codex, 이 창 안에서.
  - Claude 토큰 0 (codex 가 LLM 일 전담), broker 우회 → codex-plugin-cc#330 deadlock 비해당.

  창 = codex 콘솔 직접 출력 (live, native 색). Tee/리다이렉트 안 함 — PowerShell Tee-Object 는
  파이프 종료까지 파일을 버퍼링(live 안 흐름)하고 UTF-16 으로 쓴다. 2>&1 머지하면 stderr 가
  ErrorRecord 로 감싸져 전부 빨개진다. 둘 다 피함 → 창은 codex 가 직접 그린다.

  Claude(완료감지·검토)는 `-o, --output-last-message` 가 쓰는 *결과 파일*(UTF-8 최종응답)을 본다.
  진행 중 hang 은 *사용자가 이 창으로* 본다 (창이 안 자라면 멈춘 것 — 사용자 원래 요구).
  완료 감지 = scripts/codex_watch.py <ResultFile>.

  창은 -NoExit 로 유지 → 끝나도 스크롤백 확인 가능.

.PARAMETER PromptFile
  codex stdin 으로 먹일 프롬프트 (UTF-8). HARD-STOP 제약(commit/push 금지)은 프롬프트 본문에
  박혀 있어야 함 — generate/codex_handoff.py 빌더 참고.

.PARAMETER ResultFile
  codex 최종 메시지를 쓸 파일 (-o). 미지정 시 PromptFile → .result.md.

.PARAMETER Title
  창 머리말.

.EXAMPLE
  pwsh scripts/codex_run.ps1 -PromptFile output/codex_handconfig_foo_prompt.txt -Title "hand-config: foo"
#>
param(
    [Parameter(Mandatory = $true)][string]$PromptFile,
    [string]$ResultFile,
    [string]$Title = "codex"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path $PromptFile)) {
    throw "PromptFile not found: $PromptFile"
}
$promptAbs = (Resolve-Path $PromptFile).Path
if (-not $ResultFile) {
    $ResultFile = [System.IO.Path]::ChangeExtension($promptAbs, ".result.md")
}
# 이전 run 결과 잔존 제거 — codex_watch 가 stale 결과를 DONE 으로 오인 안 하게.
if (Test-Path $ResultFile) { Remove-Item -LiteralPath $ResultFile -Force }

# -NoExit 로 띄우되, codex 성공(rc=0) 시 명시 exit 로 자동 닫음(사용자 요구). 실패면 창 유지(검토).
$inner = @"
Set-Location '$repo'
Write-Host '=== CODEX: $Title ===' -ForegroundColor Cyan
Write-Host 'prompt: $promptAbs' -ForegroundColor DarkGray
Write-Host 'result: $ResultFile' -ForegroundColor DarkGray
Write-Host '(이 창이 진행 view — 안 자라면 멈춘 것. Claude 는 result 파일로 완료 감지.)' -ForegroundColor DarkGray
Write-Host ''
Get-Content -Raw -Encoding UTF8 '$promptAbs' | codex exec --dangerously-bypass-approvals-and-sandbox -o '$ResultFile' -
`$rc = `$LASTEXITCODE
Write-Host ''
if (`$rc -eq 0) {
    Write-Host '=== DONE (rc=0) — 3초 후 자동 닫힘. Claude 가 diff 검토 후 commit. ===' -ForegroundColor Cyan
    Start-Sleep -Seconds 3
    exit 0
} else {
    Write-Host "=== FAILED (rc=`$rc) — 창 유지(검토용). 닫으려면 exit. ===" -ForegroundColor Red
}
"@

Start-Process powershell -ArgumentList '-NoExit', '-Command', $inner
Write-Host "[codex_run] launched visible window. title='$Title' result=$ResultFile"
