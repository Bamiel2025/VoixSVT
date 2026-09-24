$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw "uv est requis. Installez-le avec: winget install --id=astral-sh.uv -e"
}

if (-not (Test-Path -LiteralPath "$root\.venv\Scripts\python.exe")) {
    uv venv --python 3.11 "$root\.venv"
}

uv pip install --python "$root\.venv\Scripts\python.exe" -e "$root[whisper-win,dev]"

Write-Host ""
Write-Host "Installation terminée." -ForegroundColor Green
Write-Host "Lancer l'application avec .\start.ps1"
