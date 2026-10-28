"""摸底测验卷接入做题系统的测试（SET_RE 扩充 + 非标准题型判分 + 回写降级）。

覆盖：
- 「概念摸底（A卷）」章节被索引进 sets 列表（SET_RE 含「摸底」）；
- 解析文档裸题头（### HL-MP-001，无括号后缀）能提出答案键；
- 非标准题型名但有标准选项 + 单字母答案键 → 按客观题判分并回传正确答案；
- 摸底卷章节名不含标准套题关键词 → 交卷不回写（skipped），不 500、不留痕。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.parser import Question, is_objective_question, parse_answer_key

FP = "测验/摸底/护理学基础/题库.md"
SEC = "二、护理概念摸底（A卷）"


# --------------------------------------------------------------------------- #
# 索引与 sets 列表
# --------------------------------------------------------------------------- #
def test_mopq_set_indexed_and_listed(mopq_client):
    sets = mopq_client.get("/api/quiz/sets").json()
    hit = [s for s in sets if s["file_path"] == FP]
    assert len(hit) == 1
    assert hit[0]["section_title"] == SEC
    assert hit[0]["n_questions"] == 2
    assert hit[0]["has_key"] is True


def test_mopq_set_loadable_without_answer_key(mopq_client):
    """取题接口不下发答案键（契约不变）。"""
    body = mopq_client.get("/api/quiz/set", params={"file_path": FP, "section_title": SEC}).json()
    assert [q["qid"] for q in body["questions"]] == ["HL-MP-001", "HL-MP-002"]
    for q in body["questions"]:
        assert "answer_key" not in q
        assert len(q["options"]) == 4  # 选项随题干下发


# --------------------------------------------------------------------------- #
# 解析文档裸题头 → 答案键
# --------------------------------------------------------------------------- #
def test_parse_answer_key_bare_head(tmp_path: Path):
    p = tmp_path / "题库解析.md"
    p.write_text(
        "### HL-MP-001\n**答案：B**\n\n### SX-MP-001（选择题，【基础｜难度 2】）\n**答案：C**\n",
        encoding="utf-8",
    )
    assert parse_answer_key(p) == {"HL-MP-001": "B", "SX-MP-001": "C"}


# --------------------------------------------------------------------------- #
# 判分：非标准题型名的单选按客观题判
# --------------------------------------------------------------------------- #
def _q(q_type: str, options: list, answer_key: str) -> Question:
    return Question(
        qid="Q-001",
        file_path=FP,
        section_title=SEC,
        q_type=q_type,
        stem="题干",
        options=options,
        answer_key=answer_key,
    )


def test_is_objective_question_nonstandard_type_with_options():
    opts = [{"label": "A", "text": "a"}, {"label": "B", "text": "b"}]
    # 非标准题型名 + 标准选项 + 单字母答案键 → 客观题（摸底卷的单项选择/细分题型）
    assert is_objective_question(_q("单项选择", opts, "B")) is True
    assert is_objective_question(_q("字音·多音字", opts, "D")) is True
    # 无选项的主观题不受影响
    assert is_objective_question(_q("填空题", [], "x")) is False
    assert is_objective_question(_q("写作·书信", [], "参考范文")) is False
    # 有选项但答案非单字母（如阅读简答）→ 仍走主观分流
    assert is_objective_question(_q("阅读·细节", opts, "第二段")) is False
    # 标准题型名照旧
    assert is_objective_question(_q("选择题", opts, "A")) is True
    assert is_objective_question(_q("判断题", [], "正确")) is True


# --------------------------------------------------------------------------- #
# 交卷：判分 + 回写降级 + 无痕
# --------------------------------------------------------------------------- #
def test_submit_mopq_grades_and_skips_writeback(mopq_client, mopq_repo: Path):
    r = mopq_client.post(
        "/api/quiz/submit",
        json={
            "file_path": FP,
            "section_title": SEC,
            "answers": {"HL-MP-001": "B", "HL-MP-002": "A"},  # 一对一错
        },
    )
    assert r.status_code == 200
    body = r.json()
    # 章节名不含标准套题关键词 → 不回写、不 500、只降级提示
    assert body["writeback"] == "skipped"
    assert "非标准套题名" in body["warning"]

    res = {x["qid"]: x for x in body["results"]}
    # 非标准题型名「单项选择」按客观题判分，并回传正确答案
    assert res["HL-MP-001"]["is_correct"] is True
    assert res["HL-MP-001"]["correct_answer"] == "B"
    assert res["HL-MP-002"]["is_correct"] is False
    assert body["summary"]["correct"] == 1 and body["summary"]["wrong"] == 1

    # 未回写：题库.md 不出现反馈三块
    text = (mopq_repo / FP).read_text(encoding="utf-8")
    assert "订正反馈" not in text and "作答记录" not in text

    # 流水落库（错题本联动照常）
    wrong = mopq_client.get("/api/quiz/wrong").json()
    assert [w["qid"] for w in wrong] == ["HL-MP-002"]


def test_submit_mopq_unanswered_goes_pending(mopq_client):
    r = mopq_client.post(
        "/api/quiz/submit",
        json={"file_path": FP, "section_title": SEC, "answers": {"HL-MP-001": "B"}},
    )
    assert r.status_code == 200
    res = {x["qid"]: x for x in r.json()["results"]}
    assert res["HL-MP-002"]["eval_state"] == "pending_manual"
    assert res["HL-MP-002"]["is_correct"] is None


def test_submit_mopq_wrongbook_subject_mapping(mopq_client, mopq_repo: Path):
    """摸底卷错题的科目归入「护理学基础」（跳过 测验/摸底 两级）。"""
    mopq_client.post(
        "/api/quiz/submit",
        json={
            "file_path": FP,
            "section_title": SEC,
            "answers": {"HL-MP-001": "A", "HL-MP-002": "A"},
        },
    )
    from app.exporter import _subject_of

    assert _subject_of(FP) == "护理学基础"
