#!/usr/bin/env bash
# scripts/build_macos.sh — one-dir + .app bundle for macOS
#
# Usage:
#   bash scripts/build_macos.sh
#
# Output:
#   dist/TrigonometrySprint/           (runnable binary + resources)
#   dist/TrigonometrySprint.app/       (when assets/icon.icns exists)
#
# Before building for distribution:
#   1. Edit src/server_config.py with the Lightsail URL so every built
#      copy auto-connects without the user setting TRIGSPRINT_SERVER_URL.
#   2. Drop assets/icon.icns for the .app bundle; assets/icon.png is the
#      fallback for the bare one-dir build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[build_macos] ensuring build deps..."
python -m pip install -r requirements-build.txt

echo "[build_macos] wiping previous build/dist..."
rm -rf build dist

echo "[build_macos] running pyinstaller..."
python -m PyInstaller TrigonometrySprint.spec --noconfirm

echo "[build_macos] done."
echo "  one-dir : dist/TrigonometrySprint/TrigonometrySprint"
if [ -d "dist/TrigonometrySprint.app" ]; then
  echo "  bundle  : dist/TrigonometrySprint.app"
fi
