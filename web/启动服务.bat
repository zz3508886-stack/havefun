@echo off
chcp 65001 >nul
cd /d %~dp0
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY where python3 >nul 2>nul && set "PY=python3"
if not defined PY echo [错误] 未找到 Python。请安装 Python 3.11 或更高版本。
if not defined PY echo 下载地址：https://www.python.org/downloads/ ，安装时勾选 Add python.exe to PATH。
if not defined PY echo 详细步骤见 app/启动说明.md 第三节。
if not defined PY pause
if not defined PY exit /b 1
echo havefun 网页刷题正在启动：http://localhost:8000/
timeout /t 2 /nobreak >nul
start "" http://localhost:8000/
%PY% app.py
if errorlevel 1 echo 服务已停止（异常退出时可阅读上方信息）。
if errorlevel 1 pause
