param([switch]$WebOnly,[switch]$WorkerOnly)
$ErrorActionPreference='Stop'
if($WebOnly -and $WorkerOnly){throw 'WebOnly and WorkerOnly cannot be used together.'}
$studioRoot=$PSScriptRoot

function Stop-StudioProcess([string]$Name,[string]$PidFile,[string]$ExpectedCommand){
    if(-not (Test-Path -LiteralPath $PidFile)){
        Write-Host "$Name PID file not found; nothing stopped."
        return
    }
    $savedPid=[int](Get-Content -LiteralPath $PidFile -Raw)
    $process=Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
    if($null -ne $process -and $process.CommandLine -match $ExpectedCommand){
        Stop-Process -Id $savedPid
        Write-Host "$Name stopped: PID $savedPid"
    }elseif($null -ne $process){
        Write-Warning "$Name PID file is stale and now belongs to another process; that process was not stopped."
    }else{
        Write-Host "$Name PID $savedPid is not running."
    }
    Remove-Item -LiteralPath $PidFile -Force
}

if(-not $WorkerOnly){Stop-StudioProcess 'Web' (Join-Path $studioRoot 'data\server.pid') 'backend\.app:app'}
if(-not $WebOnly){Stop-StudioProcess 'Worker' (Join-Path $studioRoot 'data\worker.pid') 'backend\.worker_cli'}
