# Starts the Luxion backend (FastAPI) and frontend (Vite) together.
# Usage: .\scripts\dev.ps1   (Ctrl+C stops both)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host "Creating backend venv..." -ForegroundColor Cyan
    python -m venv (Join-Path $backend '.venv')
    & $python -m pip install --upgrade pip --quiet
    & (Join-Path $backend '.venv\Scripts\pip.exe') install -e "$(Join-Path $backend '.')[dev]" --quiet
}

Write-Host "Starting backend on http://127.0.0.1:8756 ..." -ForegroundColor Cyan
$backendProc = Start-Process -FilePath $python -ArgumentList '-m', 'luxion' `
    -WorkingDirectory $backend -PassThru -WindowStyle Minimized

Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
$frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' `
    -WorkingDirectory $frontend -PassThru -WindowStyle Minimized

try {
    Write-Host "Backend  -> http://127.0.0.1:8756/api/health" -ForegroundColor Green
    Write-Host "Frontend -> http://localhost:5173" -ForegroundColor Green
    Write-Host "Press Ctrl+C to stop both." -ForegroundColor Yellow
    while ($true) {
        Start-Sleep -Seconds 2
        if ($backendProc.HasExited)  { throw "Backend exited (code $($backendProc.ExitCode))" }
        if ($frontendProc.HasExited) { throw "Frontend exited (code $($frontendProc.ExitCode))" }
    }
}
finally {
    Write-Host "Stopping dev servers..." -ForegroundColor Yellow
    foreach ($proc in @($backendProc, $frontendProc)) {
        if ($proc -and -not $proc.HasExited) {
            # npm spawns a child cmd -> kill the whole tree on Windows
            & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
        }
    }
}
