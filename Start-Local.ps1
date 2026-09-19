param([switch]$WebOnly,[switch]$WorkerOnly,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
if($WebOnly -and $WorkerOnly){throw 'WebOnly and WorkerOnly cannot be used together.'}
$localRuntime=Join-Path $env:LOCALAPPDATA 'OurVideoCreator-dev'
$localLauncher=Join-Path $localRuntime 'Start-Local.ps1'
if(-not (Test-Path -LiteralPath $localLauncher)){
    throw 'Existing local runtime configuration was not found. No database or credentials were created. See README.md for first-time setup.'
}
# Private settings stay outside Git. The runtime verifies this caller is the
# canonical project before loading credentials or starting any process.
if(-not $WorkerOnly){
    & $localLauncher -ExpectedProjectRoot $PSScriptRoot
}
if(-not $WebOnly){
    & $localLauncher -ExpectedProjectRoot $PSScriptRoot -WorkerOnly
}
if(-not $WorkerOnly -and -not $NoBrowser){Start-Process 'http://127.0.0.1:7878'}
