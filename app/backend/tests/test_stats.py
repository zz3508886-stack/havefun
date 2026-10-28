"""P5 测试：stats 聚合与流水对齐（总览/趋势/学科/薄弱点/错因分布）。

种子数据全部经 HTTP 接口（submit / feedback / checkin）产生，聚合数字再与
已知种子逐项对齐——验收点即「仪表盘数字与 stats 聚合一致」。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.db import connect

SET = ("数学/一次函数/题库.md", "三、一次函数专项测验")


def _seed_quiz(api_client) -> None:
    """两份卷：卷一 2 对 2 待复核；卷二 2 错 2 待复核。"""
    api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "answers": {"SX-001": "A", "SX-003": "正确", "SX-002": "x", "SX-004": "y"},
        },
    )
    api_client.post(
        "/api/quiz/submit",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "answers": {"SX-001": "B", "SX-003": "错误", "SX-002": "x", "SX-004": "y"},
        },
    )


def _seed_feedback(api_client) -> None:
    api_client.post(
        "/api/quiz/feedback",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "qid": "SX-001",
            "error_type": "概念不清",
            "confused": True,
        },
    )
    api_client.post(
        "/api/quiz/feedback",
        json={
            "file_path": SET[0],
            "section_title": SET[1],
            "qid": "SX-003",
            "error_type": "审题偏差",
            "confused": False,
        },
    )


def _seed_checkins() -> None:
    """三天前 + 昨天 + 今天各打一次卡（今天与昨天连续，三天前中断）。"""
    conn = connect()
    try:
        for offset, node in ((-3, "N01"), (-1, "N01"), (0, "N02")):
            conn.execute(
                "INSERT INTO plan_checkins (node_id, status, notes, created_at) "
                "VALUES (?,?,?, datetime('now', 'localtime', ?))",
                (node, "🟨", "seed", f"{offset} days"),
            )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 总览
# --------------------------------------------------------------------------- #
def test_overview_counts_and_accuracy(api_client):
    _seed_quiz(api_client)
    _seed_feedback(api_client)
    body = api_client.get("/api/stats/overview").json()

    q = body["quiz"]
    assert q["total"] == 8           # 2 卷 × 4 题
    assert q["correct"] == 2         # SX-001 / SX-003 卷一答对
    assert q["wrong"] == 2           # 卷二两题答错
    assert q["pending"] == 4         # 主观题无 AI 端点，两份卷各 2 题待复核
    assert q["judged"] == 4          # 已判 = 对 + 错（待复核不进分母）
    assert q["accuracy"] == 0.5      # 2/4
    assert q["batches"] == 2
    assert q["questions"] == 4       # 去重题目数

    assert body["feedback"]["total"] == 2
    assert body["feedback"]["confused"] == 1


def test_overview_plan_streak(api_client):
    _seed_checkins()
    body = api_client.get("/api/stats/overview").json()
    plan = body["plan"]
    assert plan["checkin_days"] == 3
    assert plan["streak_days"] == 2   # 今天 + 昨天连续；三天前中断不计
    assert plan["last_node"] == "N02"  # 最后一次打卡（今天）是 N02
    assert plan["last_status"] == "🟨"


def test_overview_empty_db_is_zero(client):
    body = client.get("/api/stats/overview").json()
    assert body["quiz"]["total"] == 0
    assert body["quiz"]["accuracy"] == 0.0
    assert body["plan"]["streak_days"] == 0
    assert body["plan"]["last_checkin_at"] is None


# --------------------------------------------------------------------------- #
# 趋势
# --------------------------------------------------------------------------- #
def test_trend_daily_series(api_client):
    _seed_quiz(api_client)
    body = api_client.get("/api/stats/trend", params={"days": 7}).json()
    assert body["days"] == 7
    series = body["series"]
    assert len(series) == 7

    # x 轴连续：从 6 天前到今天，逐日递增
    today = date.today()
    assert series[-1]["date"] == today.isoformat()
    assert series[0]["date"] == (today - timedelta(days=6)).isoformat()
    for prev, cur in zip(series, series[1:]):
        assert date.fromisoformat(cur["date"]) - date.fromisoformat(prev["date"]) == timedelta(days=1)

    # 两份卷都发生在今天
    t = series[-1]
    assert t["answered"] == 8 and t["correct"] == 2 and t["wrong"] == 2 and t["pending"] == 4
    assert t["accuracy"] == 0.5
    # 无答题日补零
    assert series[0]["answered"] == 0 and series[0]["accuracy"] == 0.0


def test_trend_days_clamped(client):
    assert client.get("/api/stats/trend", params={"days": 0}).json()["days"] == 1
    assert client.get("/api/stats/trend", params={"days": 999}).json()["days"] == 90


# --------------------------------------------------------------------------- #
# 学科掌握度
# --------------------------------------------------------------------------- #
def test_subjects_aggregation(api_client):
    _seed_quiz(api_client)
    rows = api_client.get("/api/stats/subjects").json()
    assert len(rows) == 1
    s = rows[0]
    assert s["subject"] == "数学"      # file_path 顶层目录即学科
    assert s["total"] == 8
    assert s["correct"] == 2 and s["wrong"] == 2 and s["pending"] == 4
    assert s["judged"] == 4 and s["accuracy"] == 0.5


# --------------------------------------------------------------------------- #
# 薄弱点
# --------------------------------------------------------------------------- #
def test_weak_ranking(api_client):
    _seed_quiz(api_client)
    body = api_client.get("/api/stats/weak", params={"limit": 5}).json()

    sets = body["sets"]
    assert len(sets) == 1
    top = sets[0]
    assert top["file_path"] == SET[0] and top["section_title"] == SET[1]
    assert top["wrong"] == 2 and top["pending"] == 4
    assert top["subject"] == "数学"

    qs = {q["qid"]: q for q in body["questions"]}
    assert set(qs) == {"SX-001", "SX-003"}  # 只有答错的题进出错榜
    assert qs["SX-001"]["times"] == 1 and qs["SX-001"]["q_type"] == "选择题"
    assert qs["SX-003"]["times"] == 1 and qs["SX-003"]["q_type"] == "判断题"


def test_weak_empty(client):
    body = client.get("/api/stats/weak").json()
    assert body["sets"] == [] and body["questions"] == []


# --------------------------------------------------------------------------- #
# 错因分布
# --------------------------------------------------------------------------- #
def test_error_types_distribution(api_client):
    _seed_quiz(api_client)
    _seed_feedback(api_client)
    body = api_client.get("/api/stats/error-types").json()

    by = {t["error_type"]: t for t in body["types"]}
    assert set(by) == {"概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"}
    # 客观题答错默认归「概念不清」：卷二两题 → auto=2；反馈自选再 +1
    assert by["概念不清"]["auto"] == 2
    assert by["概念不清"]["self"] == 1
    assert by["概念不清"]["total"] == 3
    # 审题偏差仅来自反馈自选
    assert by["审题偏差"]["self"] == 1 and by["审题偏差"]["total"] == 1
    assert by["计算失误"]["total"] == 0
    # 待复核不计入错因分布
    assert all("待复核" not in t["error_type"] for t in body["types"])
    assert body["confused"] == 1
