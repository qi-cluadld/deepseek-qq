#!/usr/bin/env bash
# 在 macOS 上本地打包：dist/deepseek-qq-macos-<arch>.zip
# 用法：bash build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "找不到 python3。先装命令行工具：xcode-select --install"
    exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 版本太低（需要 3.10+），当前：$("$PY" -V 2>&1)"
    echo "去 https://www.python.org/downloads/macos/ 装一个新版，或 brew install python@3.12"
    exit 1
fi
echo "==> 使用 $(command -v "$PY")（$("$PY" -V 2>&1)）"

# Homebrew / 系统自带的 Python 不允许直接往全局环境装包（PEP 668），
# 统一在本地虚拟环境里构建，干净且可重复。
if [ ! -d .venv ]; then
    echo "==> 创建虚拟环境 .venv"
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 安装依赖"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller

echo "==> 清理旧产物"
rm -rf build dist deepseek-qq.spec build_* dist_*

echo "==> PyInstaller 打包"
python -m PyInstaller --noconfirm --clean --onefile \
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
echo "    解压后双击 start-mac.command 运行"
