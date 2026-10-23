#!/usr/bin/env bash
# havefun 网页刷题（web/）一键启动：macOS / Linux 使用；Windows 请双击「启动服务.bat」
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[错误] 未找到 Python。请安装 Python 3.11 或更高版本：https://www.python.org/downloads/"
  exit 1
fi
echo "havefun 网页刷题正在启动：http://localhost:8000/"
( sleep 2; if command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8000/; elif command -v open >/dev/null 2>&1; then open http://localhost:8000/; fi ) >/dev/null 2>&1 &
exec "$PY" app.py
