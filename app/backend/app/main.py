"""FastAPI 入口：/api/health 探活 + 前端 dist 静态托管（构建后存在时）。

开发期前端走 Vite dev server（5173）并经 proxy 转发 /api 到本服务，
故 dist 缺失不影响开发联调；生产形态由本服务单进程托管前后端。
"""

from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import APP_ROOT, load_config
from .db import connect, init_db
from .ai import router as ai_router
from .knowledge import router as knowledge_router
from .plan import router as plan_router
from .policy import router as policy_router
from .quiz import router as quiz_router
from .feedback import router as feedback_router
from .stats import router as stats_router

DIST_DIR = APP_ROOT / "frontend" / "dist"

NO_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>复习管理系统 · 网页界面未构建</title>
<style>
  body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#f4f6fb;font-family:"Microsoft YaHei",system-ui,sans-serif;color:#2b3245;}}
  .card{{max-width:560px;margin:24px;padding:32px 36px;background:#fff;border-radius:14px;
        box-shadow:0 8px 30px rgba(31,45,84,.10);}}
  h1{{font-size:20px;margin:0 0 8px;}}
  p{{line-height:1.7;margin:8px 0;font-size:14px;}}
  .badge{{display:inline-block;padding:2px 10px;border-radius:999px;background:#eef2ff;
         color:#4a5bd0;font-size:12px;margin-bottom:14px;}}
  ol{{line-height:1.9;font-size:14px;padding-left:22px;margin:12px 0;}}
  code{{background:#f1f3f8;border-radius:4px;padding:1px 6px;font-size:13px;}}
  .tip{{margin-top:18px;padding-top:14px;border-top:1px dashed #e3e7f2;font-size:13px;color:#6b7488;}}
</style>
</head>
<body>
<div class="card">
  <span class="badge">后端服务正常运行</span>
  <h1>网页界面尚未构建</h1>
  <p>后端接口服务已经正常启动（<code>/api/health</code> 可访问），但前端网页需要 Node.js 才能构建，
     当前系统未检测到 Node.js，因此浏览器打不开复习页面。</p>
  <p>解决办法（约 3 分钟）：</p>
  <ol>
    <li>到 <a href="https://nodejs.org/">https://nodejs.org/</a> 下载安装 <b>Node.js LTS 20 或 22</b>；</li>
    <li>装好后<b>关闭当前命令行窗口</b>；</li>
    <li>重新双击 <code>启动服务.bat</code>，窗口会自动构建前端并打开页面。</li>
  </ol>
  <div class="tip">
    急用时也可先用接口模式：命令行运行 <code>app/start.py --skip-frontend --no-browser</code>，
    后端接口（<code>/api/health</code> 等）立即可用；网页界面装好 Node 后再补构建。
  </div>
</div>
</body>
</html>"""


def create_app() -> FastAPI:
    load_config()  # 配置损坏时记录 warning 并使服务以降级形态启动
    init_db()

    app = FastAPI(title="复习管理系统", version=__version__)
    app.include_router(quiz_router)
    app.include_router(feedback_router)
    app.include_router(plan_router)
    app.include_router(stats_router)
    app.include_router(knowledge_router)
    app.include_router(policy_router)
    app.include_router(ai_router)

    @app.get("/api/health")
    def health() -> dict:
        db_ok = False
        try:
            conn = connect()
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                db_ok = True
            finally:
                conn.close()
        except sqlite3.Error:
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "db": "ok" if db_ok else "error",
            "frontend_dist": DIST_DIR.is_dir(),
        }

    # 显式路由先注册，静态挂载兜底——/api/* 永远优先生效
    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="frontend")
    else:
        # 未构建前端时给中文指引页，而不是裸的 {"detail":"Not Found"}
        @app.get("/{full_path:path}", include_in_schema=False)
        def no_frontend(full_path: str) -> HTMLResponse:
            return HTMLResponse(NO_FRONTEND_HTML)

    return app


app = create_app()
