param(
    [string]$InstallRoot = "C:\SLF\TrackTrace",
    [string]$ReleaseSource = ".",
    [switch]$InstallLocalUi
)

$ErrorActionPreference = "Stop"

$ReleaseSource = (Resolve-Path $ReleaseSource).Path
$Version = (Get-Content (Join-Path $ReleaseSource "VERSION") -TotalCount 1).Trim()
$ReleaseDir = Join-Path $InstallRoot "releases\$Version"
$CurrentDir = Join-Path $InstallRoot "current"
$ReleaseEnv = Join-Path $ReleaseDir ".env"
$PreviousEnv = Join-Path $CurrentDir ".env"

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

if (Test-Path $ReleaseEnv) {
    Write-Host "Preserved existing $ReleaseEnv."
}
elseif (Test-Path $PreviousEnv) {
    Copy-Item -Force $PreviousEnv $ReleaseEnv
    Write-Host "Copied existing station configuration from $PreviousEnv to $ReleaseEnv."
}
else {
    Copy-Item (Join-Path $ReleaseDir "deploy\templates\panel.env.example") $ReleaseEnv
    Write-Host "Created $ReleaseDir\.env. Edit SERVER_URL, DATABASE_*, and STATION_ID before starting."
}

if (Test-Path $CurrentDir) {
    Remove-Item -Force $CurrentDir
}
New-Item -ItemType Junction -Path $CurrentDir -Target $ReleaseDir | Out-Null

$Companion = Join-Path $CurrentDir "env\Scripts\slf-trace-companion.exe"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

if ($InstallLocalUi) {
    $Ui = Join-Path $CurrentDir "env\Scripts\slf-trace-ui.exe"
    Register-ScheduledTask `
        -TaskName "SLF Track Trace UI" `
        -Action (New-ScheduledTaskAction -Execute $Ui -WorkingDirectory $CurrentDir) `
        -Trigger $Trigger `
        -Principal $Principal `
        -Force | Out-Null
}
else {
    Unregister-ScheduledTask -TaskName "SLF Track Trace UI" -Confirm:$false -ErrorAction SilentlyContinue
}

Register-ScheduledTask `
    -TaskName "SLF Track Trace Companion" `
    -Action (New-ScheduledTaskAction -Execute $Companion -WorkingDirectory $CurrentDir) `
    -Trigger $Trigger `
    -Principal $Principal `
    -Force | Out-Null

Write-Host "Installed SLF Track and Trace panel release $Version at $CurrentDir"
Write-Host "Edit .env if needed, then start the companion task from Task Scheduler or reboot."
if ($InstallLocalUi) {
    Write-Host "Local UI task installed for diagnostics. Production stations should normally omit -InstallLocalUi."
}
else {
    Write-Host "Local UI task is not installed. Production station should open the central server UI in the browser."
}
