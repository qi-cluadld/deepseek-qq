#!/usr/bin/env bash
# 在 macOS 上本地打包：dist/deepseek-qq-macos-<arch>.zip
# 用法：bash build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 检查依赖"
if ! python3 -c "import aiohttp, yaml, certifi" 2>/dev/null; then
    echo "    安装 requirements..."
    python3 -m pip install -r requirements.txt
fi
if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "    安装 PyInstaller..."
    python3 -m pip install pyinstaller
fi

echo "==> 清理旧产物"
rm -rf build dist deepseek-qq.spec build_*

echo "==> PyInstaller 打包"
python3 -m PyInstaller --noconfirm --clean --onefile \
    --name deepseek-qq \
    --add-data "config.example.yaml:." \
    --collect-data certifi \
    --collect-submodules app \
    --hidden-import aiohttp \
    --hidden-import yaml \
    --hidden-import certifi \
    main.py

echo "==> 组装压缩包"
cd dist
cp ../config.example.yaml .
cp ../start-mac.command .
chmod +x deepseek-qq start-mac.command
codesign --force --sign - deepseek-qq 2>/dev/null || echo "    跳过签名（不影响运行）"
ARCH="$(uname -m)"
zip -r "deepseek-qq-macos-${ARCH}.zip" deepseek-qq config.example.yaml start-mac.command

echo
echo "==> 完成：dist/deepseek-qq-macos-${ARCH}.zip"
echo "    双击 start-mac.command 即可运行"
