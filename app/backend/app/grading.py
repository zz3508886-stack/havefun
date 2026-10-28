"""服务端判分引擎（移植自初版网页刷题服务的判分逻辑，该服务于 P8 退役）。

判分是「错一步全盘错」的模块：客观题（选择/判断）脚本即时判分；非客观题
（填空/解答/操作/面试）走 AI 初判，未配置端点时降级为「待人工复核（pending_manual）」。
判分结果不直接内联进 markdown（答案键仅服务端持有），回写由 writeback 模块负责。

逻辑须由 pytest 覆盖（tests/test_quiz.py）：客观题对错、判断题语义归一、
主观题 AI 命中/失败/缺端点三种分流、未作答归待复核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from .parser import ERROR_TYPES, Question, is_objective_question

# AI 判分器签名：fn(question, student, answer_key) -> {"correct": bool|None,
# "错因类型": str, "错因说明": str}。未配置端点时传 None，主观题降级待复核。
AI_Grader = Callable[[Question, str, str], dict]


@dataclass
class GradedQuestion:
    qid: str
    q_type: str
    difficulty: str
    student: str
    is_correct: Optional[bool]          # True/False/None(待判)
    eval_type: str                      # auto / ai / manual
    eval_state: str                     # done / pending_manual（evaluating 为生产异步态）
    error_type: Optional[str]           # R18 五类错因 / 待复核 / None
    note: str
    key_answer: str


@dataclass
class GradingResult:
    results: list
    summary: dict


def _norm_judge(s: str) -> str:
    """判断题语义归一：把中英文/符号写法统一成「正确」「错误」。"""
    s = (s or "").strip().lower()
    if s in ("正确", "对", "√", "t", "true", "yes", "是对的", "正确。"):
        return "正确"
    if s in ("错误", "错", "×", "f", "false", "no", "不对", "是错的", "错误。"):
        return "错误"
    return s


def _grade_objective(q_type: str, student: str, key_answer: str):
    """客观题脚本判分，返回 (correct, 归一学生作答, 归一答案键)。"""
    if q_type == "判断题":
        ns, nk = _norm_judge(student), _norm_judge(key_answer)
        return (ns == nk and ns in ("正确", "错误")), ns, nk
    # 选择题：取首位字母比较（大小写不敏感）
    sk = re.match(r"([A-Za-z])", (student or "").strip())
    kk = re.match(r"([A-Za-z])", (key_answer or "").strip())
    if not sk or not kk:
        return False, (student or "").strip(), (key_answer or "").strip()
    return (
        sk.group(1).upper() == kk.group(1).upper(),
        sk.group(1).upper(),
        kk.group(1).upper(),
    )


def grade_set(
    questions: list[Question],
    answers: dict,
    ai_grader: Optional[AI_Grader] = None,
) -> GradingResult:
    """对一套题判分。questions 来自 questions_index（含 answer_key，仅服务端可见）。"""
    results: list[GradedQuestion] = []
    pending = 0
    for q in questions:
        student = str(answers.get(q.qid, "") or "").strip()
        is_objective = is_objective_question(q)
        rec = GradedQuestion(
            qid=q.qid,
            q_type=q.q_type,
            difficulty=q.difficulty or "",
            student=student,
            is_correct=None,
            eval_type="auto",
            eval_state="done",
            error_type=None,
            note="",
            key_answer=q.answer_key,
        )
        if not student:
            rec.error_type = "待复核"
            rec.note = "未作答"
            rec.eval_state = "pending_manual"
            rec.eval_type = "manual"
            pending += 1
            results.append(rec)
            continue

        if is_objective:
            ok, ns, nk = _grade_objective(q.q_type, student, q.answer_key)
            rec.is_correct = ok
            rec.student = ns
            rec.key_answer = nk
            if ok:
                rec.note = "客观题脚本判定正确"
            else:
                rec.error_type = "概念不清"  # 客观题答错默认归为概念不清
                rec.note = "客观题脚本判定错误"
        else:
            if ai_grader is not None:
                try:
                    r = ai_grader(q, student, q.answer_key)
                    rec.is_correct = r.get("correct")
                    rec.error_type = r.get("错因类型", "待复核")
                    rec.note = r.get("错因说明", "")
                    rec.eval_type = "ai"
                    if rec.is_correct is None:
                        rec.eval_state = "pending_manual"
                        pending += 1
                except Exception:
                    # DEGRADE: AI 判分异常不阻塞整卷，降级待人工复核
                    rec.is_correct = None
                    rec.error_type = "待复核"
                    rec.note = "AI 判分失败，待人工复核"
                    rec.eval_type = "ai"
                    rec.eval_state = "pending_manual"
                    pending += 1
            else:
                rec.is_correct = None
                rec.error_type = "待复核"
                rec.note = "未配置 AI 端点，待复核"
                rec.eval_state = "pending_manual"
                rec.eval_type = "manual"
                pending += 1
        results.append(rec)

    total = len(results)
    correct = sum(1 for r in results if r.is_correct is True)
    pending = pending
    wrong = total - correct - pending
    wrong_ids = [r.qid for r in results if r.is_correct is False]
    summary = {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "pending": pending,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "wrong_ids": wrong_ids,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return GradingResult(results=results, summary=summary)
