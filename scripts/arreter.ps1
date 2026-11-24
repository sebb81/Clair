$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path 'data\server.pid') {
    $serverId = [int](Get-Content 'data\server.pid')
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverId" -ErrorAction SilentlyContinue
    $expected = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
    if ($process -and $process.ExecutablePath -eq $expected -and $process.CommandLine -like '*uvicorn*app.main:app*8765*') {
        $nativeRoot = Join-Path (Get-Location).Path 'data\cpu-bench'
        # On Windows the venv launcher starts a second Python process.
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$serverId" |
            Where-Object { $_.CommandLine -like '*-m uvicorn app.main:app --host 127.0.0.1 --port 8765*' } |
            ForEach-Object {
                $workerId = $_.ProcessId
                Get-CimInstance Win32_Process -Filter "ParentProcessId=$workerId AND Name='llama-server.exe'" |
                    Where-Object { $_.ExecutablePath -like "$nativeRoot\*\llama-server.exe" } |
                    ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
                Stop-Process -Id $workerId -ErrorAction SilentlyContinue
            }
        Stop-Process -Id $serverId -ErrorAction SilentlyContinue
        Write-Host 'Serveur Clair arrete. Les documents et les lots termines sont conserves.'
    } else { Write-Host 'Aucun processus Clair correspondant au PID enregistre.' }
    Remove-Item -LiteralPath 'data\server.pid'
}
