#!/usr/bin/env bash
set -euo pipefail

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name PulsePlayer main.py

echo "Linux build complete: dist/PulsePlayer/"
