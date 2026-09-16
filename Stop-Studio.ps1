param([switch]$WebOnly,[switch]$WorkerOnly)
$ErrorActionPreference='Stop'
if($WebOnly -and $WorkerOnly){throw 'WebOnly and WorkerOnly cannot be used together.'}
$studioRoot=$PSScriptRoot
$studioPython=Join-Path $studioRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $studioPython)){ $studioPython=(Get-Command python).Source }
. (Join-Path $studioRoot 'Studio-Process.ps1')
$studioEnvironment=Get-StudioProcessEnvironmentSnapshot @('PYTHONUTF8','MVC_DATA_DIR')
try{
    $env:PYTHONUTF8='1'
    $env:MVC_DATA_DIR=Resolve-StudioDataDirectory $studioRoot
    $studioIdentity=Get-StudioIdentity $studioPython $studioRoot $env:MVC_DATA_DIR
    $failed=$false
    if(-not $WorkerOnly){
        if(-not (Stop-OwnedStudioProcess $studioIdentity 'web' 'backend.app:app')){$failed=$true}
    }
    if(-not $WebOnly){
        if(-not (Stop-OwnedStudioProcess $studioIdentity 'worker' 'backend.worker_cli')){$failed=$true}
    }
    if($failed){exit 2}
}finally{
    Restore-StudioProcessEnvironment $studioEnvironment
}
