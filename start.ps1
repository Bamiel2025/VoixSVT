$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Environnement absent. Exécutez d'abord D:\IA\CorrecteurAuto\install.ps1"
}
Set-Location -LiteralPath $root
& $python -m app.main
