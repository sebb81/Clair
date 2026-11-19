$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
Write-Host 'Installation de Clair et du modele WebNN (environ 566 Mo au premier lancement).'
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 ou plus recent est requis.' }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Echec installation Python.' }
Push-Location web
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Echec installation frontend. Node.js 20.19+ est requis.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Echec construction frontend.' }
} finally { Pop-Location }
& "$PSScriptRoot\installer-webnn.ps1"
Write-Host 'Installation terminee. Lancez demarrer.bat.' -ForegroundColor Green
