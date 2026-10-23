"""P2 测验引擎测试：判分正确性、主客观状态机分流、答案键不下发、
原子回写冲突/过检降级、attempts 落库。

涉及写文件/写库的测试均落在样例仓库(tmp)与临时 DB，不污染真实语料与 data/quiz.db。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.db import connect
from app.grading import grade_set
from app.parser import Question
from app.writeback import WriteConflict, atomic_write_text


def _q(qid, q_type, answer_key="", stem=""):
    return Question(
        qid=qid, file_path="数学/一次函数/题库.md", section_title="一次函数专项测验",
        q_type=q_type, stem=stem, answer_key=answer_key,
    )


# --------------------------------------------------------------------------- #
# 判分正确性
# --------------------------------------------------------------------------- #
def test_grade_objective_choice_correct_and_wrong():
    qs = [_q("SX-001", "选择题", "A"), _q("SX-002", "选择题", "B")]
    g = grade_set(qs, {"SX-001": "a", "SX-002": "C"})
    by = {r.qid: r for r in g.results}
    assert by["SX-001"].is_correct is True
    assert by["SX-001"].key_answer == "A"
    assert by["SX-002"].is_correct is False
    assert by["SX-002"].error_type == "概念不清"
    assert g.summary["correct"] == 1 and g.summary["wrong"] == 1


def test_grade_judgment_true_false_normalization():
    qs = [_q("SX-003", "判断题", "正确"), _q("SX-004", "判断题", "错误")]
    g = grade_set(qs, {"SX-003": "对", "SX-004": "不对"})
    by = {r.qid: r for r in g.results}
    assert by["SX-003"].is_correct is True
    assert by["SX-004"].is_correct is True  # 答案键"错误" vs 学生"不对"→ 归一一致


def test_grade_unanswered_is_pending_manual():
    qs = [_q("SX-002", "填空题", "x")]
    g = grade_set(qs, {})
    r = g.results[0]
    assert r.is_correct is None
    assert r.eval_state == "pending_manual"
    assert r.error_type == "待复核"
    assert g.summary["pending"] == 1


def test_grade_subjective_ai_hit():
    def fake_ai(q, student, key):
        return {"correct": True, "错因类型": "思路错误", "错因说明": "基本对"}

    qs = [_q("SX-002", "填空题", "x")]
    g = grade_set(qs, {"SX-002": "x"}, ai_grader=fake_ai)
    r = g.results[0]
    assert r.is_correct is True
    assert r.eval_type == "ai"
    assert r.eval_state == "done"


def test_grade_subjective_ai_fail_degrades():
    def fake_ai(q, student, key):
        raise RuntimeError("endpoint down")

    qs = [_q("SX-002", "填空题", "x")]
    g = grade_set(qs, {"SX-002": "x"}, ai_grader=fake_ai)
    r = g.results[0]
    assert r.is_correct is None
    assert r.eval_state == "pending_manual"
    assert "AI 判分失败" in r.note


# --------------------------------------------------------------------------- #
# HTTP：取题不下发答案键 + 提交判分
# --------------------------------------------------------------------------- #
def test_list_sets_and_questions_have_no_answer_key(api_client):
    sets = api_client.get("/api/quiz/sets").json()
    assert len(sets) == 1
    s = sets[0]
    assert s["n_questions"] == 4
    assert s["has_key"] is True

    body = api_client.get(
        "/api/quiz/set",
        params={"file_path": s["file_path"], "section_title": s["section_title"]},
    ).json()
    assert len(body["questions"]) == 4
    for q in body["questions"]:
        assert "answer_key" not in q  # 答案键绝不随题目下发给前端
        assert "correct_answer" not in q


def test_submit_graded_and_attempts_persisted(api_client, quiz_repo, monkeypatch):
    # 确定性：跳过回写前校验器（避免校验规则演进误伤），单独测过检门
    monkeypatch.setattr("app.writeback._precheck", lambda rel, text: [])

    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "answers": {"SX-001": "A", "SX-003": "正确", "SX-002": "x", "SX-004": "y"},
    }
    resp = api_client.post("/api/quiz/submit", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["writeback"] == "written"

    by = {r["qid"]: r for r in data["results"]}
    assert by["SX-001"]["is_correct"] is True
    assert by["SX-001"]["correct_answer"] == "A"  # 客观题判分后回传正确答案
    assert by["SX-003"]["is_correct"] is True
    # 主观题：无 AI 端点 → 待复核，不下发 correct_answer
    assert by["SX-002"]["is_correct"] is None
    assert by["SX-002"]["eval_state"] == "pending_manual"
    assert "correct_answer" not in by["SX-002"]
    assert data["summary"]["correct"] == 2
    assert data["summary"]["pending"] == 2

    # attempts 落库：4 行，客观题已判、主观题待复核
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT qid, is_correct, eval_type, eval_state FROM quiz_attempts "
            "WHERE batch_id=? ORDER BY qid",
            (data["batch_id"],),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 4
    by_db = {r["qid"]: r for r in rows}
    assert by_db["SX-001"]["is_correct"] == 1 and by_db["SX-001"]["eval_type"] == "auto"
    assert by_db["SX-002"]["is_correct"] is None
    assert by_db["SX-002"]["eval_state"] == "pending_manual"

    # 回写落到样例仓库（非真实语料）
    text = (quiz_repo / "数学/一次函数/题库.md").read_text(encoding="utf-8")
    assert "### 订正反馈（三、一次函数专项测验）" in text
    assert "### 评估（三、一次函数专项测验）" in text


def test_route_handles_writeback_conflict(api_client, monkeypatch):
    def _boom(*a, **k):
        raise WriteConflict("文件已被外部修改")

    # 路由内按名导入 write_back，须打 app.quiz.write_back 才能拦截
    monkeypatch.setattr("app.quiz.write_back", _boom)
    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "answers": {"SX-001": "A"},
    }
    resp = api_client.post("/api/quiz/submit", json=payload)
    assert resp.status_code == 200
    assert resp.json()["writeback"] == "conflict"
    # 判分仍落库（整套 4 题各记一行），不因回写冲突丢失
    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM quiz_attempts").fetchone()[0]
    finally:
        conn.close()
    assert n == 4


def test_route_handles_precheck_failure(api_client, monkeypatch):
    monkeypatch.setattr("app.writeback._precheck", lambda rel, text: ["[R17] 内联答案"])
    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "answers": {"SX-001": "A"},
    }
    resp = api_client.post("/api/quiz/submit", json=payload)
    assert resp.status_code == 200
    assert resp.json()["writeback"] == "precheck_failed"


# --------------------------------------------------------------------------- #
# 原子回写：冲突检测 + 无半截文件
# --------------------------------------------------------------------------- #
def test_atomic_write_refuses_on_external_change(tmp_path: Path, monkeypatch):
    # 单元冲突检测：用 repo 内路径并绕过预检（避免非文档文本触发 R03 等）
    monkeypatch.setattr("app.writeback._precheck", lambda rel, text: [])
    p = tmp_path / "t.md"
    p.write_text("hello\n", encoding="utf-8")
    baseline = hashlib.sha256("hello\n".encode("utf-8")).hexdigest()

    # 基线一致 → 写入成功
    atomic_write_text(p, "world\n", baseline, repo_root=tmp_path)
    assert p.read_text(encoding="utf-8") == "world\n"

    # 外部修改文件，再用旧基线写入 → 拒绝且原内容不变
    p.write_text("external\n", encoding="utf-8")
    with pytest.raises(WriteConflict):
        atomic_write_text(p, "new\n", baseline, repo_root=tmp_path)
    assert p.read_text(encoding="utf-8") == "external\n"
    # 不留半截临时文件
    assert not (tmp_path / ".t.md.tmp").exists()


def test_precheck_gate_detects_inlined_answer():
    from app.writeback import _precheck

    # R17 命中要求「**答案**」紧邻双星号（与 check_docs 规则一致）
    issues = _precheck("数学/一次函数/题库.md", "题干\n**答案**\n")
    assert any("R17" in iss for iss in issues)
