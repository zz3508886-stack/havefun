"""havefun 网页刷题 —— 题库解析、判分、回写与统计。

纯标准库实现，无第三方依赖。负责：
1. 扫描仓库内所有 题库.md，解析出可刷题的「套题」（含题目与答案键）。
2. 判分：客观题（选择/判断）由脚本比对答案键；非客观题（填空/解答/操作/面试）
   交给 ai_grader 用大模型初判，未配置模型端点时标「待复核」。
3. 回写：把机器判分结果写入 题库.md 的「作答记录」「订正反馈」「评估」三块，
   保留 danzhao-docs 的 R18/R19 校验所需结构，不内联 答案/解析（R17）。
4. 统计：汇总 results.json，供监控页使用。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
RESULTS_PATH = WEB_DIR / "results.json"

SET_RE = re.compile(r"测验|专项|模拟卷|真题|自测|练习")
QH_RE = re.compile(r"^###\s*第\s*([0-9]+)\s*题\s*[（(](.*?)[）)]\s*$")
HEAD_RE = re.compile(r"^#{2,3}\s*(.*?)\s*$")
OPT_RE = re.compile(r"^\s*[-*]\s*([A-Za-z])\s*[.、]\s*(.*)$")
ANS_RE = re.compile(r"答案[:：]\s*(.+)")
ANALYSIS_RE = re.compile(r"解析[:：]")
ID_RE = re.compile(r"^###\s*([A-Za-z0-9\-]+)\s*[（(]")
FB_HEAD_RE = re.compile(r"^###\s*订正反馈")
ZL_HEAD_RE = re.compile(r"^###\s*作答记录")
EV_HEAD_RE = re.compile(r"^###\s*评估")

ERROR_TYPES = ["概念不清", "计算失误", "思路错误", "审题偏差", "知识遗忘"]
OBJECTIVE_TYPES = {"选择题", "判断题"}

# 错因类型 -> 在「订正反馈」模板中的中文标签（与 danzhao-docs 一致）
ERROR_TYPE_LABELS = ERROR_TYPES


# --------------------------------------------------------------------------- #
# 结果存储
# --------------------------------------------------------------------------- #
def load_results() -> dict:
    if RESULTS_PATH.exists():
        try:
            return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"attempts": []}
    return {"attempts": []}


def save_results(data: dict) -> None:
    RESULTS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def append_attempt(attempt: dict) -> None:
    data = load_results()
    data.setdefault("attempts", []).append(attempt)
    save_results(data)


# --------------------------------------------------------------------------- #
# 题库解析
# --------------------------------------------------------------------------- #
def _iter_md_files():
    for p in REPO_ROOT.rglob("题库.md"):
        yield p


def _parse_header_inside(inside: str):
    """从「SX-001，选择题，【基础｜难度 2】」拆出 (id, type, difficulty)。"""
    m = re.match(
        r"^\s*([A-Za-z0-9\-]+)\s*[，,]\s*([^，,]+?)\s*[，,]\s*(.+)$", inside
    )
    if not m:
        return None, None, None
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip()


def _split_sections(lines):
    """把文件行切成二级章节，返回 [(title, start_idx, end_idx)]。"""
    sections = []
    cur = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("### "):
            if cur is not None:
                sections.append((cur[0], cur[1], i))
            cur = (line[3:].strip(), i, len(lines))
        elif cur is None and line.startswith("# "):
            # 文件开头到第一个二级标题也记一段，避免漏掉内容
            cur = ("", 0, len(lines))
    if cur is not None:
        sections.append((cur[0], cur[1], len(lines)))
    return sections


def _parse_questions_in_section(sec_lines):
    questions = []
    i = 0
    n = len(sec_lines)
    while i < n:
        m = QH_RE.match(sec_lines[i])
        if m:
            qindex = int(m.group(1))
            qid, qtype, qdiff = _parse_header_inside(m.group(2))
            if qid is None:
                i += 1
                continue
            body = []
            options = []
            j = i + 1
            while j < n and not HEAD_RE.match(sec_lines[j]):
                om = OPT_RE.match(sec_lines[j])
                if om:
                    options.append({"label": om.group(1), "text": om.group(2).strip()})
                else:
                    body.append(sec_lines[j])
                j += 1
            stem = "\n".join(l.strip() for l in body).strip()
            questions.append(
                {
                    "id": qid,
                    "index": qindex,
                    "type": qtype,
                    "difficulty": qdiff,
                    "stem": stem,
                    "options": options,
                }
            )
            i = j
        else:
            i += 1
    return questions


def _parse_answer_key(analysis_path: Path) -> dict:
    """读取同名 题库解析.md，返回 {id: {answer, analysis}}。"""
    if not analysis_path.exists():
        return {}
    lines = analysis_path.read_text(encoding="utf-8").splitlines()
    key = {}
    i = 0
    n = len(lines)
    cur_id = None
    cur = {"answer": "", "analysis": ""}
    while i < n:
        m = ID_RE.match(lines[i])
        if m and lines[i].startswith("###"):
            if cur_id is not None:
                key[cur_id] = cur
            cur_id = m.group(1)
            cur = {"answer": "", "analysis": ""}
            i += 1
            continue
        if cur_id is not None:
            am = ANS_RE.search(lines[i])
            if am and not cur["answer"]:
                cur["answer"] = am.group(1).replace("**", "").strip()
            if ANALYSIS_RE.search(lines[i]):
                # 收集解析段：从本行到下一个 ### 或 ##
                parts = [lines[i].split("：", 1)[-1].strip()]
                k = i + 1
                while k < n and not HEAD_RE.match(lines[k]):
                    parts.append(lines[k].strip())
                    k += 1
                cur["analysis"] = "\n".join(p for p in parts if p).strip()
                i = k
                continue
        i += 1
    if cur_id is not None:
        key[cur_id] = cur
    return key


def discover_sets() -> list:
    """返回可刷题套题列表（摘要信息）。"""
    out = []
    for path in _iter_md_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        analysis_path = path.with_name(path.name.replace("题库", "题库解析"))
        lines = path.read_text(encoding="utf-8").splitlines()
        for title, s, e in _split_sections(lines):
            if not SET_RE.search(title):
                continue
            sec = lines[s:e]
            qs = _parse_questions_in_section(sec)
            if not qs:
                continue
            key = _parse_answer_key(analysis_path)
            has_key = any(q["id"] in key for q in qs)
            out.append(
                {
                    "subject": rel,
                    "set": title,
                    "n_questions": len(qs),
                    "has_key": has_key,
                }
            )
    return out


def load_set(subject: str, set_title: str) -> dict:
    """返回某套题的完整结构（含答案键，供判分）。"""
    path = REPO_ROOT / subject
    analysis_path = path.with_name(path.name.replace("题库", "题库解析"))
    lines = path.read_text(encoding="utf-8").splitlines()
    for title, s, e in _split_sections(lines):
        if title == set_title and SET_RE.search(title):
            qs = _parse_questions_in_section(lines[s:e])
            key = _parse_answer_key(analysis_path)
            return {
                "subject": subject,
                "set": set_title,
                "questions": qs,
                "key": key,
            }
    return {"subject": subject, "set": set_title, "questions": [], "key": {}}


# --------------------------------------------------------------------------- #
# 判分
# --------------------------------------------------------------------------- #
def _norm_judge(s: str) -> str:
    s = (s or "").strip().lower()
    if s in ("正确", "对", "√", "t", "true", "yes", "是对的", "正确。"):
        return "正确"
    if s in ("错误", "错", "×", "f", "false", "no", "不对", "是错的", "错误。"):
        return "错误"
    return s


def _grade_objective(qtype: str, student: str, key_answer: str):
    """客观题脚本判分，返回 (correct: bool, norm_student, norm_key)。"""
    if qtype == "判断题":
        ns, nk = _norm_judge(student), _norm_judge(key_answer)
        return (ns == nk and ns in ("正确", "错误")), ns, nk
    # 选择题：取首位字母
    sk = re.match(r"([A-Za-z])", (student or "").strip())
    kk = re.match(r"([A-Za-z])", (key_answer or "").strip())
    if not sk or not kk:
        return False, (student or "").strip(), (key_answer or "").strip()
    return (
        sk.group(1).upper() == kk.group(1).upper(),
        sk.group(1).upper(),
        kk.group(1).upper(),
    )


def grade_submission(set_obj: dict, answers: dict, ai=None) -> dict:
    """对一次提交判分。ai 为 ai_grader.grade 函数或 None。"""
    questions = set_obj["questions"]
    key = set_obj["key"]
    results = []
    pending_total = 0
    for q in questions:
        qid = q["id"]
        student = (answers or {}).get(qid, "")
        if student is None:
            student = ""
        student = str(student).strip()
        entry = key.get(qid, {})
        is_objective = q["type"] in OBJECTIVE_TYPES
        rec = {
            "id": qid,
            "index": q["index"],
            "type": q["type"],
            "difficulty": q["difficulty"],
            "student": student,
            "correct": None,
            "error_type": None,
            "note": "",
            "pending": False,
            "key_answer": entry.get("answer", ""),
        }
        if not student:
            rec["error_type"] = "待复核"
            rec["note"] = "未作答"
            rec["pending"] = True
            pending_total += 1
            results.append(rec)
            continue

        if is_objective:
            ok, ns, nk = _grade_objective(q["type"], student, entry.get("answer", ""))
            rec["correct"] = ok
            rec["student"] = ns
            rec["key_answer"] = nk
            if ok:
                rec["error_type"] = None
                rec["note"] = "客观题脚本判定正确"
            else:
                rec["error_type"] = "概念不清"  # 客观题答错默认归为概念不清
                rec["note"] = "客观题脚本判定错误"
        else:
            if ai is not None:
                try:
                    r = ai(q, student, entry)
                    rec["correct"] = r.get("correct")
                    rec["error_type"] = r.get("错因类型", "待复核")
                    rec["note"] = r.get("错因说明", "")
                    if rec["correct"] is None:
                        rec["pending"] = True
                        pending_total += 1
                except Exception:
                    rec["correct"] = None
                    rec["error_type"] = "待复核"
                    rec["note"] = "AI 判分失败，待人工复核"
                    rec["pending"] = True
                    pending_total += 1
            else:
                rec["correct"] = None
                rec["error_type"] = "待复核"
                rec["note"] = "未配置 AI 端点，待复核"
                rec["pending"] = True
                pending_total += 1
        results.append(rec)

    total = len(results)
    correct = sum(1 for r in results if r["correct"] is True)
    wrong_ids = [r["id"] for r in results if r["correct"] is False]
    summary = {
        "total": total,
        "correct": correct,
        "wrong": total - correct - pending_total,
        "pending": pending_total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "wrong_ids": wrong_ids,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"results": results, "summary": summary}


# --------------------------------------------------------------------------- #
# 回写 题库.md
# --------------------------------------------------------------------------- #
def _find_block(sec_lines, regex):
    for i, l in enumerate(sec_lines):
        if regex.match(l.strip()):
            return i
    return None


def _block_end(sec_lines, start):
    n = len(sec_lines)
    i = start + 1
    while i < n:
        s = sec_lines[i].strip()
        if s.startswith("###") or s.startswith("## "):
            break
        i += 1
    return i


def _review_interval(wrong_count: int) -> int:
    if wrong_count <= 0:
        return 15
    if wrong_count <= 2:
        return 3
    if wrong_count <= 5:
        return 7
    return 15


def write_back(set_obj: dict, graded: dict) -> None:
    """把判分结果写回 题库.md：作答记录 + 订正反馈(5行) + 评估。"""
    path = REPO_ROOT / set_obj["subject"]
    lines = path.read_text(encoding="utf-8").splitlines()
    set_title = set_obj["set"]
    # 定位套题章节
    target = None
    for title, s, e in _split_sections(lines):
        if title == set_title and SET_RE.search(title):
            target = (s, e)
            break
    if target is None:
        return
    s, e = target
    sec = lines[s:e]

    fb_i = _find_block(sec, FB_HEAD_RE)
    if fb_i is None:
        # 理论上 R18 已保证存在；缺失则在章节末尾追加
        sec.append("")
        fb_i = len(sec)
        sec.append(f"### 订正反馈（{set_title}）")

    zl_i = _find_block(sec, ZL_HEAD_RE)
    ev_i = _find_block(sec, EV_HEAD_RE)
    replace_start = min([x for x in (zl_i, fb_i, ev_i) if x is not None])
    # 终结点：覆盖到最后一个相关块之后
    ends = []
    for x in (zl_i, fb_i, ev_i):
        if x is not None:
            ends.append(_block_end(sec, x))
    replace_end = max(ends) if ends else fb_i + 1

    results = graded["results"]
    summary = graded["summary"]

    # 聚合错因
    agg = {t: [] for t in ERROR_TYPES}
    for r in results:
        if r["correct"] is False and r["error_type"] in agg:
            agg[r["error_type"]].append(r["id"])

    # 作答记录块
    zl_lines = [
        f"### 作答记录（{set_title}）",
        "",
        "> 由网页刷题自动生成，判定为「参考」结论：客观题由脚本判定，非客观题由 AI 初判或标待复核；最终以验证题为准。",
        "",
        "| 题号 | 题型 | 学生作答 | 判定 | 错因类型 | 错因说明 | 作答时间 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r["correct"] is True:
            verdict = "正确"
        elif r["correct"] is False:
            verdict = "错误"
        else:
            verdict = "待复核"
        zl_lines.append(
            f"| {r['id']} | {r['type']} | {r['student'] or '（空）'} | {verdict} | {r['error_type'] or '—'} | {r['note'] or '—'} | {summary['ts']} |"
        )
    zl_lines.append("")

    # 订正反馈块（保留 5 类错因行，满足 R18）
    fb_lines = [
        f"### 订正反馈（{set_title}）",
        "",
        "| 问题类型 | 题号 | 具体情况 / 错因 | 是否攻克 |",
        "| --- | --- | --- | --- |",
    ]
    for t in ERROR_TYPES:
        ids = agg[t]
        if ids:
            fb_lines.append(f"| {t} | {', '.join(ids)} | 网页/AI 初判，以验证题为准 | ⬜ |")
        else:
            fb_lines.append(f"| {t} | — | 本轮无此类错误 | 🟢 |")
    fb_lines.append("")
    fb_lines.append("补充（非填空，可写几句）：网页刷题自动记录；错因由脚本/AI 初判，最终以验证题为准。")
    fb_lines.append("")

    # 评估块
    interval = _review_interval(summary["wrong"])
    review_date = (date.today().toordinal() + interval)
    from datetime import date as _d

    review_date_str = _d.fromordinal(review_date).strftime("%Y-%m-%d")
    if summary["wrong"] == 0 and summary["pending"] == 0:
        overall = "✅ 已掌握"
        overall_note = "全部正确，以验证题结果为准"
    else:
        overall = "🟨 学习中"
        overall_note = f"共 {summary['total']} 题，对 {summary['correct']}、错 {summary['wrong']}、待复核 {summary['pending']}，以验证题结果为准"
    main_errors = [t for t in ERROR_TYPES if agg[t]]
    ev_lines = [
        f"### 评估（{set_title}）",
        "",
        "| 维度 | 评估 | 说明 |",
        "| --- | --- | --- |",
        f"| 总体掌握 | {overall} | {overall_note} |",
        f"| 主要错因 | {', '.join(main_errors) if main_errors else '无明显错因'} | 各占对应题数 |",
        "| 建议优先级 | 先攻主要错因 | 见「作答记录」与「订正反馈」 |",
        "| 同类变式题 | 待填写 | 网页刷题自动记录，详见「作答记录」 |",
        f"| 下次回顾间隔 | {interval} 天 | 错 {summary['wrong']} 题，建议短期回顾 |",
        f"| 下次回顾日期 | {review_date_str} | 评估写入日 + 间隔天数 |",
        "",
        f"结论：共 {summary['total']} 题，正确 {summary['correct']} 题"
        + (f"，错误 {summary['wrong']} 题（{', '.join(summary['wrong_ids'])}）" if summary["wrong_ids"] else "")
        + (f"，待复核 {summary['pending']} 题" if summary["pending"] else "")
        + "；建议下次同类变式题巩固。",
        "",
    ]

    new_sec = sec[:replace_start] + zl_lines + fb_lines + ev_lines + sec[replace_end:]
    lines[s:e] = new_sec
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# 监控统计
# --------------------------------------------------------------------------- #
def compute_dashboard() -> dict:
    data = load_results()
    attempts = data.get("attempts", [])
    total_q = sum(a.get("total", 0) for a in attempts)
    correct_q = sum(a.get("correct", 0) for a in attempts)
    pending = sum(a.get("pending", 0) for a in attempts)

    per_set = {}
    weak = {}
    for a in attempts:
        key = (a["subject"], a["set"])
        ps = per_set.setdefault(
            key, {"subject": a["subject"], "set": a["set"], "attempts": 0,
                  "correct": 0, "total": 0, "latest_ts": "", "weak": {}}
        )
        ps["attempts"] += 1
        ps["correct"] += a.get("correct", 0)
        ps["total"] += a.get("total", 0)
        ps["latest_ts"] = a.get("ts", "")
        for wid in a.get("wrong_ids", []):
            ps["weak"][wid] = ps["weak"].get(wid, 0) + 1
            weak[(a["subject"], a["set"], wid)] = weak.get((a["subject"], a["set"], wid), 0) + 1

    per_set_list = []
    for (subj, st), v in per_set.items():
        per_set_list.append(
            {
                "subject": subj,
                "set": st,
                "attempts": v["attempts"],
                "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else 0.0,
                "latest_ts": v["latest_ts"],
                "weak": sorted(v["weak"].items(), key=lambda x: -x[1]),
            }
        )

    weak_list = [
        {"subject": k[0], "set": k[1], "id": k[2], "count": c}
        for k, c in sorted(weak.items(), key=lambda x: -x[1])[:10]
    ]

    recent = [
        {
            "ts": a.get("ts", ""),
            "subject": a["subject"],
            "set": a["set"],
            "total": a.get("total", 0),
            "correct": a.get("correct", 0),
            "pending": a.get("pending", 0),
            "wrong_ids": a.get("wrong_ids", []),
        }
        for a in attempts[-10:][::-1]
    ]

    return {
        "total_attempts": len(attempts),
        "overall": {
            "total": total_q,
            "correct": correct_q,
            "accuracy": round(correct_q / total_q, 4) if total_q else 0.0,
        },
        "pending_review": pending,
        "per_set": per_set_list,
        "weak_questions": weak_list,
        "recent": recent,
    }
