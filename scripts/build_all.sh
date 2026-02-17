#!/usr/bin/env bash
set -euo pipefail

os="$(uname -s)"
case "$os" in
  Linux*)
    ./scripts/build_linux.sh
    ;;
  Darwin*)
    ./scripts/build_macos.sh
    ;;
  *)
    echo "Unsupported in this script. On Windows use build_windows.bat"
    exit 1
    ;;
esac

echo "Note: Native executables must be built on each target platform."
echo "Use Linux/macOS scripts on those OSes, and build_windows.bat on Windows."
