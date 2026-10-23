@echo off
chcp 65001 >nul
cd /d %~dp0
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY where python3 >nul 2>nul && set "PY=python3"
if not defined PY echo [错误] 未找到 Python。请安装 Python 3.11 或更高版本。
if not defined PY echo 下载地址：https://www.python.org/downloads/ ，安装时勾选 Add python.exe to PATH。
if not defined PY echo 详细步骤见《启动说明.md》第三节。
if not defined PY pause
if not defined PY exit /b 1
%PY% start.py %*
if errorlevel 1 echo 启动失败，请阅读上方错误信息；排查方法见《启动说明.md》第六节。
if errorlevel 1 pause
