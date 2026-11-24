$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64') {
    throw 'Ce binaire Bergamot requiert Windows x64.'
}

$dataPath = if ($env:LOCALDOC_DATA) { $env:LOCALDOC_DATA } else { 'data' }
$dataPath = (New-Item -ItemType Directory -Force -Path $dataPath).FullName
$installPath = Join-Path $dataPath 'bergamot'
$stage = (New-Item -ItemType Directory -Path (Join-Path $dataPath ('.bergamot-install-' + [guid]::NewGuid()))).FullName

function Get-VerifiedFile($Url, $Path, $Sha256) {
    & curl.exe --fail --silent --show-error --location --retry 2 --max-time 120 --output $Path $Url
    if ($LASTEXITCODE -ne 0) { throw "Telechargement impossible : $Url" }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) {
        throw "Somme SHA-256 incorrecte : $Url"
    }
}

# Official Windows build from release 8e31cff and the two Bergamot catalog archives.
$binary = 'translateLocally.exe'
$binaryUrl = 'https://github.com/XapaJIaMnu/translateLocally/releases/download/latest/translateLocally.windows-2022.core-avx-i.exe'
$binaryHash = 'B7CB0F58369CC508812F049AF8C07ED59F2340E8007D31EE672DCEF450E53AA4'
$models = @(
    @{
        Code = 'fr-en-tiny'; Folder = 'fren.student.tiny11'
        Url = 'https://data.statmt.org/bergamot/models/fren/fren.student.tiny11.v1.dccea16d03c0a389.tar.gz'
        Hash = 'DCCEA16D03C0A3897B4CE085DB676AE4BB2777F7E2B1755C04C0F92EFA894B01'
    },
    @{
        Code = 'en-fr-tiny'; Folder = 'enfr.student.tiny11'
        Url = 'https://data.statmt.org/bergamot/models/fren/enfr.student.tiny11.v1.805d112122af03d0.tar.gz'
        Hash = '805D112122AF03D0FE2769EACAAAF5A9EAC2C4B97E862A5B2CF0EB95862A7EFB'
    }
)

try {
    Write-Host 'Telechargement de Bergamot et des modeles francais-anglais...'
    Get-VerifiedFile $binaryUrl (Join-Path $stage $binary) $binaryHash
    foreach ($model in $models) {
        $archive = Join-Path $stage ($model.Code + '.tar.gz')
        Get-VerifiedFile $model.Url $archive $model.Hash
        & tar.exe -xf $archive -C $stage
        if ($LASTEXITCODE -ne 0) { throw "Extraction impossible : $($model.Code)" }
    }
    New-Item -ItemType Directory -Force -Path $installPath | Out-Null
    foreach ($model in $models) {
        $destination = Join-Path $installPath $model.Code
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $stage $model.Folder) -File | ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
    }
    Move-Item -LiteralPath (Join-Path $stage $binary) -Destination $installPath -Force
    Write-Host 'Bergamot installe. Rouvrez le document et choisissez Bergamot (CPU) dans Traduire.' -ForegroundColor Green
} finally {
    $resolvedStage = (Resolve-Path -LiteralPath $stage).ProviderPath
    if ((Split-Path $resolvedStage -Parent) -eq $dataPath -and
            (Split-Path $resolvedStage -Leaf) -match '^\.bergamot-install-[0-9a-f-]{36}$') {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
