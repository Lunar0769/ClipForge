$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "Starting ClipForge API on http://127.0.0.1:8000 (new window)…" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location -LiteralPath '$backend'; uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir app"
)

Write-Host "Starting UI on http://localhost:5173 …" -ForegroundColor Cyan
Set-Location -LiteralPath $frontend
npm run dev
