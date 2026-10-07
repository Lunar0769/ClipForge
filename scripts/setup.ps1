$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "ClipForge setup" -ForegroundColor Magenta
foreach ($cmd in "uv", "node", "npm", "ffmpeg", "ffprobe") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Missing '$cmd'. Install it and re-run. (uv: https://docs.astral.sh/uv/ - FFmpeg 8 full build: winget install Gyan.FFmpeg)"
    }
}

Write-Host "`n> Backend dependencies" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try { uv sync; if ($LASTEXITCODE) { throw "uv sync failed" } } finally { Pop-Location }

Write-Host "`n> Frontend dependencies" -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
try { npm install; if ($LASTEXITCODE) { throw "npm install failed" } } finally { Pop-Location }

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }

Write-Host "`n> Whisper model (about 1.6 GB, first run only)" -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
try {
    uv run python -m app.cli download-models; if ($LASTEXITCODE) { throw "model download failed" }
    Write-Host "`n> Health check" -ForegroundColor Cyan
    uv run python -m app.cli doctor
} finally { Pop-Location }

Write-Host ""
Write-Host "Done! Next steps:" -ForegroundColor Green
Write-Host "  1. Open .env and add an LLM key (ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY)" -ForegroundColor Yellow
Write-Host "  2. Run: ./scripts/dev.ps1" -ForegroundColor Yellow
Write-Host "  3. Open http://localhost:5173, paste a YouTube URL and hit Forge" -ForegroundColor Yellow
