param(
    [string]$InstallRoot = "C:\SLF\TrackTrace",
    [string]$ReleaseSource = ".",
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"

$ReleaseSource = (Resolve-Path $ReleaseSource).Path
$Version = (Get-Content (Join-Path $ReleaseSource "VERSION") -TotalCount 1).Trim()
$ReleaseDir = Join-Path $InstallRoot "releases\$Version"
$CurrentDir = Join-Path $InstallRoot "current"
$ReleaseEnv = Join-Path $ReleaseDir ".env"
$PreviousEnv = Join-Path $CurrentDir ".env"
$CreatedTemplateEnv = $false

function Remove-CurrentPath {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $Item = Get-Item -LiteralPath $Path -Force
    if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        [System.IO.Directory]::Delete($Item.FullName, $false)
        return
    }

    Remove-Item -LiteralPath $Item.FullName -Recurse -Force -Confirm:$false
}

function Convert-EnvPathToInstallRoot {
    param(
        [string]$EnvPath,
        [string]$Name,
        [string]$InstallRoot
    )

    $Lines = Get-Content -LiteralPath $EnvPath
    $Changed = $false
    $Updated = foreach ($Line in $Lines) {
        if ($Line -notmatch "^$([regex]::Escape($Name))=(.*)$") {
            $Line
            continue
        }

        $Value = $Matches[1].Trim()
        if ($Value -eq "" -or [System.IO.Path]::IsPathRooted($Value)) {
            $Line
            continue
        }

        $Changed = $true
        "$Name=$((Join-Path $InstallRoot $Value))"
    }

    if ($Changed) {
        Set-Content -LiteralPath $EnvPath -Value $Updated -Encoding UTF8
    }
}

function Invoke-CheckedNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "logs") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "state") | Out-Null

if (Test-Path (Join-Path $ReleaseSource "env.zip")) {
    Expand-Archive -Force (Join-Path $ReleaseSource "env.zip") (Join-Path $ReleaseDir "env")
    $CondaUnpack = Join-Path $ReleaseDir "env\Scripts\conda-unpack.exe"
    if (Test-Path $CondaUnpack) {
        Invoke-CheckedNative -FilePath $CondaUnpack -Arguments @()
    }
}
elseif (Test-Path (Join-Path $ReleaseSource "env")) {
    Copy-Item -Recurse -Force (Join-Path $ReleaseSource "env") (Join-Path $ReleaseDir "env")
}
else {
    throw "Release source must contain env.zip or env directory."
}

Copy-Item -Force (Join-Path $ReleaseSource "alembic.ini") $ReleaseDir
Copy-Item -Recurse -Force (Join-Path $ReleaseSource "migrations") $ReleaseDir
Copy-Item -Recurse -Force (Join-Path $ReleaseSource "deploy") $ReleaseDir

if (Test-Path $ReleaseEnv) {
    Write-Host "Preserved existing $ReleaseEnv."
}
elseif (Test-Path $PreviousEnv) {
    Copy-Item -Force $PreviousEnv $ReleaseEnv
    Write-Host "Copied existing configuration from $PreviousEnv to $ReleaseEnv."
}
else {
    Copy-Item (Join-Path $ReleaseDir "deploy\templates\server.env.example") $ReleaseEnv
    $CreatedTemplateEnv = $true
    Write-Host "Created $ReleaseEnv from template. Edit it before running migrations or starting services."
}

Convert-EnvPathToInstallRoot -EnvPath $ReleaseEnv -Name "COMPANION_STATE_PATH" -InstallRoot $InstallRoot
Convert-EnvPathToInstallRoot -EnvPath $ReleaseEnv -Name "COMPANION_LOG_PATH" -InstallRoot $InstallRoot

Remove-CurrentPath $CurrentDir
New-Item -ItemType Junction -Path $CurrentDir -Target $ReleaseDir | Out-Null

$Python = Join-Path $CurrentDir "env\python.exe"
$Alembic = Join-Path $CurrentDir "env\Scripts\alembic.exe"
$ApiLog = Join-Path $InstallRoot "logs\slf-trace-api.log"
$UiLog = Join-Path $InstallRoot "logs\slf-trace-ui.log"
$ApiLauncher = Join-Path $CurrentDir "run-api-task.ps1"
$UiLauncher = Join-Path $CurrentDir "run-ui-task.ps1"

if ($CreatedTemplateEnv) {
    Write-Host "Skipped database migration because this first install created a template .env."
    Write-Host "After editing $CurrentDir\.env, run:"
    Write-Host "  cd $CurrentDir"
    Write-Host "  .\env\Scripts\alembic.exe -c alembic.ini upgrade head"
}
else {
    Push-Location $CurrentDir
    Invoke-CheckedNative -FilePath $Alembic -Arguments @("-c", "alembic.ini", "upgrade", "head")
    Pop-Location
}

$ApiLauncherContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath `$PSScriptRoot
& (Join-Path `$PSScriptRoot "env\python.exe") -c "from slf_trace.api.main import run; run()" *>> "$ApiLog"
exit `$LASTEXITCODE
"@
Set-Content -LiteralPath $ApiLauncher -Value $ApiLauncherContent -Encoding UTF8

$UiLauncherContent = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath `$PSScriptRoot
& (Join-Path `$PSScriptRoot "env\python.exe") -c "from slf_trace.ui.main import run; run()" *>> "$UiLog"
exit `$LASTEXITCODE
"@
Set-Content -LiteralPath $UiLauncher -Value $UiLauncherContent -Encoding UTF8

$ApiAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ApiLauncher`"" `
    -WorkingDirectory $CurrentDir
$ApiTrigger = New-ScheduledTaskTrigger -AtStartup
$ApiPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$TaskSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask `
    -TaskName "SLF Track Trace API" `
    -Action $ApiAction `
    -Trigger $ApiTrigger `
    -Principal $ApiPrincipal `
    -Settings $TaskSettings `
    -Force | Out-Null

if (-not $SkipUi) {
    $UiAction = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$UiLauncher`"" `
        -WorkingDirectory $CurrentDir
    Register-ScheduledTask `
        -TaskName "SLF Track Trace UI" `
        -Action $UiAction `
        -Trigger $ApiTrigger `
        -Principal $ApiPrincipal `
        -Settings $TaskSettings `
        -Force | Out-Null
}

Write-Host "Installed SLF Track and Trace server release $Version at $CurrentDir"
if ($CreatedTemplateEnv) {
    Write-Host "Edit .env and run the migration command above before starting tasks or rebooting."
}
else {
    Write-Host "Configuration preserved and migrations completed. Start tasks from Task Scheduler or reboot."
}
if ($SkipUi) {
    Write-Host "Central UI task was skipped because -SkipUi was set."
}
else {
    Write-Host "Central UI task is installed as 'SLF Track Trace UI'."
}
Write-Host "Rollback: stop tasks, point $CurrentDir to the previous release under $InstallRoot\releases, then restart tasks."
