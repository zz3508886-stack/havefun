#Requires -Version 5.0
<#
.SYNOPSIS
  Review-system one-key launcher (Windows).
.DESCRIPTION
  1) Ensures backend venv (py -3 launcher, Python >= 3.11).
  2) Installs backend deps from requirements.txt.
  3) Builds frontend dist when npm is available (skipped otherwise;
     API still works, dev via `npm run dev` in frontend/).
  4) Starts uvicorn on http://127.0.0.1:8000 (Ctrl+C to stop).
.NOTES
  Run from app/:  .\start.ps1
  First run needs Python from python.org with "Add python.exe to PATH"
  ticked, and Node.js LTS (nvm-windows / fnm recommended).
#>
$ErrorActionPreference = 'Stop'

$AppRoot = $PSScriptRoot
$Backend = Join-Path $AppRoot 'backend'
$VenvDir = Join-Path $Backend '.venv'
$VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
$Frontend = Join-Path $AppRoot 'frontend'
$Dist = Join-Path $Frontend 'dist'
$Port = 8000

# 1. venv
if (-not (Test-Path $VenvPy)) {
    Write-Host '[1/4] creating venv ...'
    py -3 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw 'py launcher failed - install Python >= 3.11 from python.org and tick "Add python.exe to PATH"'
    }
}

# 2. backend deps
Write-Host '[2/4] installing backend deps ...'
& $VenvPy -m pip install -r (Join-Path $Backend 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# 3. frontend dist
if (Test-Path $Dist) {
    Write-Host '[3/4] frontend dist exists, skip build'
}
elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host '[3/4] building frontend (first run takes 1-3 min) ...'
    Push-Location $Frontend
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm run build failed' }
    }
    finally { Pop-Location }
}
else {
    Write-Host '[3/4] npm not found, skip frontend build (API still available)'
}

# 4. serve (foreground; browser opens before uvicorn blocks)
Write-Host "[4/4] serving http://127.0.0.1:$Port/  (Ctrl+C to stop)"
Start-Process "http://127.0.0.1:$Port/"
& $VenvPy -m uvicorn app.main:app --app-dir $Backend --host 127.0.0.1 --port $Port
