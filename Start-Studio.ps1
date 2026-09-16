param(
    [int]$Port=7868,
    [string]$BindAddress='0.0.0.0',
    [int]$WorkerConcurrency=4,
    [switch]$NoBrowser,
    [switch]$WebOnly,
    [switch]$WorkerOnly
)
$ErrorActionPreference='Stop'
if($WebOnly -and $WorkerOnly){throw 'WebOnly and WorkerOnly cannot be used together.'}
$studioRoot=$PSScriptRoot
$studioPython=Join-Path $studioRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $studioPython)){ $studioPython=(Get-Command python).Source }
$studioLogs=Join-Path $studioRoot 'data\logs'
New-Item -ItemType Directory -Path $studioLogs -Force | Out-Null
$studioUrl="http://127.0.0.1:$Port"
$env:PYTHONUTF8='1'
if(-not $WorkerOnly -and -not (Test-Path -LiteralPath (Join-Path $studioRoot 'dist\index.html'))){
    throw 'Run Install-Studio.ps1 first to build the web interface.'
}

if(-not $WebOnly){
    $workerPidPath=Join-Path $studioRoot 'data\worker.pid'
    $workerRunning=$false
    if(Test-Path -LiteralPath $workerPidPath){
        $savedWorkerPid=[int](Get-Content -LiteralPath $workerPidPath -Raw)
        $savedWorker=Get-CimInstance Win32_Process -Filter "ProcessId = $savedWorkerPid" -ErrorAction SilentlyContinue
        $workerRunning=$null -ne $savedWorker -and $savedWorker.CommandLine -match 'backend\.worker_cli'
    }
    if($workerRunning){
        Write-Host "Worker is already running: PID $savedWorkerPid"
    }else{
        $workerProcess=Start-Process -FilePath $studioPython -ArgumentList '-m','backend.worker_cli','--concurrency',"$WorkerConcurrency" -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioLogs 'worker.stdout.log') -RedirectStandardError (Join-Path $studioLogs 'worker.stderr.log') -PassThru
        $workerProcess.Id | Set-Content -LiteralPath $workerPidPath
        Start-Sleep -Milliseconds 500
        if($workerProcess.HasExited){throw 'Worker exited. Check data/logs/worker.stderr.log.'}
        Write-Host "Worker: PID $($workerProcess.Id)"
    }
}

if(-not $WorkerOnly){
    try {
        $studioHealth=Invoke-RestMethod "$studioUrl/api/health" -TimeoutSec 2
        if($studioHealth.app -eq '安影'){
            if(-not $NoBrowser){Start-Process $studioUrl}
            Write-Host "Web is already running: $studioUrl"
            exit 0
        }
    }catch{}
    $studioProcess=Start-Process -FilePath $studioPython -ArgumentList '-m','uvicorn','backend.app:app','--host',$BindAddress,'--port',"$Port" -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioLogs 'server.stdout.log') -RedirectStandardError (Join-Path $studioLogs 'server.stderr.log') -PassThru
    $studioProcess.Id | Set-Content -LiteralPath (Join-Path $studioRoot 'data\server.pid')
    for($studioAttempt=0;$studioAttempt -lt 30;$studioAttempt++){
        Start-Sleep -Seconds 1
        if($studioProcess.HasExited){throw 'Web exited. Check data/logs/server.stderr.log.'}
        try{
            $studioHealth=Invoke-RestMethod "$studioUrl/api/health" -TimeoutSec 2
            if($studioHealth.status -eq 'ok'){
                if(-not $NoBrowser){Start-Process $studioUrl}
                Write-Host "Web: $studioUrl (PID $($studioProcess.Id))"
                Write-Host 'Web and Worker are independent processes. Other computers use this host LAN IP and port.'
                exit 0
            }
        }catch{}
    }
    throw 'Web did not become ready. Check data/logs.'
}
