#!/usr/bin/env bash
set -euo pipefail

PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-$(command -v python || command -v python3)}"
VERSION="${VERSION:-$("$PYTHON_BOOTSTRAP" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')}"
TARGET="${TARGET:-ubuntu24-x64-panel}"
ENV_NAME="${ENV_NAME:-slf-trace-${VERSION}-${TARGET}}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
OUT_DIR="${OUT_DIR:-dist/offline/${VERSION}/${TARGET}}"
BOOTSTRAP_ENV="${BOOTSTRAP_ENV:-.build/packed-env-bootstrap}"

rm -rf build dist/*.whl "$OUT_DIR" "$BOOTSTRAP_ENV"
mkdir -p "$OUT_DIR"

"$PYTHON_BOOTSTRAP" -m venv "$BOOTSTRAP_ENV"
"$BOOTSTRAP_ENV/bin/python" -m pip install -q --upgrade pip build conda-pack
"$BOOTSTRAP_ENV/bin/python" -m build --wheel

if command -v micromamba >/dev/null 2>&1; then
  MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/.local/share/mamba}"
  export MAMBA_ROOT_PREFIX
  micromamba env remove -y -n "$ENV_NAME" >/dev/null 2>&1 || true
  micromamba create -y -q -n "$ENV_NAME" "python=${PYTHON_VERSION}" pip
  eval "$(micromamba shell hook --shell bash)"
  micromamba activate "$ENV_NAME"
  ENV_PREFIX="$MAMBA_ROOT_PREFIX/envs/$ENV_NAME"
elif command -v mamba >/dev/null 2>&1; then
  mamba env remove -y -n "$ENV_NAME" >/dev/null 2>&1 || true
  mamba create -y -q -n "$ENV_NAME" "python=${PYTHON_VERSION}" pip
  eval "$(conda shell.bash hook)"
  conda activate "$ENV_NAME"
  ENV_PREFIX="$CONDA_PREFIX"
else
  echo "micromamba or mamba is required for packed env builds." >&2
  exit 1
fi

python -m pip install -q "dist/slf_trace-${VERSION}-py3-none-any.whl[smb,serial,print]"

python - <<'PY'
import slf_trace
from slf_trace.api.main import app
from slf_trace.companion.runtime import CompanionRuntime
from slf_trace.ui.main import build_admin_app

print("slf-trace", slf_trace.__version__)
print("api", app.title)
print("companion", CompanionRuntime.__name__)
print("ui", build_admin_app.__name__)
PY

"$BOOTSTRAP_ENV/bin/conda-pack" -p "$ENV_PREFIX" -o "$OUT_DIR/env.tar.gz" --force

cp alembic.ini "$OUT_DIR/"
cp -R migrations "$OUT_DIR/"
find "$OUT_DIR/migrations" \( -name '._*' -o -name '.DS_Store' \) -type f -delete
mkdir -p "$OUT_DIR/deploy" "$OUT_DIR/docs"
cp -R deploy/install-panel.sh deploy/install-server.sh deploy/scripts deploy/templates deploy/systemd "$OUT_DIR/deploy/"
cp -R deploy/linux "$OUT_DIR/deploy/"
cp docs/deployment.md "$OUT_DIR/docs/"
cp docs/security.md "$OUT_DIR/docs/" 2>/dev/null || true
printf '%s\n' "$VERSION" > "$OUT_DIR/VERSION"

(
  cd "$OUT_DIR"
  sha256sum env.tar.gz alembic.ini VERSION > SHA256SUMS
)

echo "Built $OUT_DIR"
