#!/usr/bin/env bash
# 复习管理系统（app/）一键启动：macOS / Linux 使用；Windows 请双击「启动服务.bat」
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[错误] 未找到 Python。请安装 Python 3.11 或更高版本：https://www.python.org/downloads/"
  echo "macOS 可用 brew install python@3.11；详细步骤见《启动说明.md》第三节。"
  exit 1
fi
exec "$PY" start.py "$@"
