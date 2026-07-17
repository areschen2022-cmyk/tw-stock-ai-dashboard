param(
  [string]$Message = "Update dashboard"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$docs = Join-Path $root "docs"
$dashboard = Join-Path $root "dashboard"

New-Item -ItemType Directory -Force -Path $docs | Out-Null

$dashboardIndexCandidates = @(
  (Join-Path $dashboard "index.html"),
  (Join-Path $dashboard "dashboard.html")
)
$dashboardIndex = $dashboardIndexCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $dashboardIndex) {
  throw "No dashboard HTML found. Expected one of: $($dashboardIndexCandidates -join ', ')"
}

Copy-Item -Force -Path $dashboardIndex -Destination (Join-Path $docs "index.html")
Copy-Item -Force -Path (Join-Path $dashboard "dashboard_data.json") -Destination (Join-Path $docs "dashboard_data.json")
Copy-Item -Force -Path (Join-Path $dashboard "performance.html") -Destination (Join-Path $docs "performance.html")
Copy-Item -Force -Path (Join-Path $dashboard "performance_data.json") -Destination (Join-Path $docs "performance_data.json")
if (Test-Path (Join-Path $dashboard "potential.html")) {
  Copy-Item -Force -Path (Join-Path $dashboard "potential.html") -Destination (Join-Path $docs "potential.html")
}
if (Test-Path (Join-Path $dashboard "potential_data.json")) {
  Copy-Item -Force -Path (Join-Path $dashboard "potential_data.json") -Destination (Join-Path $docs "potential_data.json")
}
if (Test-Path (Join-Path $dashboard "weekly.html")) {
  Copy-Item -Force -Path (Join-Path $dashboard "weekly.html") -Destination (Join-Path $docs "weekly.html")
}
if (Test-Path (Join-Path $dashboard "weekly_data.json")) {
  Copy-Item -Force -Path (Join-Path $dashboard "weekly_data.json") -Destination (Join-Path $docs "weekly_data.json")
}
if (Test-Path (Join-Path $dashboard "theme_history.json")) {
  Copy-Item -Force -Path (Join-Path $dashboard "theme_history.json") -Destination (Join-Path $docs "theme_history.json")
}
foreach ($name in @("debug_data.json", "backtest_review.json", "weekly_review.json", "backtest_30y.json", "cloud_skill_routes_status.json")) {
  $source = Join-Path $dashboard $name
  if (Test-Path $source) {
    Copy-Item -Force -Path $source -Destination (Join-Path $docs $name)
  }
}

git add docs .gitignore .nojekyll scripts/publish_pages.ps1
if (-not (git diff --cached --quiet)) {
  git commit -m $Message
  git push
} else {
  Write-Host "No dashboard changes to publish."
}
