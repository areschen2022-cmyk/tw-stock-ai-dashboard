param(
  [string]$Message = "Update dashboard"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$docs = Join-Path $root "docs"
$dashboard = Join-Path $root "dashboard"

New-Item -ItemType Directory -Force -Path $docs | Out-Null
Copy-Item -Force -Path (Join-Path $dashboard "dashboard.html") -Destination (Join-Path $docs "index.html")
Copy-Item -Force -Path (Join-Path $dashboard "dashboard_data.json") -Destination (Join-Path $docs "dashboard_data.json")
Copy-Item -Force -Path (Join-Path $dashboard "performance.html") -Destination (Join-Path $docs "performance.html")
Copy-Item -Force -Path (Join-Path $dashboard "performance_data.json") -Destination (Join-Path $docs "performance_data.json")

git add docs .gitignore .nojekyll scripts/publish_pages.ps1
if (-not (git diff --cached --quiet)) {
  git commit -m $Message
  git push
} else {
  Write-Host "No dashboard changes to publish."
}
