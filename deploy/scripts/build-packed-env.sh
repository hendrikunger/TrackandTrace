#!/usr/bin/env bash
set -euo pipefail

VERSION="${VERSION:-$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')}"
TARGET="${TARGET:-ubuntu24-x64-panel}"
ENV_NAME="${ENV_NAME:-slf-trace-${VERSION}-${TARGET}}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
OUT_DIR="${OUT_DIR:-dist/offline/${VERSION}/${TARGET}}"

rm -rf build dist/*.whl "$OUT_DIR"
mkdir -p "$OUT_DIR"

python -m pip install --upgrade build conda-pack
python -m build --wheel

if command -v micromamba >/dev/null 2>&1; then
  micromamba create -y -n "$ENV_NAME" "python=${PYTHON_VERSION}" pip
  eval "$(micromamba shell hook --shell bash)"
  micromamba activate "$ENV_NAME"
elif command -v mamba >/dev/null 2>&1; then
  mamba create -y -n "$ENV_NAME" "python=${PYTHON_VERSION}" pip
  eval "$(conda shell.bash hook)"
  conda activate "$ENV_NAME"
else
  echo "micromamba or mamba is required for packed env builds." >&2
  exit 1
fi

python -m pip install --upgrade pip
python -m pip install "dist/slf_trace-${VERSION}-py3-none-any.whl[smb,serial]"

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

conda-pack -n "$ENV_NAME" -o "$OUT_DIR/env.tar.gz" --force

cp alembic.ini "$OUT_DIR/"
cp -R migrations "$OUT_DIR/"
mkdir -p "$OUT_DIR/deploy" "$OUT_DIR/docs"
cp -R deploy/install-panel.sh deploy/templates deploy/systemd "$OUT_DIR/deploy/"
cp docs/deployment.md "$OUT_DIR/docs/"
printf '%s\n' "$VERSION" > "$OUT_DIR/VERSION"

(
  cd "$OUT_DIR"
  sha256sum env.tar.gz alembic.ini VERSION > SHA256SUMS
)

echo "Built $OUT_DIR"
