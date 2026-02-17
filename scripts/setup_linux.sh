#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it first."
  exit 1
fi

echo "Installing Linux system dependencies (requires sudo)..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ffmpeg portaudio19-dev python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y ffmpeg portaudio-devel python3-venv python3-pip
elif command -v pacman >/dev/null 2>&1; then
  sudo pacman -Sy --noconfirm ffmpeg portaudio python python-pip
else
  echo "Unsupported package manager. Install ffmpeg + portaudio development headers manually."
fi

echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

echo "Linux setup complete."
echo "Run the app with: ./scripts/run.sh"
