#Requires -Version 5.0
<#
.SYNOPSIS
  Review-system one-key launcher (Windows) - compatibility entry.
.DESCRIPTION
  Real logic lives in the cross-platform launcher start.py (python check,
  venv, deps, frontend build, browser, uvicorn). This file is kept only for
  backward compatibility with older docs and habits; normal users should
  double-click 启动服务.bat instead. Equivalent: python start.py
.NOTES
  Prereqs: Python >= 3.11 from python.org with "Add python.exe to PATH"
  ticked; Node.js LTS optional (only for first-run frontend build).
#>
$ErrorActionPreference = 'Stop'
$AppRoot = $PSScriptRoot
$Py = $null
foreach ($Name in @('py', 'python', 'python3')) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) { $Py = $Name; break }
}
if (-not $Py) {
    throw '未找到 Python。请安装 Python >= 3.11（https://www.python.org/downloads/ ），安装时勾选 Add python.exe to PATH；详见同目录《启动说明.md》第三节。'
}
$StartPy = Join-Path $AppRoot 'start.py'
if ($Py -eq 'py') { & py -3 $StartPy @args } else { & $Py $StartPy @args }
