#!/usr/bin/env bash
# music-unlock 启动器（macOS/Linux）
# 网页版:  ./run.sh web             -> 浏览器打开 http://127.0.0.1:8686
# 命令行:  ./run.sh <文件或目录> [-o 输出目录] [--format mp3|flac|m4a|wav|ogg]
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "web" ]; then
  shift
  exec ./.venv/bin/python web/server.py "$@"
fi

exec ./.venv/bin/python unlocker.py "$@"
