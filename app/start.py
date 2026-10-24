#!/usr/bin/env python3
"""复习管理系统一键启动器（Windows / macOS / Linux 通用）。

普通用户请双击入口文件，无需输入命令：Windows 双击「启动服务.bat」，
macOS / Linux 双击「启动服务.sh」。命令行高级用法见参数说明或 --help。
首次运行自动完成：检查 Python（需 3.11+）→ 建虚拟环境 → 装依赖 →
按需构建前端（无 Node 时给出指引）→ 打开浏览器 → 启动服务。
详细引导与常见问题见同目录《启动说明.md》。
"""
import argparse, json, os, shutil, socket, subprocess, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
BACKEND = APP_ROOT / "backend"
FRONTEND = APP_ROOT / "frontend"
DIST = FRONTEND / "dist"
MIN_PY = (3, 11)


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError:
        log(f"      未找到命令：{cmd[0]}")
        return 127


def find_python():
    """按优先级找到第一个版本 >= MIN_PY 的解释器；找不到返回 None。"""
    seen = set()
    for exe in [sys.executable] + [shutil.which(n) for n in ("py", "python3", "python")]:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        cmd = [exe, "-3", "--version"] if os.path.basename(exe).lower() in ("py", "py.exe") else [exe, "--version"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.split()
            if len(out) >= 2 and out[0] == "Python" and tuple(int(n) for n in out[1].split(".")[:2]) >= MIN_PY:
                return exe
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return None


def ensure_venv(py):
    venv_dir = BACKEND / ".venv"
    exe = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    if exe.exists():
        log("[2/4] 虚拟环境已就绪，跳过创建")
        return exe
    log("[2/4] 首次运行，正在创建虚拟环境（约 1 分钟）...")
    if run([py, "-m", "venv", str(venv_dir)]) != 0 or not exe.exists():
        sys.exit("虚拟环境创建失败：请确认 Python 安装完整（含 venv 模块）后重试，详见《启动说明.md》第六节。")
    return exe


def install_deps(venv_exe):
    req = BACKEND / "requirements.txt"
    log("[3/4] 正在安装后端依赖（首次约 1 至 3 分钟）...")
    cmd = [str(venv_exe), "-m", "pip", "install", "-r", str(req), "--quiet"]
    if run(cmd) != 0:
        log("      安装失败，尝试升级 pip 后重试一次...")
        subprocess.run([str(venv_exe), "-m", "pip", "install", "--upgrade", "pip"], capture_output=True)
        if run(cmd) != 0:
            sys.exit("依赖安装失败。常见原因：\n"
                     "      1. 网络不通：检查网络连通性后重新双击启动；\n"
                     "      2. 报错含 Microsoft Visual C++ 或 Failed building wheel："
                     "当前 Python 版本过新，缺少现成安装包，需要本地编译；\n"
                     "         建议改装 Python 3.12 或 3.13，删除 app/backend/.venv 后重新双击启动。\n"
                     "      详见《启动说明.md》第六节。")


def build_index(venv_exe):
    """启动前增量构建文档索引。按内容哈希判断，未改动的文件会跳过，通常不到 1 秒。"""
    log("      正在构建文档索引（题库 / 疑难点 / 知识点梳理 / 节点安排）...")
    cmd = [str(venv_exe), "-m", "app.indexer"]
    if run(cmd, cwd=BACKEND) != 0:
        log("      索引构建失败：不影响启动；可进入 backend 目录执行 python -m app.indexer 重试。")


def newest_mtime(root):
    latest = 0.0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for name in files:
            try:
                latest = max(latest, (Path(dirpath) / name).stat().st_mtime)
            except OSError:
                continue
    return latest


def build_frontend():
    """按需构建前端。有意降级：无 Node 或构建失败时不阻断启动，服务以接口形态继续运行，
    窗口会明确告知网页界面不可用及补救办法（见《启动说明.md》第六节）。"""
    if not DIST.is_dir():
        reason = "dist 不存在（首次运行或全新克隆）"
    elif (FRONTEND / "src").is_dir() and newest_mtime(FRONTEND / "src") > newest_mtime(DIST):
        reason = "检测到前端源码有更新"
    else:
        log("[4/4] 前端已是最新构建，跳过")
        return
    npm = shutil.which("npm")
    if not npm:
        log(f"[4/4] 跳过前端构建（{reason}）：未检测到 Node.js，网页界面不可用（接口仍可访问）。")
        log("      补救：到 https://nodejs.org/ 安装 Node.js LTS，装好后重新双击启动。")
        return
    log(f"[4/4] 正在构建前端（{reason}，首次约 1 至 3 分钟）...")
    if not (FRONTEND / "node_modules").is_dir() and run([npm, "install"], cwd=FRONTEND) != 0:
        log("      npm install 失败：请检查网络后重试；网页界面暂不可用。")
        return
    if run([npm, "run", "build"], cwd=FRONTEND) != 0:
        log("      前端构建失败：请阅读上方报错；网页界面暂不可用，接口仍可访问。")
        return
    log("      前端构建完成")


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def open_browser_when_ready(page, health):
    """后台轮询探活地址，服务就绪后自动打开浏览器。"""

    def worker():
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health, timeout=3) as resp:
                    if resp.status == 200:
                        try:
                            webbrowser.open(page)
                        except Exception:
                            pass  # 打开浏览器失败不影响服务：地址已打印，可手动访问
                        return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=worker, daemon=True).start()


def ensure_config():
    cfg, example = APP_ROOT / "config.json", APP_ROOT / "config.example.json"
    if not cfg.exists() and example.exists():
        shutil.copyfile(example, cfg)
        log("      已生成 config.json（AI 判分等可选配置在其中修改）")
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        return int(data.get("server", {}).get("port", 8000))
    except (OSError, ValueError, AttributeError):
        return 8000


def main():
    parser = argparse.ArgumentParser(description="复习管理系统一键启动器")
    parser.add_argument("--port", type=int, default=0, help="服务端口，默认取 config.json，未配置为 8000")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机访问")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过前端构建（仅接口）")
    args = parser.parse_args()
    port = args.port or ensure_config()
    page = f"http://{args.host}:{port}/"
    health = f"{page}api/health"
    log("复习管理系统 · 一键启动（启动过程请勿关闭窗口，停止服务请按 Ctrl+C）")
    py = find_python()
    if not py:
        sys.exit(f"[1/4] 未找到 Python {MIN_PY[0]}.{MIN_PY[1]} 或更高版本。\n"
                 f"      请到 https://www.python.org/downloads/ 下载安装；"
                 f"Windows 安装时务必勾选 Add python.exe to PATH。\n"
                 f"      详细步骤见《启动说明.md》第三节。")
    log(f"[1/4] 使用 Python：{py}")
    venv_exe = ensure_venv(py)
    install_deps(venv_exe)
    build_index(venv_exe)
    if args.skip_frontend:
        log("[4/4] 已按参数跳过前端构建")
    else:
        build_frontend()
    if port_in_use(port):
        sys.exit(f"端口 {port} 已被占用：请关闭占用该端口的程序，或改用其他端口"
                 f"（python start.py --port 8001）。详见《启动说明.md》第六节。")
    if not args.no_browser:
        open_browser_when_ready(page, health)
    log(f"服务地址：{page}（停止服务请按 Ctrl+C）")
    cmd = [str(venv_exe), "-m", "uvicorn", "app.main:app",
           "--app-dir", str(BACKEND), "--host", args.host, "--port", str(port)]
    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        sys.exit(f"服务启动失败：{exc}")
    try:
        proc.wait()
    except KeyboardInterrupt:
        log("\n正在停止服务...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log("服务已停止。")


if __name__ == "__main__":
    main()
