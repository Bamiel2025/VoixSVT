$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Environnement absent. Exécutez d'abord $root\install.ps1"
}
Set-Location -LiteralPath $root

$url = 'http://127.0.0.1:8765'

function Test-ServeurPret {
    try {
        $reponse = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 2
        return $reponse.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (Test-ServeurPret) {
    Write-Host "Le serveur tourne déjà : $url" -ForegroundColor Yellow
    Start-Process $url
    return
}

$serveur = Start-Process -FilePath $python -ArgumentList '-m', 'app.main' -WorkingDirectory $root -PassThru -NoNewWindow
$pret = $false
for ($essai = 0; $essai -lt 60; $essai++) {
    if ($serveur.HasExited) { break }
    Start-Sleep -Milliseconds 500
    if (Test-ServeurPret) { $pret = $true; break }
}

if ($pret) {
    Write-Host "Application prête : $url" -ForegroundColor Green
    Start-Process $url
} elseif ($serveur.HasExited) {
    Write-Host "Le serveur s'est arrêté (code $($serveur.ExitCode))." -ForegroundColor Red
} else {
    Write-Host "Le serveur n'a pas répondu dans les 30 secondes." -ForegroundColor Red
}

Wait-Process -Id $serveur.Id
