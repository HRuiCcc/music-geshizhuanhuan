#!/usr/bin/env bash
# music-geshizhuanhuan 启动器（macOS/Linux）
# 网页版:  ./run.sh web             -> 自动打开 http://127.0.0.1:8686
# 命令行:  ./run.sh <文件或目录> [-o 输出目录] [--format mp3|flac|m4a|wav|ogg]
set -euo pipefail
cd "$(dirname "$0")"

# 首次运行自动创建虚拟环境并安装依赖
if [ ! -x .venv/bin/python ]; then
  echo "[music-geshizhuanhuan] 首次运行：创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

if [ "${1:-}" = "web" ]; then
  shift
  exec ./.venv/bin/python web/server.py "$@"
fi

exec ./.venv/bin/python unlocker.py "$@"
