$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runner = Join-Path $repoRoot "scripts\run_knowledge_hub_export.bat"
$taskName = "tw-stock-ai-knowledge-hub-export"
$taskTime = "08:45"

if (-not (Test-Path $runner)) {
    throw "Missing runner: $runner"
}

$taskAction = "cmd.exe /c `"$runner`""

schtasks /Create /TN $taskName /TR $taskAction /SC DAILY /ST $taskTime /F | Out-Host

Write-Host "Installed scheduled task: $taskName"
Write-Host "Schedule: daily $taskTime"
Write-Host "Runner: $runner"
