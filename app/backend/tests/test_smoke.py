"""P0 冒烟：health 探活 + 四表 schema 落库 + WAL 模式。"""

from __future__ import annotations

import sqlite3

from app.db import connect


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["version"]


def test_schema_created(client, db_path):
    """client 夹具创建 app 时执行 init_db，落库到 db_path。"""
    conn = connect(db_path)
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "doc_files",
            "questions_index",
            "quiz_attempts",
            "plan_checkins",
        } <= names
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_connect_is_idempotent(db_path):
    """init 可重复执行（启动与测试共用）。"""
    from app.db import init_db

    init_db(db_path)
    init_db(db_path)


def test_health_db_error_reports_degraded(client, monkeypatch, db_path):
    """数据库不可用时 health 报 degraded 而非崩溃。"""

    def _raise(_path=None):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("app.main.connect", _raise)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "error"
    assert resp.json()["status"] == "degraded"
