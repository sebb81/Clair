param([switch]$NoBrowser, [switch]$GpuHautePerformance)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv\Scripts\python.exe') -or -not (Test-Path 'web\dist\index.html')) {
    & "$PSScriptRoot\installer.ps1"
}
New-Item -ItemType Directory -Force data | Out-Null
$root = (Get-Location).Path
$url = 'http://127.0.0.1:8765'
function Open-Clair {
    if ($NoBrowser) { return }
    $edge = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $edge) { throw 'Microsoft Edge est requis. Installez-le puis relancez demarrer.bat.' }
    $profile = Join-Path $root 'data\edge-webnn'
    $edgeArgs = @("--user-data-dir=`"$profile`"", '--enable-features=WebMachineLearningNeuralNetwork', '--no-first-run')
    if ($GpuHautePerformance) { $edgeArgs += '--force-high-performance-gpu' }
    Start-Process -FilePath $edge -ArgumentList ($edgeArgs + $url)
}
$healthy = $false
$health = $null
try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 6; $healthy = $health.mode -eq 'webnn' } catch {}
if ($healthy) { Open-Clair; Write-Host 'Clair est deja lance.'; exit 0 }
if ($health) { throw 'Une ancienne version de Clair occupe le port 8765. Lancez arreter.bat puis demarrer.bat.' }
$server = Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765','--no-access-log' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput 'data\server.log' -RedirectStandardError 'data\server-error.log' -PassThru
$server.Id | Set-Content data\server.pid
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-RestMethod "$url/api/documents" -TimeoutSec 2 | Out-Null
    } catch { continue }
    Open-Clair
    Write-Host "Clair : $url" -ForegroundColor Green
    Write-Host 'Les syntheses avancent dans le panneau du document. Journaux : data\server-error.log'
    exit 0
}
throw 'Le serveur ne repond pas. Consultez data\server-error.log.'
