"""过程数据导出器（P9 试点）：SQLite 为源，markdown 为导出视图。

试点范围（过程数据，网页端编辑最频繁、天然结构化的两类）：
- 复习计划/节点安排.md「一、节点总表」**状态列** ← plan_checkins 推导
  （明细本就是事实源，状态列此前后是「回写目标」，现改为导出视图）；
- 错题本/README.md「一、错题记录 / 二、按科目统计 / 三、高频错因 TOP」
  ← quiz_attempts + quiz_feedback + wrongbook_reviews 汇总。

契约（与《总体设计 · 数据所有权划分》对应，硬约束）：
1. 过程数据的事实源是 SQLite；md 对应区块只是渲染视图，可随时删除重生成。
2. 导出**幂等**：内容与 DB 推导一致则不动文件（返回 unchanged）。
3. 冲突语义与回写**相反**：外部（AI/手改）对导出区块的修改会被下次导出覆盖，
   这是「DB 为源」的含义；因此不做读前哈希比对（见 writeback.atomic_replace）。
4. **只触碰导出区块**：文档其余部分（使用说明、其他章节、表头）逐字保留。
5. 写入前过检（R14/R17 阻断项，同回写器策略）+ 临时文件原子替换。
6. md 区块被覆盖 = 预期行为；AI 与手写内容请落到内容文档（题库解析/评估块）
   或过程数据的写入接口（feedback/review），不要写导出区块。

触发点：交卷（quiz.submit / submit-wrong）、人工复核（quiz.review）、
反馈（feedback）、复盘登记（feedback.wrong/review）、打卡（plan.checkin）
均 best-effort 调用；也可用 CLI 手动重生成：
    python -m app export plan|wrongbook|all
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from . import indexer
from .db import connect
from .feedback import ERROR_TYPES
from .parser import _split_sections
from .plan import PLAN_REL, derive_status, latest_checkins, parse_nodes
from .writeback import PreCheckError, _precheck, atomic_replace

logger = logging.getLogger("app.exporter")

WRONGBOOK_REL = "错题本/README.md"
NODE_SECTION_KEYWORD = "节点总表"

# 错题本 README「二、按科目统计」的固定科目表（与模板一致）；数据里出现
# 表外科目时追加在表尾
SUBJECT_ROSTER = ["语文", "数学", "英语", "解剖学基础", "生理学基础", "护理学基础"]

# 复盘做满 4 次标记已攻克（错题本 README 使用说明：1/3/7/15 天四次均做对）
MASTERY_REVIEWS = 4

# 各导出区块的空态模板行：与 错题本/README.md 现有模板逐字一致，
# 保证空库时导出结果与模板相同（文件不动）
_EMPTY_RECORD_ROW = "| CT-001 | 待填写 | | | | | | 0 | 🔴 未攻克 |"
_EMPTY_SUBJECT_ROW = "| 待填写 | 待填写 | 待填写 |"


# --------------------------------------------------------------------------- #
# 行级小工具（与 feedback/plan 同构，避免跨模块私有引用）
# --------------------------------------------------------------------------- #
def _split_row(line: str) -> list[str]:
    return [p.strip() for p in line.strip().strip("|").split("|")]


def _make_row(cols: list[str]) -> str:
    return "| " + " | ".join(cols) + " |"


def _is_sep(line: str) -> bool:
    s = line.strip().strip("|").replace(" ", "").replace("|", "")
    return bool(s) and set(s) <= set("-:")


def _subject_of(file_path: str) -> str:
    """题库路径 → 科目（对齐错题本「按科目统计」的粒度）。

    - 护理专业/解剖学基础/… → 解剖学基础（取二级目录）
    - 测验/摸底/护理学基础/… → 护理学基础（跳过「测验/摸底」两级）
    - 其余 → 一级目录（数学 / 英语 / 语文）
    """
    parts = [p for p in file_path.split("/") if p]
    if not parts:
        return "未知"
    if parts[0] == "护理专业" and len(parts) >= 2:
        return parts[1]
    if parts[0] == "测验" and len(parts) >= 3:
        return parts[2]
    return parts[0]


def _short_stem(stem: Optional[str], limit: int = 30) -> str:
    text = (stem or "").replace("\n", " ").strip()
    if not text:
        return "待填写"
    return text[:limit] + ("…" if len(text) > limit else "")


def _clip_date(ts: Optional[str]) -> str:
    return (ts or "")[:10] or "待填写"


# --------------------------------------------------------------------------- #
# 节点状态列导出（plan_checkins → 节点安排.md）
# --------------------------------------------------------------------------- #
def export_plan_status(repo_root: Optional[Path] = None) -> dict:
    """按 plan_checkins 推导全量节点状态，重写 节点安排.md 节点总表状态列。

    只改节点行的末列一个单元格；文档其余部分逐字保留。推导规则同
    plan.derive_status：最近一次打卡状态，无打卡 → ⬜。
    """
    root = Path(repo_root) if repo_root else indexer.REPO_ROOT
    path = root / PLAN_REL
    if not path.is_file():
        raise FileNotFoundError(f"未找到 {PLAN_REL}")

    nodes = parse_nodes(path)
    latest = latest_checkins()
    node_ids = {n["node_id"] for n in nodes}

    lines = path.read_text(encoding="utf-8").splitlines()
    changed = 0
    for title, s, e in _split_sections(lines):
        if NODE_SECTION_KEYWORD not in title:
            continue
        for i in range(s, e):
            cells = _split_row(lines[i])
            if len(cells) >= 7 and cells[0] in node_ids:
                want = derive_status(latest.get(cells[0]))
                if cells[6] != want:
                    cells[6] = want
                    lines[i] = _make_row(cells)
                    changed += 1
        break  # 节点总表唯一，取到即止

    if changed == 0:
        return {"status": "unchanged", "file": PLAN_REL, "nodes": len(nodes)}

    new_text = "\n".join(lines) + "\n"
    errs = _precheck(PLAN_REL, new_text)
    if errs:
        raise PreCheckError(errs)

    atomic_replace(path, new_text)
    return {"status": "written", "file": PLAN_REL, "nodes": len(nodes), "updated": changed}


# --------------------------------------------------------------------------- #
# 错题本数据汇总（quiz_attempts + quiz_feedback + wrongbook_reviews → dict）
# --------------------------------------------------------------------------- #
def collect_wrongbook() -> dict:
    """汇总错题本视图所需的全部过程数据（纯读，不写任何文件）。

    items：去重错题（任一次作答错即入册），按首次答错时间排序；
    每项带错因（反馈优先、判分兜底）、复盘统计与最近一次复盘要点。
    """
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT a.file_path AS file_path, a.qid AS qid,
                   q.section_title AS section_title, q.stem AS stem,
                   MIN(CASE WHEN a.is_correct = 0 THEN a.created_at END) AS first_wrong_at,
                   SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END) AS wrong_times
            FROM quiz_attempts a
            LEFT JOIN questions_index q ON q.file_path = a.file_path AND q.qid = a.qid
            GROUP BY a.file_path, a.qid
            HAVING wrong_times > 0
            ORDER BY first_wrong_at, a.file_path, a.qid
            """
        ).fetchall()

        items: list[dict] = []
        for r in rows:
            fp, qid = r["file_path"], r["qid"]
            error_type = _latest_error_type(conn, fp, qid)
            reviews = conn.execute(
                "SELECT result, note FROM wrongbook_reviews "
                "WHERE file_path=? AND qid=? ORDER BY id",
                (fp, qid),
            ).fetchall()
            review_correct = sum(1 for x in reviews if x["result"])
            trailing = 0
            for x in reversed(reviews):  # 最近连续做对次数
                if x["result"]:
                    trailing += 1
                else:
                    break
            note = next(
                (x["note"] for x in reversed(reviews) if x["note"] and x["note"].strip()),
                None,
            )
            items.append(
                {
                    "file_path": fp,
                    "qid": qid,
                    "section_title": r["section_title"] or "",
                    "stem": r["stem"],
                    "subject": _subject_of(fp),
                    "source": f"{fp}#{qid}",
                    "first_wrong_at": r["first_wrong_at"],
                    "wrong_times": r["wrong_times"],
                    "error_type": error_type,
                    "review_correct": review_correct,
                    "mastered": trailing >= MASTERY_REVIEWS,
                    "note": note,
                }
            )

        error_rows = conn.execute(
            "SELECT error_type, COUNT(*) AS n FROM quiz_feedback "
            "WHERE error_type IS NOT NULL GROUP BY error_type"
        ).fetchall()
    finally:
        conn.close()

    error_top = [
        {"error_type": r["error_type"], "count": r["n"]}
        for r in sorted(error_rows, key=lambda x: (-x["n"], x["error_type"]))
        if r["error_type"] in ERROR_TYPES
    ]
    return {"items": items, "error_top": error_top}


def _latest_error_type(conn, file_path: str, qid: str) -> Optional[str]:
    """错因：quiz_feedback 学生自选优先，判分时写入的 quiz_attempts 兜底。"""
    row = conn.execute(
        "SELECT error_type FROM quiz_feedback "
        "WHERE file_path=? AND qid=? AND error_type IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (file_path, qid),
    ).fetchone()
    if row:
        return row["error_type"]
    row = conn.execute(
        "SELECT error_type FROM quiz_attempts "
        "WHERE file_path=? AND qid=? AND error_type IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (file_path, qid),
    ).fetchone()
    return row["error_type"] if row else None


# --------------------------------------------------------------------------- #
# 错题本导出（collect_wrongbook → 错题本/README.md 三张表）
# --------------------------------------------------------------------------- #
def _render_records(items: list[dict]) -> list[str]:
    if not items:
        return [_EMPTY_RECORD_ROW]
    rows = []
    for i, it in enumerate(items, 1):
        rows.append(
            _make_row(
                [
                    f"CT-{i:03d}",
                    it["subject"],
                    it["source"],
                    _short_stem(it["stem"]),
                    it["error_type"] or "待填写",
                    (it["note"] or "").replace("\n", " ").replace("|", "/") or "待填写",
                    _clip_date(it["first_wrong_at"]),
                    str(it["review_correct"]),
                    "🟢 已攻克" if it["mastered"] else "🔴 未攻克",
                ]
            )
        )
    return rows


def _render_subject_stats(items: list[dict]) -> list[str]:
    if not items:
        return [_EMPTY_SUBJECT_ROW]
    stats: dict[str, dict[str, int]] = {}
    for it in items:
        st = stats.setdefault(it["subject"], {"total": 0, "open": 0, "mastered": 0})
        st["total"] += 1
        st["mastered" if it["mastered"] else "open"] += 1
    # 固定科目表全量输出（含 0），表外科目追加在表尾：行集合稳定，便于 diff 与幂等
    extras = sorted(s for s in stats if s not in SUBJECT_ROSTER)
    zero = {"total": 0, "open": 0, "mastered": 0}
    return [
        _make_row(
            [
                s,
                str(stats.get(s, zero)["total"]),
                str(stats.get(s, zero)["open"]),
                str(stats.get(s, zero)["mastered"]),
            ]
        )
        for s in SUBJECT_ROSTER + extras
    ]


def _render_error_top(error_top: list[dict]) -> list[str]:
    if not error_top:
        return [_EMPTY_SUBJECT_ROW]
    # 整改措施是学习者/AI 的策展内容，不属过程数据：占位待填
    return [_make_row([e["error_type"], str(e["count"]), "待填写"]) for e in error_top]


def _rebuild_section(lines: list[str], heading: str, header_cell: str, rows: list[str]) -> list[str]:
    """重写某二级章节下的表格数据行；表头/分隔行/章节内其他内容逐字保留。"""
    hi = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if hi is None:
        raise RuntimeError(f"缺少章节：{heading}")
    end = next(
        (i for i in range(hi + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
    )
    ti = next(
        (
            i
            for i in range(hi, end)
            if lines[i].lstrip().startswith("|") and _split_row(lines[i])[:1] == [header_cell]
        ),
        None,
    )
    if ti is None:
        raise RuntimeError(f"章节 {heading} 缺少表格（表头首列应为「{header_cell}」）")
    if ti + 1 >= end or not _is_sep(lines[ti + 1]):
        raise RuntimeError(f"章节 {heading} 的表格缺少分隔行")
    dj = ti + 2  # 数据行范围：分隔行之后连续的 | 行
    while dj < end and lines[dj].lstrip().startswith("|"):
        dj += 1
    return lines[: ti + 2] + rows + lines[dj:]


def export_wrongbook(repo_root: Optional[Path] = None) -> dict:
    """按过程数据重生成 错题本/README.md 的一/二/三张表（其余内容不动）。"""
    root = Path(repo_root) if repo_root else indexer.REPO_ROOT
    path = root / WRONGBOOK_REL
    if not path.is_file():
        raise FileNotFoundError(f"未找到 {WRONGBOOK_REL}")

    data = collect_wrongbook()
    if not data["items"] and not data["error_top"]:
        # 空库：与模板一致，文件不动（避免无意义 diff）
        return {"status": "unchanged", "file": WRONGBOOK_REL, "reason": "no-data"}

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines = _rebuild_section(lines, "## 一、错题记录", "编号", _render_records(data["items"]))
    lines = _rebuild_section(lines, "## 二、按科目统计", "科目", _render_subject_stats(data["items"]))
    lines = _rebuild_section(lines, "## 三、高频错因 TOP", "错因类型", _render_error_top(data["error_top"]))
    new_text = "\n".join(lines) + "\n"
    if new_text == text:
        return {"status": "unchanged", "file": WRONGBOOK_REL, "items": len(data["items"])}

    errs = _precheck(WRONGBOOK_REL, new_text)
    if errs:
        raise PreCheckError(errs)

    atomic_replace(path, new_text)
    return {"status": "written", "file": WRONGBOOK_REL, "items": len(data["items"])}


# --------------------------------------------------------------------------- #
# best-effort 包装：交互钩子（交卷/反馈/复核/复盘/打卡）共用
# --------------------------------------------------------------------------- #
def safe_export(kind: str) -> str:
    """best-effort 导出：失败只返回状态标记并记日志，绝不打断主流程。"""
    try:
        if kind == "plan":
            return export_plan_status()["status"]
        if kind == "wrongbook":
            return export_wrongbook()["status"]
        raise ValueError(f"未知导出类型：{kind}")
    except PreCheckError as exc:
        logger.warning("%s 导出未通过校验器检查，已跳过：%s", kind, exc)
        return "precheck_failed"
    except Exception as exc:  # noqa: BLE001 - 视图是派生数据，失败不应影响交互
        logger.warning("%s 导出失败（不影响主流程）: %s", kind, exc)
        return "failed"


# --------------------------------------------------------------------------- #
# CLI：python -m app export plan|wrongbook|all [--json]
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app export",
        description="过程数据导出：以 SQLite 为源重生成 markdown 视图（可反复执行，幂等）",
    )
    parser.add_argument(
        "command",
        choices=["plan", "wrongbook", "all"],
        help="plan=节点状态列；wrongbook=错题本三表；all=两者",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非摘要")
    args = parser.parse_args(argv)

    results: dict[str, dict] = {}
    if args.command in ("plan", "all"):
        results["plan"] = export_plan_status()
    if args.command in ("wrongbook", "all"):
        results["wrongbook"] = export_wrongbook()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        for kind, res in results.items():
            detail = res.get("updated") or res.get("items") or res.get("reason") or ""
            print(f"{kind}: {res['status']}（{res['file']}{'，' + str(detail) if detail != '' else ''}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
