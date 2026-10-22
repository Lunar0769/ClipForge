$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "ClipForge update" -ForegroundColor Magenta
Push-Location $root
try {
    $dirty = git status --porcelain --untracked-files=no
    if ($dirty) {
        throw "You have local code changes. Commit or stash them first, then run this again."
    }
    $before = (Get-Content (Join-Path $root "backend/app/__init__.py") | Select-String '__version__').ToString()

    Write-Host "`n> Downloading the latest version" -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE) { throw "git pull failed - check your internet connection or branch." }
    git fetch --tags --quiet

    Write-Host "`n> Updating backend dependencies" -ForegroundColor Cyan
    Push-Location (Join-Path $root "backend")
    try {
        uv sync
        if ($LASTEXITCODE) { throw "uv sync failed" }
        uv run python -m app.cli download-models
        if ($LASTEXITCODE) { throw "model download failed" }
    } finally { Pop-Location }

    Write-Host "`n> Updating frontend dependencies" -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend")
    try {
        npm install
        if ($LASTEXITCODE) { throw "npm install failed" }
    } finally { Pop-Location }

    $after = (Get-Content (Join-Path $root "backend/app/__init__.py") | Select-String '__version__').ToString()
    Write-Host "`nUpdated: $before -> $after" -ForegroundColor Green
    Write-Host "Your projects and settings in workspace/ are untouched. Restart with: ./scripts/dev.ps1" -ForegroundColor Green
} finally { Pop-Location }
