param(
    [string]$InstallRoot = "C:\SLF\TrackTrace",
    [string]$ReleaseSource = "."
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

Copy-Item -Force (Join-Path $ReleaseSource "alembic.ini") $ReleaseDir -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $ReleaseSource "migrations") $ReleaseDir -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $ReleaseSource "deploy") $ReleaseDir

if (-not (Test-Path (Join-Path $ReleaseDir ".env"))) {
    Copy-Item (Join-Path $ReleaseDir "deploy\templates\panel.env.example") (Join-Path $ReleaseDir ".env")
    Write-Host "Created $ReleaseDir\.env. Edit SERVER_URL, DATABASE_*, and STATION_ID before starting."
}

if (Test-Path $CurrentDir) {
    Remove-Item -Force $CurrentDir
}
New-Item -ItemType Junction -Path $CurrentDir -Target $ReleaseDir | Out-Null

$Ui = Join-Path $CurrentDir "env\Scripts\slf-trace-ui.exe"
$Companion = Join-Path $CurrentDir "env\Scripts\slf-trace-companion.exe"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask `
    -TaskName "SLF Track Trace UI" `
    -Action (New-ScheduledTaskAction -Execute $Ui -WorkingDirectory $CurrentDir) `
    -Trigger $Trigger `
    -Principal $Principal `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName "SLF Track Trace Companion" `
    -Action (New-ScheduledTaskAction -Execute $Companion -WorkingDirectory $CurrentDir) `
    -Trigger $Trigger `
    -Principal $Principal `
    -Force | Out-Null

Write-Host "Installed SLF Track and Trace panel release $Version at $CurrentDir"
Write-Host "Edit .env if needed, then start tasks from Task Scheduler or reboot."
