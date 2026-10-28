"""学情聚合层（纯函数，无 FastAPI 依赖）：仪表盘与 AI 取数通道的唯一数据源。

stats 路由（人看）与 ai 通道（CLI/快照/API，AI 看）都调用本层函数，
保证「仪表盘数字与快照一致」——P5/P7 的验收点。

口径约定（tests 对齐）：
- 「已判」= is_correct 非 NULL；正确率 = correct / 已判，待复核不进分母。
- 日期分组用本地时间（SQLite CURRENT_TIMESTAMP 为 UTC）。
- 学科 = file_path 顶层目录；套题 = (file_path, section_title)。
"""

from __future__ import annotations

from datetime import date, timedelta

from .db import connect

ERROR_TYPES = ["概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"]


def _accuracy(correct: int, judged: int) -> float:
    return round(correct / judged, 4) if judged else 0.0


def _subject_of(file_path: str) -> str:
    return file_path.split("/", 1)[0] if file_path else ""


# --------------------------------------------------------------------------- #
# 总览
# --------------------------------------------------------------------------- #
def overview() -> dict:
    """一页纸总览：做题总量与正确率、反馈、打卡连续性。"""
    conn = connect()
    try:
        q = conn.execute(
            "SELECT count(*) AS total, "
            "SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct, "
            "SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS wrong, "
            "SUM(CASE WHEN is_correct IS NULL THEN 1 ELSE 0 END) AS pending, "
            "count(DISTINCT batch_id) AS batches, "
            "count(DISTINCT file_path || '#' || qid) AS questions "
            "FROM quiz_attempts"
        ).fetchone()
        fb = conn.execute(
            "SELECT count(*) AS total, "
            "SUM(CASE WHEN confused=1 THEN 1 ELSE 0 END) AS confused "
            "FROM quiz_feedback"
        ).fetchone()
        days = [
            r["d"]
            for r in conn.execute(
                "SELECT DISTINCT strftime('%Y-%m-%d', created_at, 'localtime') AS d "
                "FROM plan_checkins ORDER BY d"
            ).fetchall()
        ]
        last_ck = conn.execute(
            "SELECT node_id, status, created_at FROM plan_checkins ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    total = q["total"] or 0
    correct = q["correct"] or 0
    wrong = q["wrong"] or 0
    pending = q["pending"] or 0
    judged = correct + wrong

    # 连续打卡：从最近一天往前数连续不断的日期（最近打卡是今天或昨天才计入）
    streak = 0
    if days:
        day_set = set(days)
        cursor = date.fromisoformat(days[-1])
        if (date.today() - cursor).days <= 1:
            while cursor.isoformat() in day_set:
                streak += 1
                cursor -= timedelta(days=1)

    return {
        "quiz": {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "pending": pending,
            "judged": judged,
            "accuracy": _accuracy(correct, judged),
            "batches": q["batches"] or 0,
            "questions": q["questions"] or 0,
        },
        "feedback": {"total": fb["total"] or 0, "confused": fb["confused"] or 0},
        "plan": {
            "checkin_days": len(days),
            "streak_days": streak,
            "last_checkin_at": last_ck["created_at"] if last_ck else None,
            "last_node": last_ck["node_id"] if last_ck else None,
            "last_status": last_ck["status"] if last_ck else None,
        },
    }


# --------------------------------------------------------------------------- #
# 趋势（按日）
# --------------------------------------------------------------------------- #
def trend(days: int = 30) -> dict:
    """最近 N 天每日答题趋势（缺失日补零，保证折线 x 轴连续）。"""
    days = max(1, min(days, 90))
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT strftime('%Y-%m-%d', created_at, 'localtime') AS d, "
            "count(*) AS answered, "
            "SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct, "
            "SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS wrong, "
            "SUM(CASE WHEN is_correct IS NULL THEN 1 ELSE 0 END) AS pending "
            "FROM quiz_attempts "
            "WHERE created_at >= date('now', 'localtime', ?) "
            "GROUP BY d ORDER BY d",
            (f"-{days - 1} days",),
        ).fetchall()
    finally:
        conn.close()

    by_day = {r["d"]: r for r in rows}
    series = []
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        r = by_day.get(d)
        answered = r["answered"] if r else 0
        correct = r["correct"] if r else 0
        wrong = r["wrong"] if r else 0
        pending = r["pending"] if r else 0
        series.append(
            {
                "date": d,
                "answered": answered,
                "correct": correct,
                "wrong": wrong,
                "pending": pending,
                "accuracy": _accuracy(correct, correct + wrong),
            }
        )
    return {"days": days, "series": series}


# --------------------------------------------------------------------------- #
# 学科掌握度
# --------------------------------------------------------------------------- #
def subjects() -> list[dict]:
    """各学科（一级目录）掌握度：已判正确率 + 错题/待复核量，错误多的排前。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT file_path, "
            "SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct, "
            "SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS wrong, "
            "SUM(CASE WHEN is_correct IS NULL THEN 1 ELSE 0 END) AS pending, "
            "count(*) AS total "
            "FROM quiz_attempts GROUP BY file_path"
        ).fetchall()
    finally:
        conn.close()

    agg: dict[str, dict] = {}
    for r in rows:
        subj = _subject_of(r["file_path"])
        a = agg.setdefault(
            subj, {"subject": subj, "total": 0, "correct": 0, "wrong": 0, "pending": 0}
        )
        a["total"] += r["total"] or 0
        a["correct"] += r["correct"] or 0
        a["wrong"] += r["wrong"] or 0
        a["pending"] += r["pending"] or 0
    out = []
    for a in agg.values():
        judged = a["correct"] + a["wrong"]
        out.append({**a, "judged": judged, "accuracy": _accuracy(a["correct"], judged)})
    out.sort(key=lambda x: (-x["wrong"], -x["pending"], x["subject"]))
    return out


# --------------------------------------------------------------------------- #
# 薄弱点
# --------------------------------------------------------------------------- #
def weak(limit: int = 10) -> dict:
    """薄弱套题榜 + 重复错题榜（错题本「出现次数」的流水版）。"""
    limit = max(1, min(limit, 50))
    conn = connect()
    try:
        sets = conn.execute(
            "SELECT a.file_path AS file_path, q.section_title AS section_title, "
            "SUM(CASE WHEN a.is_correct=0 THEN 1 ELSE 0 END) AS wrong, "
            "SUM(CASE WHEN a.is_correct IS NULL THEN 1 ELSE 0 END) AS pending, "
            "MAX(a.created_at) AS last_at "
            "FROM quiz_attempts a "
            "LEFT JOIN questions_index q ON q.file_path=a.file_path AND q.qid=a.qid "
            "GROUP BY a.file_path, q.section_title"
        ).fetchall()
        qids = conn.execute(
            "SELECT a.file_path AS file_path, a.qid AS qid, q.stem AS stem, "
            "q.q_type AS q_type, count(*) AS times, MAX(a.created_at) AS last_at "
            "FROM quiz_attempts a "
            "LEFT JOIN questions_index q ON q.file_path=a.file_path AND q.qid=a.qid "
            "WHERE a.is_correct=0 GROUP BY a.file_path, a.qid"
        ).fetchall()
    finally:
        conn.close()

    set_rows = []
    for r in sets:
        wrong = r["wrong"] or 0
        pending = r["pending"] or 0
        if wrong == 0 and pending == 0:
            continue
        set_rows.append(
            {
                "subject": _subject_of(r["file_path"]),
                "file_path": r["file_path"],
                "section_title": r["section_title"] or "",
                "wrong": wrong,
                "pending": pending,
                "last_at": r["last_at"],
            }
        )
    set_rows.sort(key=lambda x: (-x["wrong"], -x["pending"], x["last_at"] or ""))

    qid_rows = [
        {
            "subject": _subject_of(r["file_path"]),
            "file_path": r["file_path"],
            "qid": r["qid"],
            "stem": r["stem"] or "",
            "q_type": r["q_type"] or "",
            "times": r["times"] or 0,
            "last_at": r["last_at"],
        }
        for r in qids
    ]
    qid_rows.sort(key=lambda x: (-x["times"], x["last_at"] or ""))
    return {"sets": set_rows[:limit], "questions": qid_rows[:limit]}


# --------------------------------------------------------------------------- #
# 错因分布
# --------------------------------------------------------------------------- #
def error_types() -> dict:
    """R18 五类错因分布（attempts 的 error_type + feedback 的自选错因）+ 疑难点计数。"""
    conn = connect()
    try:
        att = conn.execute(
            "SELECT error_type, count(*) AS n FROM quiz_attempts "
            "WHERE is_correct=0 AND error_type IS NOT NULL AND error_type != '待复核' "
            "GROUP BY error_type"
        ).fetchall()
        fbk = conn.execute(
            "SELECT error_type, count(*) AS n FROM quiz_feedback "
            "WHERE error_type IS NOT NULL GROUP BY error_type"
        ).fetchall()
        confused = conn.execute(
            "SELECT count(*) AS n FROM quiz_feedback WHERE confused=1"
        ).fetchone()
    finally:
        conn.close()

    by_type = {t: {"auto": 0, "self": 0} for t in ERROR_TYPES}
    for r in att:
        if r["error_type"] in by_type:
            by_type[r["error_type"]]["auto"] = r["n"] or 0
    for r in fbk:
        if r["error_type"] in by_type:
            by_type[r["error_type"]]["self"] = r["n"] or 0
    return {
        "types": [
            {"error_type": t, "auto": v["auto"], "self": v["self"], "total": v["auto"] + v["self"]}
            for t, v in by_type.items()
        ],
        "confused": confused["n"] or 0,
    }


# --------------------------------------------------------------------------- #
# 待复核 / 最近流水
# --------------------------------------------------------------------------- #
def pending(limit: int = 20) -> list[dict]:
    """待人工复核的作答（is_correct NULL），供 AI 批量判分或提示用户复核。"""
    limit = max(1, min(limit, 200))
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT a.batch_id AS batch_id, a.file_path AS file_path, a.qid AS qid, "
            "a.user_answer AS user_answer, a.is_correct AS is_correct, "
            "a.eval_state AS eval_state, a.created_at AS created_at, "
            "q.section_title AS section_title, q.q_type AS q_type, q.stem AS stem "
            "FROM quiz_attempts a "
            "LEFT JOIN questions_index q ON q.file_path=a.file_path AND q.qid=a.qid "
            "WHERE a.is_correct IS NULL ORDER BY a.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def recent(limit: int = 20) -> list[dict]:
    """最近答题流水（新的在前），含判定结果与错因。"""
    limit = max(1, min(limit, 200))
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT a.batch_id AS batch_id, a.file_path AS file_path, a.qid AS qid, "
            "a.user_answer AS user_answer, a.is_correct AS is_correct, "
            "a.eval_type AS eval_type, a.eval_state AS eval_state, "
            "a.error_type AS error_type, a.created_at AS created_at, "
            "q.section_title AS section_title, q.q_type AS q_type, q.stem AS stem "
            "FROM quiz_attempts a "
            "LEFT JOIN questions_index q ON q.file_path=a.file_path AND q.qid=a.qid "
            "ORDER BY a.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
