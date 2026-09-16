Set-StrictMode -Version Latest

function Get-StudioProcessEnvironmentSnapshot([string[]]$Names){
    $snapshot=@{}
    foreach($name in $Names){
        $value=[Environment]::GetEnvironmentVariable($name,[EnvironmentVariableTarget]::Process)
        $snapshot[$name]=[pscustomobject]@{
            Defined=$null -ne $value
            Value=$value
        }
    }
    return $snapshot
}

function Restore-StudioProcessEnvironment($Snapshot){
    foreach($name in $Snapshot.Keys){
        $state=$Snapshot[$name]
        $value=if($state.Defined){[string]$state.Value}else{$null}
        [Environment]::SetEnvironmentVariable(
            [string]$name,
            $value,
            [EnvironmentVariableTarget]::Process
        )
    }
}

function Resolve-StudioDataDirectory([string]$Root){
    $targetRoot=[IO.Path]::GetFullPath($Root)
    $configured=[Environment]::GetEnvironmentVariable('MVC_DATA_DIR')
    if([string]::IsNullOrWhiteSpace($configured)){
        return [IO.Path]::GetFullPath((Join-Path $targetRoot 'data'))
    }
    if([IO.Path]::IsPathRooted($configured)){
        return [IO.Path]::GetFullPath($configured)
    }
    return [IO.Path]::GetFullPath((Join-Path $targetRoot $configured))
}

function Get-StudioIdentity([string]$Python,[string]$Root,[string]$DataDir){
    $targetRoot=[IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    $targetData=[IO.Path]::GetFullPath($DataDir).TrimEnd([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)
    Push-Location -LiteralPath $targetRoot
    try{$identityJson=& $Python -m backend.instance_identity 2>&1}
    finally{Pop-Location}
    if($LASTEXITCODE -ne 0){throw "Unable to determine studio identity: $identityJson"}
    $identity=$identityJson | ConvertFrom-Json
    if(-not $identity.instance_id -or -not $identity.project_root -or -not $identity.data_dir){
        throw 'Studio identity response is incomplete.'
    }
    if(-not [string]::Equals([string]$identity.project_root,$targetRoot,[StringComparison]::OrdinalIgnoreCase)){
        throw 'Studio identity project_root does not match the script project root.'
    }
    if(-not [string]::Equals([string]$identity.data_dir,$targetData,[StringComparison]::OrdinalIgnoreCase)){
        throw 'Studio identity data_dir does not match the normalized script data directory.'
    }
    return $identity
}

function Get-StudioRecordPath($Identity,[string]$Role){
    return Join-Path ([string]$Identity.data_dir) "$Role.process.json"
}

function Get-StudioProcess([int]$ProcessId){
    return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Get-StudioCreationUtc($ProcessInfo){
    return ([DateTime]$ProcessInfo.CreationDate).ToUniversalTime().ToString('o')
}

function Write-StudioProcessRecord($Identity,[string]$Role,[int]$ProcessId,[string]$ExpectedMarker){
    $processInfo=$null
    for($attempt=0;$attempt -lt 20 -and $null -eq $processInfo;$attempt++){
        $processInfo=Get-StudioProcess $ProcessId
        if($null -eq $processInfo){Start-Sleep -Milliseconds 50}
    }
    if($null -eq $processInfo){throw "$Role process $ProcessId disappeared before it could be recorded."}
    if($processInfo.CommandLine -notmatch [regex]::Escape($ExpectedMarker)){
        throw "$Role process command line does not contain the expected marker."
    }
    $record=[ordered]@{
        schema=1
        role=$Role
        pid=$ProcessId
        instance_id=[string]$Identity.instance_id
        project_root=[string]$Identity.project_root
        data_dir=[string]$Identity.data_dir
        creation_utc=Get-StudioCreationUtc $processInfo
        executable_path=[string]$processInfo.ExecutablePath
        command_line=[string]$processInfo.CommandLine
    }
    $path=Get-StudioRecordPath $Identity $Role
    $temporary="$path.$PID.tmp"
    $record | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $path -Force
    return $record
}

function Resolve-StudioProcessRecord($Identity,[string]$Role,[string]$ExpectedMarker){
    $path=Get-StudioRecordPath $Identity $Role
    if(-not (Test-Path -LiteralPath $path)){
        return [pscustomobject]@{State='missing';Reason='record not found';Path=$path;Process=$null;Record=$null}
    }
    try{$record=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json}
    catch{return [pscustomobject]@{State='invalid';Reason='record is not valid JSON';Path=$path;Process=$null;Record=$null}}
    $checks=@(
        @('schema',[string]$record.schema,'1'),
        @('role',[string]$record.role,$Role),
        @('instance_id',[string]$record.instance_id,[string]$Identity.instance_id),
        @('project_root',[string]$record.project_root,[string]$Identity.project_root),
        @('data_dir',[string]$record.data_dir,[string]$Identity.data_dir)
    )
    foreach($check in $checks){
        if(-not [string]::Equals($check[1],$check[2],[StringComparison]::OrdinalIgnoreCase)){
            return [pscustomobject]@{State='invalid';Reason="$($check[0]) does not belong to this studio instance";Path=$path;Process=$null;Record=$record}
        }
    }
    $savedPid=0
    if(-not [int]::TryParse([string]$record.pid,[ref]$savedPid) -or $savedPid -le 0){
        return [pscustomobject]@{State='invalid';Reason='PID is invalid';Path=$path;Process=$null;Record=$record}
    }
    $processInfo=Get-StudioProcess $savedPid
    if($null -eq $processInfo){
        return [pscustomobject]@{State='stale';Reason='recorded process is no longer running';Path=$path;Process=$null;Record=$record}
    }
    try{
        $recordCreation=if($record.creation_utc -is [DateTime]){
            ([DateTime]$record.creation_utc).ToUniversalTime()
        }else{
            [DateTime]::Parse(
                [string]$record.creation_utc,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            ).ToUniversalTime()
        }
    }catch{
        return [pscustomobject]@{State='invalid';Reason='creation time is invalid';Path=$path;Process=$processInfo;Record=$record}
    }
    $actualCreation=([DateTime]$processInfo.CreationDate).ToUniversalTime()
    if($actualCreation.Ticks -ne $recordCreation.Ticks){
        return [pscustomobject]@{State='invalid';Reason='PID creation time does not match the recorded lifecycle';Path=$path;Process=$processInfo;Record=$record}
    }
    if(-not [string]::Equals([string]$processInfo.ExecutablePath,[string]$record.executable_path,[StringComparison]::OrdinalIgnoreCase)){
        return [pscustomobject]@{State='invalid';Reason='executable path does not match the recorded process';Path=$path;Process=$processInfo;Record=$record}
    }
    if(-not [string]::Equals([string]$processInfo.CommandLine,[string]$record.command_line,[StringComparison]::Ordinal)){
        return [pscustomobject]@{State='invalid';Reason='command line does not match the recorded process';Path=$path;Process=$processInfo;Record=$record}
    }
    if($processInfo.CommandLine -notmatch [regex]::Escape($ExpectedMarker)){
        return [pscustomobject]@{State='invalid';Reason='command line lacks the expected role marker';Path=$path;Process=$processInfo;Record=$record}
    }
    return [pscustomobject]@{State='owned';Reason='';Path=$path;Process=$processInfo;Record=$record}
}

function Remove-StudioRecordIfNotOwned($Resolution){
    if($Resolution.State -in @('stale','invalid') -and (Test-Path -LiteralPath $Resolution.Path)){
        Remove-Item -LiteralPath $Resolution.Path -Force
    }
}

function Stop-OwnedStudioProcess($Identity,[string]$Role,[string]$ExpectedMarker){
    $resolution=Resolve-StudioProcessRecord $Identity $Role $ExpectedMarker
    if($resolution.State -eq 'missing'){
        Write-Host "$Role process record not found; nothing stopped."
        return $true
    }
    if($resolution.State -ne 'owned'){
        Write-Warning "$Role process was not stopped: $($resolution.Reason)."
        Remove-StudioRecordIfNotOwned $resolution
        return $false
    }
    Stop-Process -Id ([int]$resolution.Record.pid)
    for($attempt=0;$attempt -lt 50;$attempt++){
        if($null -eq (Get-StudioProcess ([int]$resolution.Record.pid))){break}
        Start-Sleep -Milliseconds 100
    }
    if($null -ne (Get-StudioProcess ([int]$resolution.Record.pid))){
        Write-Warning "$Role process did not stop within five seconds."
        return $false
    }
    Remove-Item -LiteralPath $resolution.Path -Force
    Write-Host "$Role stopped: PID $($resolution.Record.pid)"
    return $true
}
