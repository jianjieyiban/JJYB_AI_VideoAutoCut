#!/usr/bin/env bash
# JJYB AI SmartCut — Linux x86_64 Executa artifact build (WSL JJYB-AnnaBuild)
# Usage: wsl -d JJYB-AnnaBuild -- bash /mnt/f/Users/AI工具/JJYB_AI智剪/scripts/wsl_linux_build.sh
set -euo pipefail

SRC="/mnt/f/Users/AI工具/JJYB_AI智剪/executas/jjyb-ai-smartcut"
PY=/opt/jjybvenv/bin/python

# 1. Sync latest source into the WSL build workspace
rm -rf "$HOME/jjyb/backend"
cp -r "/mnt/f/Users/AI工具/JJYB_AI智剪/backend" "$HOME/jjyb/backend"
cp "$SRC/jjyb_plugin.py" "$SRC/jjyb_executa_linux.spec" "$HOME/jjyb/"

# 2. Localize spec ROOT to the WSL workspace copy
sed -i "s|ROOT = Path(__file__).resolve().parents\[2\]|ROOT = Path('$HOME/jjyb')|" \
    "$HOME/jjyb/jjyb_executa_linux.spec"
grep -n '^ROOT' "$HOME/jjyb/jjyb_executa_linux.spec"

# 3. Build with the pinned venv (Python 3.14 + PyInstaller 6.16)
cd "$HOME/jjyb"
"$PY" -m PyInstaller --noconfirm --clean \
    --workpath "$HOME/build/jjyb_linux" \
    --distpath "$HOME/jjyb/dist" \
    "$HOME/jjyb/jjyb_executa_linux.spec"

# 4. Post-copy Linux ffmpeg/ffprobe into _internal (parity with 1.0.2 artifact)
cp -r "$HOME/jjyb/ffmpeg" "$HOME/jjyb/dist/jjyb-ai-smartcut/_internal/ffmpeg"
ls -la "$HOME/jjyb/dist/jjyb-ai-smartcut/_internal/ffmpeg"

echo LINUX_BUILD_OK
