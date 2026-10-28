"""P4/P9 测试：节点解析、状态推导规则、节点安排.md 状态列导出、打卡 HTTP。

状态列自 P9 起为导出视图（过程数据以 SQLite 为源），导出的细粒度行为
（幂等/覆盖手改/过检阻断）在 test_exporter.py 覆盖；本文件聚焦解析、
推导与 HTTP 契约。涉及写文件/写库的测试均落在样例仓库(tmp)与临时 DB，
不污染真实语料与 data/quiz.db。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import connect
from app.plan import (
    PLAN_REL,
    derive_status,
    latest_checkins,
    parse_nodes,
)


def _plan_path(repo: Path) -> Path:
    return repo / PLAN_REL


# --------------------------------------------------------------------------- #
# 节点解析
# --------------------------------------------------------------------------- #
def test_parse_nodes_only_reads_node_table(plan_repo: Path):
    nodes = parse_nodes(_plan_path(plan_repo))
    assert [n["node_id"] for n in nodes] == ["N01", "N02"]
    assert all(n["status"] == "⬜" for n in nodes)
    n1 = nodes[0]
    assert n1["name"] == "摸底与基线建立" and n1["stage"] == "准备"
    # 第二节「科目侧重」表首列也是 N01，但列数不足 7，不得误判为节点行
    assert len(nodes) == 2


def test_parse_nodes_missing_file_raises(plan_repo: Path):
    _plan_path(plan_repo).unlink()
    with pytest.raises(FileNotFoundError):
        parse_nodes(_plan_path(plan_repo))


# --------------------------------------------------------------------------- #
# 状态推导规则（最近一次打卡为准，允许复盘修正）
# --------------------------------------------------------------------------- #
def test_derive_status_rule():
    assert derive_status(None) == "⬜"       # 无打卡 → 未开始
    assert derive_status("🟨") == "🟨"       # 进行中
    assert derive_status("✅") == "✅"       # 已完成
    assert derive_status("乱码") == "⬜"     # 脏数据回退未开始


def test_latest_checkins_latest_wins(plan_client):
    plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "✅"})
    plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "🟨"})
    plan_client.post("/api/plan/checkin", json={"node_id": "N02", "status": "✅"})
    latest = latest_checkins()
    # 复盘修正：最近一次 🟨 覆盖此前的 ✅
    assert latest == {"N01": "🟨", "N02": "✅"}


# --------------------------------------------------------------------------- #
# HTTP：打卡落库 + 状态列导出 + 推导
# --------------------------------------------------------------------------- #
def test_checkin_persists_and_writes_node_status(plan_client, plan_repo: Path):
    r = plan_client.post(
        "/api/plan/checkin", json={"node_id": "N01", "status": "🟨", "notes": "完成两科自测"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["writeback"] == "written" and body["ok"] is True

    # 明细落库
    conn = connect()
    try:
        row = conn.execute(
            "SELECT node_id, status, notes FROM plan_checkins WHERE id=?", (body["id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row["node_id"] == "N01" and row["status"] == "🟨" and row["notes"] == "完成两科自测"

    # 文档状态列已按明细导出（仅末列，其余列原样）
    text = _plan_path(plan_repo).read_text(encoding="utf-8")
    assert "| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | 🟨 |" in text

    # 节点清单：derived_status 反映最近一次打卡
    nodes = {n["node_id"]: n for n in plan_client.get("/api/plan/nodes").json()}
    assert nodes["N01"]["derived_status"] == "🟨"
    assert nodes["N01"]["checkin_count"] == 1
    assert nodes["N02"]["derived_status"] == "⬜"


def test_checkin_latest_wins_allows_reopen(plan_client, plan_repo: Path):
    plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "✅"})
    plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "🟨"})
    nodes = {n["node_id"]: n for n in plan_client.get("/api/plan/nodes").json()}
    # 复盘修正：最近一次 🟨 覆盖此前的 ✅（⬜→🟨→✅ 推进 + 可修正）
    assert nodes["N01"]["derived_status"] == "🟨"
    assert nodes["N01"]["checkin_count"] == 2
    text = _plan_path(plan_repo).read_text(encoding="utf-8")
    assert "| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | 🟨 |" in text


def test_checkin_export_failure_keeps_db_row(plan_client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("导出炸了")

    monkeypatch.setattr("app.exporter.export_plan_status", _boom)
    r = plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "✅"})
    assert r.status_code == 200
    assert r.json()["writeback"] == "export_failed"
    # 打卡不因导出失败丢失
    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM plan_checkins").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_checkin_rejects_invalid_input(plan_client):
    r1 = plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "完成"})
    assert r1.status_code == 422
    r2 = plan_client.post("/api/plan/checkin", json={"node_id": "节点一", "status": "🟨"})
    assert r2.status_code == 422
    # 非法输入不落库
    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM plan_checkins").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_list_checkins_recent_first(plan_client):
    plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "🟨"})
    plan_client.post("/api/plan/checkin", json={"node_id": "N02", "status": "🟨"})
    rows = plan_client.get("/api/plan/checkins").json()
    assert [r["node_id"] for r in rows] == ["N02", "N01"]
