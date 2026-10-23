"""P3 测试：反馈落库 + 疑难点.md 累加 + 错题本联动。"""

from pathlib import Path


def _seed_ynd(quiz_repo: Path) -> None:
    d = quiz_repo / "错题本"
    d.mkdir(parents=True, exist_ok=True)
    (d / "疑难点.md").write_text(
        "# 疑难点\n\n"
        "| 项目 | 内容 |\n| --- | --- |\n| 学科 | 错题本 |\n| 分类 | 疑难点 |\n\n"
        "## 一、疑难点记录\n\n"
        "| 专题 | 学科 | 出现次数 | 首次出现 | 最近出现 | 关联问题摘要 | 对应章节链接 | 状态 |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | ⬜ |\n",
        encoding="utf-8",
    )


def _ynd_text(quiz_repo: Path) -> str:
    return (quiz_repo / "错题本" / "疑难点.md").read_text(encoding="utf-8")


def test_feedback_records_and_appends_ynd(api_client, quiz_repo):
    _seed_ynd(quiz_repo)
    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "qid": "SX-001",
        "error_type": "概念不清",
        "confused": True,
    }
    r1 = api_client.post("/api/quiz/feedback", json=payload)
    assert r1.status_code == 200
    assert r1.json()["ynd_appended"] is True

    # 落库
    from app.db import connect

    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM quiz_feedback").fetchone()[0]
        row = conn.execute(
            "SELECT error_type, confused FROM quiz_feedback WHERE qid='SX-001'"
        ).fetchone()
    finally:
        conn.close()
    assert n == 1
    assert row["error_type"] == "概念不清" and row["confused"] == 1

    # 疑难点.md 累加（出现次数 1，替换占位行）
    t = _ynd_text(quiz_repo)
    assert "三、一次函数专项测验" in t and "| 数学 |" in t
    assert "| 1 |" in t

    # 再次反馈同专题 → 累加为 2，不新增行
    r2 = api_client.post("/api/quiz/feedback", json=payload)
    assert r2.status_code == 200
    t2 = _ynd_text(quiz_repo)
    # 出现次数 2 的那一行仍存在；占位行应已被替换（不再有孤立的「待填写 | 待填写 | 待填写」）
    assert "| 2 |" in t2
    assert t2.count("三、一次函数专项测验") == 1


def test_feedback_non_confused_does_not_append(api_client, quiz_repo):
    _seed_ynd(quiz_repo)
    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "qid": "SX-002",
        "error_type": "计算失误",
        "confused": False,
    }
    r = api_client.post("/api/quiz/feedback", json=payload)
    assert r.status_code == 200
    assert r.json()["ynd_appended"] is False

    from app.db import connect

    conn = connect()
    try:
        n = conn.execute("SELECT count(*) FROM quiz_feedback").fetchone()[0]
    finally:
        conn.close()
    assert n == 1
    # 疑难点.md 未被改写（仍只有占位行）
    assert "三、一次函数专项测验" not in _ynd_text(quiz_repo)


def test_feedback_rejects_invalid_error_type(api_client, quiz_repo):
    _seed_ynd(quiz_repo)
    payload = {
        "file_path": "数学/一次函数/题库.md",
        "section_title": "三、一次函数专项测验",
        "qid": "SX-003",
        "error_type": "瞎填的错因",
        "confused": True,
    }
    r = api_client.post("/api/quiz/feedback", json=payload)
    assert r.status_code == 422


def test_wrong_endpoint_lists_wrong_answers(api_client):
    # 交一份含错误答案的卷
    submit = api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": "数学/一次函数/题库.md",
            "section_title": "三、一次函数专项测验",
            "answers": {"SX-001": "B", "SX-003": "错误"},  # 均答错
        },
    )
    assert submit.status_code == 200

    r = api_client.get("/api/quiz/wrong")
    assert r.status_code == 200
    wrong = r.json()
    qids = {w["qid"] for w in wrong}
    assert "SX-001" in qids and "SX-003" in qids
    sx1 = next(w for w in wrong if w["qid"] == "SX-001")
    assert sx1["times"] >= 1
    assert sx1["q_type"] == "选择题"
