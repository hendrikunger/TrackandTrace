param(
    [string]$Target = "windows-x64-panel",
    [string]$PythonVersion = "3.12",
    [string]$MambaExe = "",
    [string]$CondaExe = ""
)

$ErrorActionPreference = "Stop"

function Get-ProjectVersion {
    $InProject = $false
    foreach ($Line in Get-Content pyproject.toml) {
        if ($Line -match '^\[project\]') {
            $InProject = $true
            continue
        }
        if ($InProject -and $Line -match '^\[') {
            break
        }
        if ($InProject -and $Line -match '^version\s*=\s*"([^"]+)"') {
            return $Matches[1]
        }
    }
    throw "Could not read project.version from pyproject.toml."
}

function Resolve-Tool {
    param([string]$ExplicitPath, [string[]]$Names)

    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "Configured tool not found: $ExplicitPath"
        }
        return (Resolve-Path $ExplicitPath).Path
    }

    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }
    return $null
}

$Version = Get-ProjectVersion
$EnvName = "slf-trace-$Version-$Target"
$OutDir = "dist/offline/$Version/$Target"
$WheelPath = "dist/slf_trace-$Version-py3-none-any.whl"

Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Force dist/*.whl -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $OutDir | Out-Null

$Micromamba = Resolve-Tool -ExplicitPath $MambaExe -Names @("micromamba")
$Mamba = $null
$Conda = $null

if (-not $Micromamba) {
    $Mamba = Resolve-Tool -ExplicitPath $MambaExe -Names @("mamba")
}
if (-not $Micromamba -and -not $Mamba) {
    $Conda = Resolve-Tool -ExplicitPath $CondaExe -Names @("conda")
}

if ($Micromamba) {
    & $Micromamba env remove -y -n $EnvName 2>$null
    & $Micromamba create -y -n $EnvName "python=$PythonVersion" pip
    $RunnerExe = $Micromamba
    $RunnerArgs = @("run", "-n", $EnvName)
}
elseif ($Mamba) {
    & $Mamba env remove -y -n $EnvName 2>$null
    & $Mamba create -y -n $EnvName "python=$PythonVersion" pip
    $RunnerExe = $Mamba
    $RunnerArgs = @("run", "-n", $EnvName)
}
elseif ($Conda) {
    & $Conda env remove -y -n $EnvName 2>$null
    & $Conda create -y -n $EnvName "python=$PythonVersion" pip
    $RunnerExe = $Conda
    $RunnerArgs = @("run", "-n", $EnvName)
}
else {
    throw "micromamba, mamba, or conda is required for packed env builds. Pass -MambaExe or -CondaExe if it is not on PATH."
}

function Invoke-InPackedEnv {
    param([string[]]$CommandArgs)
    & $RunnerExe @RunnerArgs @CommandArgs
}

Invoke-InPackedEnv @("python", "-m", "pip", "install", "--upgrade", "pip", "build", "conda-pack")
Invoke-InPackedEnv @("python", "-m", "build", "--wheel")
Invoke-InPackedEnv @("python", "-m", "pip", "install", "$WheelPath[smb,serial]")
Invoke-InPackedEnv @("python", "-c", "import slf_trace; from slf_trace.api.main import app; from slf_trace.companion.runtime import CompanionRuntime; from slf_trace.ui.main import build_admin_app; print(slf_trace.__version__, app.title, CompanionRuntime.__name__, build_admin_app.__name__)")
Invoke-InPackedEnv @("python", "-m", "conda_pack.cli", "-n", $EnvName, "-o", "$OutDir/env.zip", "--force")

Copy-Item alembic.ini "$OutDir/"
Copy-Item -Recurse migrations "$OutDir/"
New-Item -ItemType Directory -Force -Path "$OutDir/deploy", "$OutDir/docs" | Out-Null
Copy-Item deploy/install-server.ps1 "$OutDir/deploy/"
Copy-Item deploy/install-server.sh "$OutDir/deploy/"
Copy-Item deploy/install-panel.ps1 "$OutDir/deploy/"
Copy-Item deploy/install-panel.sh "$OutDir/deploy/"
Copy-Item -Recurse deploy/linux "$OutDir/deploy/"
Copy-Item -Recurse deploy/scripts "$OutDir/deploy/"
Copy-Item -Recurse deploy/systemd "$OutDir/deploy/"
Copy-Item -Recurse deploy/templates "$OutDir/deploy/"
Copy-Item docs/deployment.md "$OutDir/docs/"
Copy-Item docs/security.md "$OutDir/docs/" -ErrorAction SilentlyContinue
Set-Content -Path "$OutDir/VERSION" -Value $Version
@"
# SLF Track and Trace $Version $Target

Built on: $([DateTimeOffset]::Now.ToString("o"))
Target: $Target
Python: $PythonVersion

Install:
- Windows server: deploy\install-server.ps1
- Windows panel: deploy\install-panel.ps1

Validate SHA256SUMS before install. Keep the previous release directory for rollback.
"@ | Set-Content -Path "$OutDir/RELEASE_NOTES.md"

Push-Location $OutDir
$ChecksumRoot = (Get-Location).Path
if (-not $ChecksumRoot.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $ChecksumRoot = "$ChecksumRoot$([System.IO.Path]::DirectorySeparatorChar)"
}
$ChecksumRootUri = [Uri]$ChecksumRoot
Get-ChildItem -Recurse -File |
    Where-Object { $_.Name -ne "SHA256SUMS" } |
    Sort-Object FullName |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object {
        $Relative = [Uri]::UnescapeDataString(
            $ChecksumRootUri.MakeRelativeUri([Uri]$_.Path).ToString()
        ).Replace("\", "/")
        "$($_.Hash.ToLower())  $Relative"
    } |
    Set-Content SHA256SUMS
Pop-Location

Write-Host "Built $OutDir"
