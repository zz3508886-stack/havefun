"""测验引擎 HTTP 接口：套题列表 / 取题(不下发答案键) / 提交判分 + 回写。

答案键仅服务端持有：GET /set 的题目载荷绝不携带 answer_key；POST /submit 在服务端
用 questions_index.answer_key 判分，客观题当场出分，主观题降级待复核，结果不内联进
markdown。回写(题库.md 三块)失败(冲突/过检)时判分已落库，返回降级标记而非崩溃。
"""

from __future__ import annotations

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pathlib import Path

from .ai_grader import make_ai_grader
from .config import load_config
from .db import connect
from .grading import GradedQuestion, grade_set
from .indexer import REPO_ROOT
from .parser import Question, is_objective_question, parse_explanations
from .writeback import PreCheckError, WriteConflict, write_back

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


class ReviewRequest(BaseModel):
    batch_id: str
    file_path: str
    qid: str
    is_correct: bool
    error_type: Optional[str] = None


@router.post("/review")
def review(req: ReviewRequest) -> dict:
    """人工复核：把待复核(pending_manual)翻为 对/错，写回 quiz_attempts。

    仅更新本次 batch 内对应 qid 的那条记录；判对则清空错因，判错保留（可选）错因。
    """
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE quiz_attempts SET is_correct=?, eval_state='done', eval_type='manual', "
            "error_type=? WHERE batch_id=? AND file_path=? AND qid=?",
            (
                int(req.is_correct),
                None if req.is_correct else (req.error_type or None),
                req.batch_id,
                req.file_path,
                req.qid,
            ),
        )
        conn.commit()
        updated = cur.rowcount
    finally:
        conn.close()
    if updated == 0:
        raise HTTPException(status_code=404, detail="未找到该待复核记录（可能已复核或批次不符）")

    # P9：复核会翻转对错 → 可能新增/消除错题册条目，刷新导出视图（best-effort）
    from .exporter import safe_export

    wrongbook_export = safe_export("wrongbook")
    return {
        "ok": True,
        "qid": req.qid,
        "is_correct": req.is_correct,
        "updated": updated,
        "wrongbook_export": wrongbook_export,
    }


class SubmitRequest(BaseModel):
    file_path: str
    section_title: str
    answers: dict[str, str]


def _load_set(file_path: str, section_title: str) -> list[Question]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT qid, section_title, q_type, stem, options_json, answer_key, difficulty "
            "FROM questions_index WHERE file_path=? AND section_title=? ORDER BY rowid",
            (file_path, section_title),
        ).fetchall()
    finally:
        conn.close()
    out: list[Question] = []
    for r in rows:
        out.append(
            Question(
                qid=r["qid"],
                file_path=file_path,
                section_title=r["section_title"],
                q_type=r["q_type"],
                stem=r["stem"],
                options=json.loads(r["options_json"] or "[]"),
                answer_key=r["answer_key"],
                difficulty=r["difficulty"] or "",
            )
        )
    return out


@router.get("/sets")
def list_sets() -> list[dict]:
    """列出全部已索引套题（含是否有答案键，但不下发答案键本身）。"""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT file_path, section_title, count(*) AS n, "
            "SUM(CASE WHEN answer_key IS NOT NULL AND answer_key != '' THEN 1 ELSE 0 END) AS has_key "
            "FROM questions_index GROUP BY file_path, section_title "
            "ORDER BY file_path, section_title"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "file_path": r["file_path"],
            "section_title": r["section_title"],
            "n_questions": r["n"],
            "has_key": bool(r["has_key"]),
        }
        for r in rows
    ]


@router.get("/set")
def get_set(file_path: str, section_title: str) -> dict:
    """取一套题（不含 answer_key，答案键仅服务端判分时使用）。"""
    qs = _load_set(file_path, section_title)
    if not qs:
        raise HTTPException(status_code=404, detail="套题不存在或未索引")
    return {
        "file_path": file_path,
        "section_title": section_title,
        "questions": [
            {
                "qid": q.qid,
                "q_type": q.q_type,
                "stem": q.stem,
                "options": q.options,
                "difficulty": q.difficulty,
            }
            for q in qs
        ],
    }


def _to_results(graded, qmeta: dict, expl_map: dict) -> list[dict]:
    out: list[dict] = []
    for r in graded.results:
        q = qmeta.get(r.qid)
        fp = q.file_path if q else ""
        st = q.section_title if q else ""
        item = {
            "qid": r.qid,
            "key": f"{fp}#{r.qid}",
            "file_path": fp,
            "section_title": st,
            "q_type": r.q_type,
            "difficulty": r.difficulty,
            "stem": q.stem if q else "",
            "options": q.options if q else [],
            "student": r.student,
            "is_correct": r.is_correct,
            "eval_state": r.eval_state,
            "error_type": r.error_type,
            "note": r.note,
            "explanation": expl_map.get((fp, r.qid), "") if q else "",
        }
        # 仅客观题在判定后回传正确答案（判分结果，非预下发答案键）
        if q is not None and is_objective_question(q) and r.is_correct is not None:
            item["correct_answer"] = r.key_answer
        out.append(item)
    return out


@router.post("/submit")
def submit(req: SubmitRequest) -> dict:
    qs = _load_set(req.file_path, req.section_title)
    if not qs:
        raise HTTPException(status_code=404, detail="套题不存在或未索引")

    # P2：默认无 AI 端点 → 主观题降级 pending_manual；配置后走 AI 初判
    graded = grade_set(qs, req.answers, ai_grader=make_ai_grader(load_config()))

    # 题干/选项（来自题目索引）+ 解析（来自同名 题库解析.md），用于回显完整试题
    qmeta = {q.qid: q for q in qs}
    analysis_path = (
        Path(REPO_ROOT / req.file_path).with_name(
            Path(req.file_path).name.replace("题库", "题库解析")
        )
    )
    expl_map = {(req.file_path, k): v for k, v in parse_explanations(analysis_path).items()}

    batch_id = uuid.uuid4().hex
    conn = connect()
    try:
        for r in graded.results:
            conn.execute(
                "INSERT INTO quiz_attempts "
                "(batch_id, file_path, qid, user_answer, is_correct, eval_type, "
                "eval_state, error_type) VALUES (?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    req.file_path,
                    r.qid,
                    r.student,
                    r.is_correct,
                    r.eval_type,
                    r.eval_state,
                    r.error_type,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    payload = {
        "batch_id": batch_id,
        "results": _to_results(graded, qmeta, expl_map),
        "summary": graded.summary,
    }
    try:
        write_back(req.file_path, req.section_title, graded)
        payload["writeback"] = "written"
    except WriteConflict as exc:
        # 冲突：判分已落库，仅跳过本次回写并提示
        payload["writeback"] = "conflict"
        payload["warning"] = str(exc)
    except PreCheckError as exc:
        payload["writeback"] = "precheck_failed"
        payload["warning"] = "回写内容未通过校验器检查，已跳过写入"
    except ValueError as exc:
        # 章节名不含标准套题关键词（如摸底卷「概念摸底（A卷）」）→ 不回写，判分照常
        payload["writeback"] = "skipped"
        payload["warning"] = f"该章节非标准套题名，跳过回写：{exc}"

    # P9：交卷可能产生新错题 → 刷新错题本导出视图（best-effort，失败不影响交卷）
    from .exporter import safe_export

    payload["wrongbook_export"] = safe_export("wrongbook")

    # P7：交互后刷新 AI 一页纸快照（best-effort，失败不影响交卷）
    from .ai import refresh_snapshot

    refresh_snapshot()
    return payload


def _load_question(file_path: str, qid: str) -> Optional[Question]:
    """按 (file_path, qid) 取单题（含 answer_key，仅服务端判分用）。"""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT qid, section_title, q_type, stem, options_json, answer_key, difficulty "
            "FROM questions_index WHERE file_path=? AND qid=?",
            (file_path, qid),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return Question(
        qid=row["qid"],
        file_path=file_path,
        section_title=row["section_title"],
        q_type=row["q_type"],
        stem=row["stem"],
        options=json.loads(row["options_json"] or "[]"),
        answer_key=row["answer_key"],
        difficulty=row["difficulty"] or "",
    )


@router.get("/wrong-paper")
def wrong_paper(by: str, value: str) -> dict:
    """按口径聚合错题，返回可组成一张试卷的题目列表。

    by=cat(大类别/学科) | sub(小类别/章节) | quiz(单套题)；value 为对应取值。
    每题 qid 用 ``file_path#qid`` 复合键，避免跨文件 qid 撞车。
    """
    if by not in ("cat", "sub", "quiz"):
        raise HTTPException(status_code=400, detail="by 必须是 cat/sub/quiz 之一")
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT a.file_path AS file_path, q.section_title AS section_title, "
            "a.qid AS qid FROM quiz_attempts a LEFT JOIN questions_index q "
            "ON q.file_path = a.file_path AND q.qid = a.qid WHERE a.is_correct = 0"
        ).fetchall()
    finally:
        conn.close()

    picked: list[dict] = []
    seen: set = set()
    for r in rows:
        fp = r["file_path"]
        st = r["section_title"]
        qid = r["qid"]
        if by == "cat" and fp.split("/", 1)[0] != value:
            continue
        if by == "sub" and st != value:
            continue
        if by == "quiz" and f"{fp}#{st}" != value:
            continue
        k = (fp, qid)
        if k in seen:
            continue
        seen.add(k)
        q = _load_question(fp, qid)
        if not q:
            continue
        picked.append(
            {
                "qid": f"{fp}#{qid}",  # 前端复合键
                "real_qid": qid,
                "file_path": fp,
                "section_title": st,
                "q_type": q.q_type,
                "stem": q.stem,
                "options": q.options,
                "difficulty": q.difficulty,
            }
        )
    return {"by": by, "value": value, "questions": picked}


class SubmitWrongRequest(BaseModel):
    items: List[dict]
    answers: dict[str, str]


@router.post("/submit-wrong")
def submit_wrong(req: SubmitWrongRequest) -> dict:
    """提交一张「错题卷」：由一组跨套题的错题组成，逐题判分并落库。

    与 /submit 不同，这里不绑定单一 (file_path, section_title)；每题用复合键判分，
    落库时还原真实 file_path+real_qid。回写（写回题库.md）对混合卷跳过。
    """
    qs: list[Question] = []
    real_info: list[tuple] = []  # (file_path, real_qid, section_title)
    for it in req.items:
        fp = it.get("file_path")
        qid = it.get("qid")
        if not fp or not qid:
            continue
        q = _load_question(fp, qid)
        if not q:
            continue
        real_info.append((fp, qid, it.get("section_title") or q.section_title))
        qs.append(q)
    if not qs:
        raise HTTPException(status_code=404, detail="未找到对应的错题试题")

    # 判分用复合键，避免跨文件 qid 冲突
    for i, q in enumerate(qs):
        q.qid = f"{real_info[i][0]}#{real_info[i][1]}"

    graded = grade_set(qs, req.answers, ai_grader=make_ai_grader(load_config()))

    expl_map: dict = {}
    for q in qs:
        ap = Path(REPO_ROOT / q.file_path).with_name(
            Path(q.file_path).name.replace("题库", "题库解析")
        )
        for k, v in parse_explanations(ap).items():
            expl_map[(q.file_path, k)] = v

    batch_id = uuid.uuid4().hex
    out: list[dict] = []
    conn = connect()
    try:
        for i, r in enumerate(graded.results):
            fp, real_qid, st = real_info[i]
            q = qs[i]
            item = {
                "qid": real_qid,
                "key": f"{fp}#{real_qid}",
                "file_path": fp,
                "section_title": st,
                "q_type": r.q_type,
                "difficulty": r.difficulty,
                "stem": q.stem,
                "options": q.options,
                "student": r.student,
                "is_correct": r.is_correct,
                "eval_state": r.eval_state,
                "error_type": r.error_type,
                "note": r.note,
                "explanation": expl_map.get((fp, real_qid), ""),
            }
            if is_objective_question(qs[i]) and r.is_correct is not None:
                item["correct_answer"] = r.key_answer
            out.append(item)
            conn.execute(
                "INSERT INTO quiz_attempts "
                "(batch_id, file_path, qid, user_answer, is_correct, eval_type, "
                "eval_state, error_type) VALUES (?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    fp,
                    real_qid,
                    r.student,
                    r.is_correct,
                    r.eval_type,
                    r.eval_state,
                    r.error_type,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    # P9：错题卷同样产生流水 → 刷新错题本导出视图（best-effort）
    from .exporter import safe_export

    return {
        "batch_id": batch_id,
        "results": out,
        "summary": graded.summary,
        "writeback": "skipped",
        "wrongbook_export": safe_export("wrongbook"),
    }
