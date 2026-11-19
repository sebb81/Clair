param([ValidateSet('qwen2','qwen25-15b','qwen3-4b')][string]$Model = 'qwen2')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$folder = Join-Path $(if ($env:LOCALDOC_DATA) { $env:LOCALDOC_DATA } else { 'data' }) "webnn-model/$Model"
if ($Model -eq 'qwen3-4b') {
    $python = (Resolve-Path '.venv/Scripts/python.exe').Path
    & $python -c 'from app.webnn import MODELS, QWEN3; raise SystemExit(0 if MODELS[QWEN3].installed() else 1)'
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'Qwen3 4B est deja installe.'
        return
    }
    & $python -m scripts.fetch_webnn_candidate Qwen3-4B
    if ($LASTEXITCODE -ne 0) { throw 'Telechargement Qwen3 4B incomplet. Relancez cette commande pour reprendre.' }

    $tools = (New-Item -ItemType Directory -Force 'data/webnn-bench/onnx-tools').FullName
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $tools
        if (-not (Test-Path (Join-Path $tools 'onnx'))) {
            & $python -m pip install --target $tools 'onnx==1.20.0'
            if ($LASTEXITCODE -ne 0) { throw 'Installation des outils ONNX impossible.' }
        }
        & $python -m scripts.prepare_webnn_graph qwen3-4b
        if ($LASTEXITCODE -ne 0) { throw 'Preparation du graphe Qwen3 4B impossible.' }
    } finally { $env:PYTHONPATH = $previousPythonPath }

    $source = 'data/webnn-bench/qwen3-4b'
    New-Item -ItemType Directory -Force $folder | Out-Null
    foreach ($asset in @('tokenizer.json','tokenizer_config.json','webnn/model.onnx','webnn/weights-0.data','webnn/weights-1.data')) {
        $target = Join-Path $folder (Split-Path $asset -Leaf)
        Copy-Item -LiteralPath (Join-Path $source $asset) -Destination "$target.part" -Force
        Move-Item -LiteralPath "$target.part" -Destination $target -Force
    }
    & $python -c 'from app.webnn import MODELS, QWEN3; raise SystemExit(0 if MODELS[QWEN3].installed() else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Installation Qwen3 4B incomplete.' }
    Write-Host 'Qwen3 4B est installe. Rechargez Clair.'
    return
}
$revision = 'e4a5ce8c87de70975278a72ff575182318a16684'
$base = "https://huggingface.co/webnn/Qwen2-0.5B-Instruct-onnx/resolve/$revision"
$files = [ordered]@{
    'tokenizer.json' = 11418266
    'tokenizer_config.json' = 1373
    'model.onnx' = 242285
    'model.onnx.data' = 554459904
}
$checksums = @{
    'tokenizer.json' = 'bcfe42da0a4497e8b2b172c1f9f4ec423a46dc12907f4349c55025f670422ba9'
    'tokenizer_config.json' = '9dcd9322b895599d2422456442e9f9152ff96da9aa9ac5e5beA4e089b9727a7f'
    'model.onnx' = 'af6a2a4c0d095db4c90ec0e863d49172aa791aab875fa4df2a6c366b2aa9108d'
    'model.onnx.data' = 'cc9f2db236f19bd689ea0f2338ed23405cfbed5f5eeb07a8a708e6b8a9896e0d'
}
if ($Model -eq 'qwen25-15b') {
    $revision = 'f931fb97de0e3330582d332831f8ea3c65d00595'
    $base = "https://huggingface.co/keystone-systems/Qwen2.5-1.5B-Instruct-onnx-dml-int4/resolve/$revision"
    $files = [ordered]@{
        'tokenizer.json' = 11421892
        'tokenizer_config.json' = 721
        'model.onnx' = 310715
        'model.onnx.data' = 1343750144
    }
    $checksums = @{
        'tokenizer.json' = '3fd169731d2cbde95e10bf356d66d5997fd885dd8dbb6b4684da3f23b2585d8'
        'tokenizer_config.json' = '415b7f0fb037ee2a98f8ab6e7e2ba9e3d43ac270a992bdd149b008d25f69918f'
        'model.onnx' = '09d14950e1e362ab5b3e783f1711af9c81793acb2646f30f63effdaae77a11bc'
        'model.onnx.data' = '6f13389c8f11c0deb0ba855aa5e6450326312576b8bf10f60913f94451f0dfa3'
    }
}
New-Item -ItemType Directory -Force $folder | Out-Null
foreach ($entry in $files.GetEnumerator()) {
    $path = Join-Path $folder $entry.Key
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -eq $entry.Value) { continue }
    Write-Host "Telechargement du modele WebNN : $($entry.Key) ($([math]::Round($entry.Value / 1MB)) Mio)"
    & curl.exe -fL --retry 2 --progress-bar "$base/$($entry.Key)" -o "$path.part"
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath "$path.part").Length -ne $entry.Value) {
        throw "Telechargement WebNN incomplet : $($entry.Key). Relancez installer.bat."
    }
    if ((Get-FileHash -LiteralPath "$path.part").Hash -ne $checksums[$entry.Key]) {
        throw "Le fichier WebNN ne correspond pas a la version attendue : $($entry.Key)."
    }
    Move-Item -LiteralPath "$path.part" -Destination $path -Force
}
