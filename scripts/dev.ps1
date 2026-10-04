$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$healthUrl = "http://127.0.0.1:8000/api/health"

Write-Host "Starting ClipForge API on http://127.0.0.1:8000 (new window)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location -LiteralPath '$backend'; uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir app"
)

Write-Host "Waiting for the API to come up..." -ForegroundColor Cyan
$apiUp = $false
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $apiUp = $true
            break
        }
    } catch {
        # Not listening yet; keep polling.
    }
    Start-Sleep -Milliseconds 500
}
if ($apiUp) {
    Write-Host "API is up." -ForegroundColor Green
} else {
    Write-Warning "The API did not answer at $healthUrl within 30 seconds. Check the API window for errors (run scripts\setup.ps1 first if you have not). Starting the UI anyway."
}

Write-Host "Starting UI on http://localhost:5173 ..." -ForegroundColor Cyan
Set-Location -LiteralPath $frontend
npm run dev
