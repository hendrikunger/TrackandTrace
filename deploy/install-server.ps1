param(
    [string]$InstallRoot = "C:\SLF\TrackTrace",
    [string]$ReleaseSource = ".",
    [switch]$InstallAdminUi
)

$ErrorActionPreference = "Stop"

$ReleaseSource = (Resolve-Path $ReleaseSource).Path
$Version = (Get-Content (Join-Path $ReleaseSource "VERSION") -TotalCount 1).Trim()
$ReleaseDir = Join-Path $InstallRoot "releases\$Version"
$CurrentDir = Join-Path $InstallRoot "current"
$ReleaseEnv = Join-Path $ReleaseDir ".env"
$PreviousEnv = Join-Path $CurrentDir ".env"
$CreatedTemplateEnv = $false

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "logs") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "state") | Out-Null

if (Test-Path (Join-Path $ReleaseSource "env.zip")) {
    Expand-Archive -Force (Join-Path $ReleaseSource "env.zip") (Join-Path $ReleaseDir "env")
    $CondaUnpack = Join-Path $ReleaseDir "env\Scripts\conda-unpack.exe"
    if (Test-Path $CondaUnpack) {
        & $CondaUnpack
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

if (Test-Path $CurrentDir) {
    Remove-Item -Force $CurrentDir
}
New-Item -ItemType Junction -Path $CurrentDir -Target $ReleaseDir | Out-Null

$Python = Join-Path $CurrentDir "env\python.exe"
$Alembic = Join-Path $CurrentDir "env\Scripts\alembic.exe"

if ($CreatedTemplateEnv) {
    Write-Host "Skipped database migration because this first install created a template .env."
    Write-Host "After editing $CurrentDir\.env, run:"
    Write-Host "  cd $CurrentDir"
    Write-Host "  .\env\Scripts\alembic.exe -c alembic.ini upgrade head"
}
else {
    Push-Location $CurrentDir
    & $Alembic -c alembic.ini upgrade head
    Pop-Location
}

$ApiAction = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument '-c "from slf_trace.api.main import run; run()"' `
    -WorkingDirectory $CurrentDir
$ApiTrigger = New-ScheduledTaskTrigger -AtStartup
$ApiPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask `
    -TaskName "SLF Track Trace API" `
    -Action $ApiAction `
    -Trigger $ApiTrigger `
    -Principal $ApiPrincipal `
    -Force | Out-Null

if ($InstallAdminUi) {
    $UiAction = New-ScheduledTaskAction `
        -Execute $Python `
        -Argument '-c "from slf_trace.ui.main import run; run()"' `
        -WorkingDirectory $CurrentDir
    Register-ScheduledTask `
        -TaskName "SLF Track Trace UI" `
        -Action $UiAction `
        -Trigger $ApiTrigger `
        -Principal $ApiPrincipal `
        -Force | Out-Null
}

Write-Host "Installed SLF Track and Trace server release $Version at $CurrentDir"
if ($CreatedTemplateEnv) {
    Write-Host "Edit .env and run the migration command above before starting tasks or rebooting."
}
else {
    Write-Host "Configuration preserved and migrations completed. Start tasks from Task Scheduler or reboot."
}
Write-Host "Rollback: stop tasks, point $CurrentDir to the previous release under $InstallRoot\releases, then restart tasks."
