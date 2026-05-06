param(
    [string]$Target = "windows-x64-panel",
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"

$Version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
$EnvName = "slf-trace-$Version-$Target"
$OutDir = "dist/offline/$Version/$Target"

Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $OutDir | Out-Null

python -m pip install --upgrade build conda-pack
python -m build --wheel

if (Get-Command micromamba -ErrorAction SilentlyContinue) {
    micromamba create -y -n $EnvName "python=$PythonVersion" pip
    micromamba run -n $EnvName python -m pip install --upgrade pip
    micromamba run -n $EnvName python -m pip install "dist/slf_trace-$Version-py3-none-any.whl[smb,serial]"
    micromamba run -n $EnvName python -c "import slf_trace; from slf_trace.api.main import app; from slf_trace.ui.main import build_admin_app; print(slf_trace.__version__, app.title, build_admin_app.__name__)"
}
elseif (Get-Command conda -ErrorAction SilentlyContinue) {
    conda create -y -n $EnvName "python=$PythonVersion" pip
    conda run -n $EnvName python -m pip install --upgrade pip
    conda run -n $EnvName python -m pip install "dist/slf_trace-$Version-py3-none-any.whl[smb,serial]"
    conda run -n $EnvName python -c "import slf_trace; from slf_trace.api.main import app; from slf_trace.ui.main import build_admin_app; print(slf_trace.__version__, app.title, build_admin_app.__name__)"
}
else {
    throw "micromamba or conda is required for packed env builds."
}

conda-pack -n $EnvName -o "$OutDir/env.zip" --force

Copy-Item alembic.ini "$OutDir/"
Copy-Item -Recurse migrations "$OutDir/"
New-Item -ItemType Directory -Force "$OutDir/deploy" "$OutDir/docs" | Out-Null
Copy-Item deploy/install-server.ps1 "$OutDir/deploy/"
Copy-Item deploy/install-panel.ps1 "$OutDir/deploy/"
Copy-Item -Recurse deploy/templates "$OutDir/deploy/"
Copy-Item docs/deployment.md "$OutDir/docs/"
if (Test-Path docs/security.md) {
    Copy-Item docs/security.md "$OutDir/docs/"
}
Set-Content -Path "$OutDir/VERSION" -Value $Version

Push-Location $OutDir
Get-FileHash env.zip, alembic.ini, VERSION -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash.ToLower())  $([System.IO.Path]::GetFileName($_.Path))" } |
    Set-Content SHA256SUMS
Pop-Location

Write-Host "Built $OutDir"
