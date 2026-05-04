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

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "logs") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $InstallRoot "state") | Out-Null

if (Test-Path (Join-Path $ReleaseSource "env.zip")) {
    Expand-Archive -Force (Join-Path $ReleaseSource "env.zip") (Join-Path $ReleaseDir "env")
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

if (-not (Test-Path (Join-Path $ReleaseDir ".env"))) {
    Copy-Item (Join-Path $ReleaseDir "deploy\templates\server.env.example") (Join-Path $ReleaseDir ".env")
    Write-Host "Created $ReleaseDir\.env. Edit it before starting services."
}

if (Test-Path $CurrentDir) {
    Remove-Item -Force $CurrentDir
}
New-Item -ItemType Junction -Path $CurrentDir -Target $ReleaseDir | Out-Null

$Python = Join-Path $CurrentDir "env\python.exe"
$Api = Join-Path $CurrentDir "env\Scripts\slf-trace-api.exe"
$Ui = Join-Path $CurrentDir "env\Scripts\slf-trace-ui.exe"
$Alembic = Join-Path $CurrentDir "env\Scripts\alembic.exe"

Push-Location $CurrentDir
& $Alembic -c alembic.ini upgrade head
Pop-Location

$ApiAction = New-ScheduledTaskAction -Execute $Api -WorkingDirectory $CurrentDir
$ApiTrigger = New-ScheduledTaskTrigger -AtStartup
$ApiPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
Register-ScheduledTask `
    -TaskName "SLF Track Trace API" `
    -Action $ApiAction `
    -Trigger $ApiTrigger `
    -Principal $ApiPrincipal `
    -Force | Out-Null

if ($InstallAdminUi) {
    $UiAction = New-ScheduledTaskAction -Execute $Ui -WorkingDirectory $CurrentDir
    Register-ScheduledTask `
        -TaskName "SLF Track Trace UI" `
        -Action $UiAction `
        -Trigger $ApiTrigger `
        -Principal $ApiPrincipal `
        -Force | Out-Null
}

Write-Host "Installed SLF Track and Trace server release $Version at $CurrentDir"
Write-Host "Edit .env if needed, then start tasks from Task Scheduler or reboot."
