param(
    [int]$Port=7878,
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
. (Join-Path $studioRoot 'Studio-Process.ps1')
$studioEnvironment=Get-StudioProcessEnvironmentSnapshot @('PYTHONUTF8','MVC_DATA_DIR','OVC_DATABASE_URL')
try{
    $env:PYTHONUTF8='1'
    $env:MVC_DATA_DIR=Resolve-StudioDataDirectory $studioRoot
    $studioIdentity=Get-StudioIdentity $studioPython $studioRoot $env:MVC_DATA_DIR
    $studioData=[string]$studioIdentity.data_dir
    $studioLogs=Join-Path $studioData 'logs'
    New-Item -ItemType Directory -Path $studioLogs -Force | Out-Null
    $studioUrl="http://127.0.0.1:$Port"
    if(-not $WorkerOnly -and -not (Test-Path -LiteralPath (Join-Path $studioRoot 'dist\index.html'))){
        throw 'Run Install-Studio.ps1 first to build the web interface.'
    }

    $webCreated=$false
    $webReady=$false
    if(-not $WorkerOnly){
        $existingHealth=$null
        try{$existingHealth=Invoke-RestMethod "$studioUrl/api/health" -TimeoutSec 2}catch{}
        if($null -ne $existingHealth){
            if($existingHealth.instance_id -ne $studioIdentity.instance_id){
                throw "Port $Port is occupied by a different studio instance. Stop that instance or choose another port."
            }
            $webResolution=Resolve-StudioProcessRecord $studioIdentity 'web' 'backend.app:app'
            if($webResolution.State -ne 'owned'){
                Remove-StudioRecordIfNotOwned $webResolution
                throw 'A matching Web responded, but its local process lifecycle cannot be proven. It was not reused or stopped.'
            }
            Write-Host "Web is already running: $studioUrl (PID $($webResolution.Record.pid))"
            $webReady=$true
        }else{
            $webResolution=Resolve-StudioProcessRecord $studioIdentity 'web' 'backend.app:app'
            if($webResolution.State -eq 'owned'){
                throw "Recorded Web PID $($webResolution.Record.pid) is running but its health endpoint is unavailable. It was not replaced."
            }
            Remove-StudioRecordIfNotOwned $webResolution
            $serverOut=Join-Path $studioLogs 'server.stdout.log'
            $serverErr=Join-Path $studioLogs 'server.stderr.log'
            Remove-Item -LiteralPath $serverOut,$serverErr -Force -ErrorAction SilentlyContinue
            $studioProcess=Start-Process -FilePath $studioPython -ArgumentList '-m','uvicorn','backend.app:app','--host',$BindAddress,'--port',"$Port" -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr -PassThru
            try{
                Write-StudioProcessRecord $studioIdentity 'web' $studioProcess.Id 'backend.app:app' | Out-Null
                $webCreated=$true
                for($studioAttempt=0;$studioAttempt -lt 30;$studioAttempt++){
                    Start-Sleep -Milliseconds 250
                    if($studioProcess.HasExited){throw 'Web exited. Check the isolated data logs/server.stderr.log.'}
                    try{$studioHealth=Invoke-RestMethod "$studioUrl/api/health" -TimeoutSec 2}catch{$studioHealth=$null}
                    if($null -ne $studioHealth){
                        if($studioHealth.instance_id -ne $studioIdentity.instance_id){
                            throw "Port $Port answered for a different studio instance."
                        }
                        if($studioHealth.status -eq 'ok'){$webReady=$true;break}
                    }
                }
                if(-not $webReady){throw 'Web did not become ready. Check the isolated data logs.'}
                Write-Host "Web: $studioUrl (PID $($studioProcess.Id), instance $($studioIdentity.instance_id))"
            }catch{
                if($webCreated){Stop-OwnedStudioProcess $studioIdentity 'web' 'backend.app:app' | Out-Null}
                elseif($null -ne $studioProcess -and -not $studioProcess.HasExited){Stop-Process -Id $studioProcess.Id}
                throw
            }
        }
    }

    try{
        if(-not $WebOnly){
            $workerResolution=Resolve-StudioProcessRecord $studioIdentity 'worker' 'backend.worker_cli'
            if($workerResolution.State -eq 'owned'){
                Write-Host "Worker is already running: PID $($workerResolution.Record.pid)"
            }else{
                Remove-StudioRecordIfNotOwned $workerResolution
                $workerOut=Join-Path $studioLogs 'worker.stdout.log'
                $workerErr=Join-Path $studioLogs 'worker.stderr.log'
                Remove-Item -LiteralPath $workerOut,$workerErr -Force -ErrorAction SilentlyContinue
                $workerProcess=Start-Process -FilePath $studioPython -ArgumentList '-m','backend.worker_cli','--concurrency',"$WorkerConcurrency" -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr -PassThru
                $workerRecorded=$false
                try{
                    Write-StudioProcessRecord $studioIdentity 'worker' $workerProcess.Id 'backend.worker_cli' | Out-Null
                    $workerRecorded=$true
                    $workerReady=$false
                    for($workerAttempt=0;$workerAttempt -lt 50;$workerAttempt++){
                        Start-Sleep -Milliseconds 100
                        if($workerProcess.HasExited){
                            $details=if(Test-Path -LiteralPath $workerErr){Get-Content -LiteralPath $workerErr -Raw}else{''}
                            throw "Worker exited: $details"
                        }
                        if((Test-Path -LiteralPath $workerOut) -and (Get-Content -LiteralPath $workerOut -Raw) -match 'Worker started:'){
                            $workerReady=$true;break
                        }
                    }
                    if(-not $workerReady){throw 'Worker did not report ready within five seconds.'}
                    Write-Host "Worker: PID $($workerProcess.Id), instance $($studioIdentity.instance_id)"
                }catch{
                    if($workerRecorded){Stop-OwnedStudioProcess $studioIdentity 'worker' 'backend.worker_cli' | Out-Null}
                    elseif(-not $workerProcess.HasExited){Stop-Process -Id $workerProcess.Id}
                    throw
                }
            }
        }
    }catch{
        if($webCreated){Stop-OwnedStudioProcess $studioIdentity 'web' 'backend.app:app' | Out-Null}
        throw
    }

    if(-not $WorkerOnly){
        if(-not $NoBrowser){Start-Process $studioUrl}
        Write-Host 'Web and Worker have separate lifecycle records. Other computers use this host LAN IP and port.'
    }
}finally{
    Restore-StudioProcessEnvironment $studioEnvironment
}
