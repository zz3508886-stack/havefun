"""P9 试点测试：过程数据导出器（SQLite 为源，markdown 为导出视图）。

覆盖：
- export_plan_status：节点状态列按 plan_checkins 推导重写、幂等、
  覆盖外部手改（DB 为源语义）、空库不动、过检阻断；
- collect_wrongbook / export_wrongbook：错题记录/按科目统计/高频错因 TOP
  三表渲染、复盘次数与攻克态、错因来源（反馈优先）、空库不动、幂等；
- HTTP 钩子：打卡 / 交卷 / 复盘登记触发导出，失败降级不丢流水。

所有写文件/写库均落在样例仓库(tmp)与临时 DB，不污染真实语料与 data/quiz.db。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import connect
from app.exporter import (
    MASTERY_REVIEWS,
    collect_wrongbook,
    export_plan_status,
    export_wrongbook,
)
from app.plan import PLAN_REL
from app.writeback import PreCheckError

WB_REL = "错题本/README.md"
FP = "数学/一次函数/题库.md"


def _wb_path(repo: Path) -> Path:
    return repo / WB_REL


def _seed_attempt(
    file_path: str,
    qid: str,
    correct: bool,
    error_type: str | None = None,
    at: str = "2026-10-24 10:00:00",
) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO quiz_attempts "
            "(batch_id, file_path, qid, user_answer, is_correct, eval_type, "
            "eval_state, error_type, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("b1", file_path, qid, "x", int(correct), "auto", "done", error_type, at),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_feedback(file_path: str, qid: str, error_type: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO quiz_feedback (file_path, section_title, qid, error_type, confused) "
            "VALUES (?,?,?,?,0)",
            (file_path, "三、一次函数专项测验", qid, error_type),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_review(file_path: str, qid: str, ok: bool, note: str | None = None) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO wrongbook_reviews (file_path, qid, result, note) VALUES (?,?,?,?)",
            (file_path, qid, int(ok), note),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 节点状态列导出
# --------------------------------------------------------------------------- #
def test_export_plan_status_writes_derived_column(plan_repo: Path):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO plan_checkins (node_id, status, notes) VALUES (?,?,?)",
            ("N01", "🟨", "完成两科自测"),
        )
        conn.execute(
            "INSERT INTO plan_checkins (node_id, status, notes) VALUES (?,?,?)",
            ("N02", "✅", None),
        )
        conn.execute(
            "INSERT INTO plan_checkins (node_id, status, notes) VALUES (?,?,?)",
            ("N02", "🟨", "复盘修正"),
        )
        conn.commit()
    finally:
        conn.close()

    out = export_plan_status(plan_repo)
    assert out["status"] == "written" and out["updated"] == 2

    lines = (plan_repo / PLAN_REL).read_text(encoding="utf-8").splitlines()
    n1 = next(ln for ln in lines if ln.strip().startswith("| N01 |"))
    n2 = next(ln for ln in lines if ln.strip().startswith("| N02 |"))
    assert n1.rstrip().endswith("| 🟨 |")  # 明细落库即更新
    assert n2.rstrip().endswith("| 🟨 |")  # 最近一次打卡优先（允许复盘修正）
    # 目标行除末列外逐字未变；非节点内容不动
    assert n1.startswith("| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 |")
    assert "| 状态 | 🟨 整理中 |" in lines
    assert "| N01 | 摸底自测 | 摸底自测 |" in lines
    assert "| 高考/单招报名 | 2026-11 至 2026-12 | ⬜ | 流程见文档 |" in lines


def test_export_plan_status_idempotent(plan_repo: Path):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO plan_checkins (node_id, status) VALUES (?,?)", ("N01", "🟨")
        )
        conn.commit()
    finally:
        conn.close()

    assert export_plan_status(plan_repo)["status"] == "written"
    text1 = (plan_repo / PLAN_REL).read_text(encoding="utf-8")
    out2 = export_plan_status(plan_repo)
    assert out2["status"] == "unchanged"
    assert (plan_repo / PLAN_REL).read_text(encoding="utf-8") == text1


def test_export_plan_status_overwrites_hand_edit(plan_repo: Path):
    """外部手改状态列会被导出覆盖——过程数据以 DB 为源。"""
    path = plan_repo / PLAN_REL
    text = path.read_text(encoding="utf-8")
    hand = text.replace(
        "| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | ⬜ |",
        "| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | ✅ |",
    )
    assert hand != text
    path.write_text(hand, encoding="utf-8")

    out = export_plan_status(plan_repo)  # DB 无打卡 → 推导为 ⬜
    assert out["status"] == "written"
    n1 = next(
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("| N01 |")
    )
    assert n1.rstrip().endswith("| ⬜ |")


def test_export_plan_status_empty_db_noop(plan_repo: Path):
    before = (plan_repo / PLAN_REL).read_text(encoding="utf-8")
    out = export_plan_status(plan_repo)
    assert out["status"] == "unchanged"
    assert (plan_repo / PLAN_REL).read_text(encoding="utf-8") == before


def test_export_plan_status_precheck_blocks(plan_repo: Path, monkeypatch):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO plan_checkins (node_id, status) VALUES (?,?)", ("N01", "🟨")
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("app.exporter._precheck", lambda rel, text: ["[R14] 黑话"])
    before = (plan_repo / PLAN_REL).read_text(encoding="utf-8")
    with pytest.raises(PreCheckError):
        export_plan_status(plan_repo)
    assert (plan_repo / PLAN_REL).read_text(encoding="utf-8") == before
    assert not (plan_repo / "复习计划" / ".节点安排.md.tmp").exists()


def test_export_plan_status_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        export_plan_status(tmp_path)


# --------------------------------------------------------------------------- #
# 错题本数据汇总与导出
# --------------------------------------------------------------------------- #
def _seed_wrongbook_data() -> None:
    # SX-001：两次答错（10-24 首次），反馈错因=计算失误，3 次复盘做对 + 要点
    _seed_attempt(FP, "SX-001", False, at="2026-10-24 10:00:00")
    _seed_attempt(FP, "SX-001", False, at="2026-10-25 10:00:00")
    _seed_feedback(FP, "SX-001", "计算失误")
    for _ in range(3):
        _seed_review(FP, "SX-001", True)
    _seed_review(FP, "SX-001", True, note="先想定义再下笔")
    # SX-003：一次答错，无反馈无复盘；判分时写入的错因作兜底
    _seed_attempt(FP, "SX-003", False, error_type="审题偏差", at="2026-10-26 10:00:00")


def test_collect_wrongbook_aggregates(wrongbook_repo: Path):
    _seed_wrongbook_data()
    data = collect_wrongbook()
    items = {i["qid"]: i for i in data["items"]}
    assert set(items) == {"SX-001", "SX-003"}
    # 录入日期 = 首次答错日；反馈错因优先于判分错因
    sx1 = items["SX-001"]
    assert sx1["first_wrong_at"][:10] == "2026-10-24"
    assert sx1["wrong_times"] == 2
    assert sx1["error_type"] == "计算失误"
    assert sx1["review_correct"] == 4 and sx1["mastered"] is True
    assert sx1["note"] == "先想定义再下笔"
    assert sx1["subject"] == "数学"
    # 无反馈 → 兜底判分错因
    assert items["SX-003"]["error_type"] == "审题偏差"
    assert items["SX-003"]["mastered"] is False
    # 高频错因 TOP：按反馈次数降序
    assert data["error_top"] == [{"error_type": "计算失误", "count": 1}]


def test_export_wrongbook_renders_three_tables(wrongbook_repo: Path):
    _seed_wrongbook_data()
    out = export_wrongbook(wrongbook_repo)
    assert out["status"] == "written" and out["items"] == 2

    text = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    lines = text.splitlines()
    # 章节结构与使用说明原样保留
    assert lines[0] == "# 错题本"
    assert "## 使用说明" in text
    assert "## 一、错题记录" in text and "## 二、按科目统计" in text and "## 三、高频错因 TOP" in text
    assert "- 错因类型参考：概念不清 / 计算失误 / 思路错误 / 审题偏差 / 知识遗忘。" in text
    # 一、错题记录：按首次答错时间排序编号；错因/复盘/要点入列
    assert "| CT-001 | 数学 | 数学/一次函数/题库.md#SX-001 | 题干A： | 计算失误 | 先想定义再下笔 | 2026-10-24 | 4 | 🟢 已攻克 |" in text
    assert "| CT-002 | 数学 | 数学/一次函数/题库.md#SX-003 | 题干C： | 审题偏差 | 待填写 | 2026-10-26 | 0 | 🔴 未攻克 |" in text
    assert "| 编号 | 科目 | 题目来源 | 题目摘要 | 错因类型 | 正确思路 | 录入日期 | 复盘次数 | 状态 |" in text
    # 二、按科目统计：固定科目表 + 实数
    assert "| 数学 | 2 | 1 | 1 |" in text
    assert "| 语文 | 0 | 0 | 0 |" in text
    assert "| 护理学基础 | 0 | 0 | 0 |" in text
    # 三、高频错因 TOP
    assert "| 计算失误 | 1 | 待填写 |" in text
    assert "| 错因类型 | 出现次数 | 整改措施 |" in text


def test_export_wrongbook_mastery_needs_four_consecutive(wrongbook_repo: Path):
    """「四次均做对」按最近连续做对计：中途答错即中断。"""
    _seed_attempt(FP, "SX-001", False, at="2026-10-24 10:00:00")
    _seed_review(FP, "SX-001", True)
    _seed_review(FP, "SX-001", True)
    _seed_review(FP, "SX-001", True)
    _seed_review(FP, "SX-001", False)  # 中断
    export_wrongbook(wrongbook_repo)
    text = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    assert "| CT-001 | 数学 | 数学/一次函数/题库.md#SX-001 | 题干A： | 待填写 | 待填写 | 2026-10-24 | 3 | 🔴 未攻克 |" in text

    for _ in range(MASTERY_REVIEWS):
        _seed_review(FP, "SX-001", True)
    export_wrongbook(wrongbook_repo)
    text = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    assert "| CT-001 | 数学 | 数学/一次函数/题库.md#SX-001 | 题干A： | 待填写 | 待填写 | 2026-10-24 | 7 | 🟢 已攻克 |" in text


def test_export_wrongbook_empty_is_noop(wrongbook_repo: Path):
    before = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    out = export_wrongbook(wrongbook_repo)
    assert out["status"] == "unchanged" and out["reason"] == "no-data"
    assert _wb_path(wrongbook_repo).read_text(encoding="utf-8") == before


def test_export_wrongbook_idempotent(wrongbook_repo: Path):
    _seed_wrongbook_data()
    assert export_wrongbook(wrongbook_repo)["status"] == "written"
    text1 = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    assert export_wrongbook(wrongbook_repo)["status"] == "unchanged"
    assert _wb_path(wrongbook_repo).read_text(encoding="utf-8") == text1


def test_export_wrongbook_precheck_blocks(wrongbook_repo: Path, monkeypatch):
    _seed_attempt(FP, "SX-001", False)
    monkeypatch.setattr("app.exporter._precheck", lambda rel, text: ["[R17] 内联答案"])
    before = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    with pytest.raises(PreCheckError):
        export_wrongbook(wrongbook_repo)
    assert _wb_path(wrongbook_repo).read_text(encoding="utf-8") == before


def test_export_wrongbook_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        export_wrongbook(tmp_path)


# --------------------------------------------------------------------------- #
# HTTP 钩子：打卡 / 交卷 / 复盘登记
# --------------------------------------------------------------------------- #
def test_checkin_triggers_export(plan_client, plan_repo: Path):
    r = plan_client.post(
        "/api/plan/checkin", json={"node_id": "N01", "status": "🟨", "notes": "完成两科自测"}
    )
    assert r.status_code == 200
    assert r.json()["writeback"] == "written" and r.json()["warning"] is None
    text = (plan_repo / PLAN_REL).read_text(encoding="utf-8")
    assert "| N01 | 摸底与基线建立 | 2026-10-22 至 2026-10-25 | 准备 | 完成各科摸底自测 | 自测记录 | 🟨 |" in text
    nodes = {n["node_id"]: n for n in plan_client.get("/api/plan/nodes").json()}
    assert nodes["N01"]["derived_status"] == "🟨"
    assert nodes["N01"]["status"] == "🟨"  # 文档状态列 = 最近一次导出值


def test_checkin_export_failure_keeps_row(plan_client, plan_repo: Path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("磁盘炸了")

    monkeypatch.setattr("app.exporter.export_plan_status", _boom)
    r = plan_client.post("/api/plan/checkin", json={"node_id": "N01", "status": "✅"})
    assert r.status_code == 200
    assert r.json()["writeback"] == "export_failed"
    assert "磁盘炸了" in r.json()["warning"]
    # 打卡明细不因导出失败丢失
    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM plan_checkins").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_submit_triggers_wrongbook_export(wrongbook_client, wrongbook_repo: Path):
    r = wrongbook_client.post(
        "/api/quiz/submit",
        json={
            "file_path": FP,
            "section_title": "三、一次函数专项测验",
            "answers": {"SX-001": "B", "SX-003": "错误"},  # 均答错
        },
    )
    assert r.status_code == 200
    assert r.json()["wrongbook_export"] == "written"
    text = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    assert "| CT-001 | 数学 | 数学/一次函数/题库.md#SX-001 |" in text
    assert "🔴 未攻克" in text
    assert "| 数学 | 2 | 2 | 0 |" in text


def test_wrong_review_endpoint(wrongbook_client, wrongbook_repo: Path):
    _seed_attempt(FP, "SX-001", False)
    r = wrongbook_client.post(
        "/api/quiz/wrong/review",
        json={"file_path": FP, "qid": "SX-001", "result": True, "note": "先想定义再下笔"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["wrongbook_export"] == "written"

    conn = connect()
    try:
        row = conn.execute(
            "SELECT result, note FROM wrongbook_reviews WHERE id=?", (body["id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row["result"] == 1 and row["note"] == "先想定义再下笔"

    text = _wb_path(wrongbook_repo).read_text(encoding="utf-8")
    assert "| 2026-10-24 | 1 | 🔴 未攻克 |" in text  # 录入日期 + 复盘次数
    assert "先想定义再下笔" in text  # 要点进入「正确思路」列


def test_wrong_review_rejects_missing_fields(wrongbook_client):
    r = wrongbook_client.post(
        "/api/quiz/wrong/review", json={"file_path": FP, "qid": "SX-001"}
    )
    assert r.status_code == 422
