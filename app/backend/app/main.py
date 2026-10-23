"""FastAPI 入口：/api/health 探活 + 前端 dist 静态托管（构建后存在时）。

开发期前端走 Vite dev server（5173）并经 proxy 转发 /api 到本服务，
故 dist 缺失不影响开发联调；生产形态由本服务单进程托管前后端。
"""

from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import APP_ROOT, load_config
from .db import connect, init_db
from .quiz import router as quiz_router
from .feedback import router as feedback_router

DIST_DIR = APP_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    load_config()  # 配置损坏时记录 warning 并使服务以降级形态启动
    init_db()

    app = FastAPI(title="复习管理系统", version=__version__)
    app.include_router(quiz_router)
    app.include_router(feedback_router)

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

    return app


app = create_app()
