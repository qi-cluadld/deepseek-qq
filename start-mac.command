#!/bin/bash
# 双击这个文件即可启动 DeepSeek QQ 机器人（macOS）
# 第一次运行如果提示“无法打开”，先看 README 里的“首次运行”说明

cd "$(dirname "$0")" || exit 1

chmod +x ./deepseek-qq 2>/dev/null

echo "==============================================="
echo "  DeepSeek QQ 机器人"
echo "  目录: $(pwd)"
echo "  按 Ctrl+C 停止"
echo "==============================================="
echo

./deepseek-qq "$@"

echo
echo "机器人已停止。按任意键关闭窗口…"
read -n 1 -s
