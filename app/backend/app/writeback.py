"""原子回写 题库.md：把判分结果写入「作答记录 + 订正反馈(5类错因) + 评估」三块。

落实《总体设计 · 原子回写》三步法：
1. 读前比对：进入时记录目标文件哈希；替换前重读比对，外部已修改则放弃覆盖并告警。
2. 内存过检：对新内容跑校验器 FILE_RULES（ERROR 级为零才写），不复制规则、不落地临时文件。
3. 原子替换：新内容写同目录 `.<原名>.tmp`，ERROR 为零才 os.replace 瞬时替换。

校验器规则随仓库演进，故动态 import check_docs 跑 FILE_RULES；其 R14 自动登记黑话的
副作用仅在 check_docs.main() 调用 register_new_slang 时发生，本模块只跑规则函数、
不调用登记，故不会污染 slang-words.txt。import 失败时优雅跳过过检（降级日志）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from .grading import ERROR_TYPES, GradedQuestion, GradingResult
from .indexer import REPO_ROOT
from .parser import _split_sections

logger = logging.getLogger("app.writeback")

SET_RE = re.compile(r"测验|专项|模拟卷|真题|自测|练习")
FB_HEAD_RE = re.compile(r"^###\s*订正反馈")
ZL_HEAD_RE = re.compile(r"^###\s*作答记录")
EV_HEAD_RE = re.compile(r"^###\s*评估")

CHECK_DOCS_PATH = (
    Path(__file__).resolve().parents[3]
    / ".codebuddy" / "skills" / "danzhao-docs" / "scripts" / "check_docs.py"
)


class WriteConflict(Exception):
    """目标文件在读取与写入之间被外部修改，放弃覆盖以免丢失他人改动。"""


class PreCheckError(Exception):
    """回写内容未通过校验器 ERROR 级检查，拒绝写入以免污染 AI 输入。"""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _review_interval(wrong: int) -> int:
    if wrong <= 0:
        return 15
    if wrong <= 2:
        return 3
    if wrong <= 5:
        return 7
    return 15


def _find_block(sec_lines, regex) -> Optional[int]:
    for i, line in enumerate(sec_lines):
        if regex.match(line.strip()):
            return i
    return None


def _block_end(sec_lines, start: int) -> int:
    n = len(sec_lines)
    i = start + 1
    while i < n:
        s = sec_lines[i].strip()
        if s.startswith("###") or s.startswith("## "):
            break
        i += 1
    return i


def build_blocks(section_title: str, graded: GradingResult) -> list[str]:
    """构造「作答记录 + 订正反馈(5类错因) + 评估」三块（移植自已退役的初版服务）。"""
    results = graded.results
    summary = graded.summary

    agg = {t: [] for t in ERROR_TYPES}
    for r in results:
        if r.is_correct is False and r.error_type in agg:
            agg[r.error_type].append(r.qid)

    ts = summary.get("ts", "")

    # 作答记录块
    zl_lines = [
        f"### 作答记录（{section_title}）",
        "",
        "> 由复习管理系统自动生成：客观题由脚本判定，非客观题标待复核/AI 初判，最终以验证题为准。",
        "",
        "| 题号 | 题型 | 学生作答 | 判定 | 错因类型 | 错因说明 | 作答时间 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r.is_correct is True:
            verdict = "正确"
        elif r.is_correct is False:
            verdict = "错误"
        else:
            verdict = "待复核"
        zl_lines.append(
            f"| {r.qid} | {r.q_type} | {r.student or '（空）'} | {verdict} "
            f"| {r.error_type or '—'} | {r.note or '—'} | {ts} |"
        )
    zl_lines.append("")

    # 订正反馈块（保留 5 类错因行，满足 R18）
    fb_lines = [
        f"### 订正反馈（{section_title}）",
        "",
        "| 问题类型 | 题号 | 具体情况 / 错因 | 是否攻克 |",
        "| --- | --- | --- | --- |",
    ]
    for t in ERROR_TYPES:
        ids = agg[t]
        if ids:
            fb_lines.append(
                f"| {t} | {', '.join(ids)} | 系统初判，以验证题为准 | ⬜ |"
            )
        else:
            fb_lines.append(f"| {t} | — | 本轮无此类错误 | 🟢 |")
    # 待复核行（R19 一致性）：有未判题目时「是否攻克」不全绿，
    # 总体掌握才能保持 🟨 学习中，避免「反馈全绿但评估 🟨」被 R19 告警
    pending_ids = [r.qid for r in results if r.eval_state == "pending_manual"]
    if pending_ids:
        fb_lines.append(
            f"| 待复核 | {', '.join(pending_ids)} | 非客观题未判或未作答，待人工复核 | ⬜ |"
        )
    fb_lines.append("")
    fb_lines.append("补充：系统自动记录；错因由脚本/AI 初判，最终以验证题为准。")
    fb_lines.append("")

    # 评估块（与 R19 一致：全绿才标 ✅）
    interval = _review_interval(summary["wrong"])
    review_date_str = date.fromordinal(date.today().toordinal() + interval).strftime(
        "%Y-%m-%d"
    )
    if summary["wrong"] == 0 and summary["pending"] == 0:
        overall = "✅ 已掌握"
        overall_note = "全部正确，以验证题结果为准"
    else:
        overall = "🟨 学习中"
        overall_note = (
            f"共 {summary['total']} 题，对 {summary['correct']}、"
            f"错 {summary['wrong']}、待复核 {summary['pending']}，以验证题结果为准"
        )
    main_errors = [t for t in ERROR_TYPES if agg[t]]
    ev_lines = [
        f"### 评估（{section_title}）",
        "",
        "| 维度 | 评估 | 说明 |",
        "| --- | --- | --- |",
        f"| 总体掌握 | {overall} | {overall_note} |",
        f"| 主要错因 | {', '.join(main_errors) if main_errors else '无明显错因'} | 各占对应题数 |",
        "| 建议优先级 | 先攻主要错因 | 见「作答记录」与「订正反馈」 |",
        "| 同类变式题 | 待填写 | 系统自动记录，详见「作答记录」 |",
        f"| 下次回顾间隔 | {interval} 天 | 错 {summary['wrong']} 题，建议短期回顾 |",
        f"| 下次回顾日期 | {review_date_str} | 评估写入日 + 间隔天数 |",
        "",
        f"结论：共 {summary['total']} 题，正确 {summary['correct']} 题"
        + (
            f"，错误 {summary['wrong']} 题（{', '.join(summary['wrong_ids'])}）"
            if summary["wrong_ids"]
            else ""
        )
        + (f"，待复核 {summary['pending']} 题" if summary["pending"] else "")
        + "；建议下次同类变式题巩固。",
        "",
    ]

    return zl_lines + fb_lines + ev_lines


# 回写前过检的「阻断项」：只拦截会污染 AI 输入的内联答案(R17)与黑话(R14)。
# 其余 ERROR（R03/R15/R16 等文档结构/质量项）属既有文档瑕疵，仅告警不阻断，
# 否则任一旧文档结构不达标都会让合法回写无法落地。
BLOCKING_RULES = {"R14", "R17"}


def _precheck(rel: str, text: str) -> list[str]:
    """内存过检：跑 FILE_RULES，仅返回阻断项(BLOCKING_RULES)的问题；不可用则跳过。"""
    if not CHECK_DOCS_PATH.exists():
        logger.warning("校验器脚本缺失，跳过回写前内存过检: %s", CHECK_DOCS_PATH)
        return []
    try:
        spec = importlib.util.spec_from_file_location("check_docs_wb", CHECK_DOCS_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 - 校验器不可用不应阻断回写
        logger.warning("回写前校验器 import 失败，跳过内存过检: %s", exc)
        return []

    lines = text.splitlines()
    words, ignored = mod.load_slang_words()
    ctx = {
        "root": REPO_ROOT,
        "words": mod.load_colloquial_words(),
        "prefixes": mod.load_prefixes(),
        "slang_words": words,
        "slang_ignored": ignored,
        "slang_candidates": {},
    }
    issues: list[str] = []
    for rule in mod.FILE_RULES:
        try:
            for iss in rule(rel, lines, ctx):
                if getattr(iss, "severity", None) != mod.SEVERITY_ERROR:
                    continue
                rid = getattr(iss, "rule_id", "")
                if rid in BLOCKING_RULES:
                    issues.append(f"[{rid}] {iss.message}")
                else:
                    # 非阻断项：仅告警，不阻断回写
                    logger.warning("回写前校验 %s（非阻断，仅提示）: %s", rid, iss.message)
        except Exception as exc:  # noqa: BLE001 - 单条规则异常不应阻断
            logger.warning("校验规则 %s 执行异常，跳过: %s", getattr(rule, "__name__", rule), exc)
    return issues


def atomic_write_text(
    target: Path, new_text: str, expected_hash: str, repo_root: Optional[Path] = None
) -> None:
    """原子写：读前比对(冲突检测) → 临时文件 + os.replace。

    内存过检在 write_back 中对「新增块」单独执行（详见 write_back），此处只负责
    冲突检测与瞬时替换，不重复跑校验器。
    """
    # 1. 读前比对：外部已修改则放弃覆盖
    current = target.read_text(encoding="utf-8")
    if _sha256_text(current) != expected_hash:
        raise WriteConflict(f"目标文件已被外部修改，放弃覆盖：{target}")

    # 2. 原子替换
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, target)


def atomic_replace(target: Path, new_text: str) -> None:
    """原子替换（无哈希基线）：导出视图专用，供 exporter 使用。

    与 atomic_write_text 的区别：不做读前比对。导出每次都基于最新读取的
    文本做变换，外部（AI/手改）对导出区块的修改会被本次导出自然覆盖——
    这正是「过程数据以 DB 为源」的语义。非导出场景仍应走 atomic_write_text，
    保留写前冲突保护。
    """
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, target)


def write_back(
    file_path_rel: str,
    section_title: str,
    graded: GradingResult,
    repo_root: Optional[Path] = None,
) -> dict:
    """把判分结果回写 题库.md 对应套题章节（原子写入）。"""
    root = Path(repo_root or REPO_ROOT)
    path = root / file_path_rel
    text = path.read_text(encoding="utf-8")
    entry_hash = _sha256_text(text)  # 进入任务时记录哈希，作为冲突比对基线

    lines = text.splitlines()
    target = None
    for title, s, e in _split_sections(lines):
        if title == section_title and SET_RE.search(title):
            target = (s, e)
            break
    if target is None:
        raise ValueError(f"未找到套题章节：{section_title}")

    s, e = target
    sec = lines[s:e]
    fb_i = _find_block(sec, FB_HEAD_RE)
    zl_i = _find_block(sec, ZL_HEAD_RE)
    ev_i = _find_block(sec, EV_HEAD_RE)
    new_blocks = build_blocks(section_title, graded)

    if fb_i is None and zl_i is None and ev_i is None:
        # 章节内尚无反馈块（R18 要求缺失时由系统补建）
        new_sec = sec + [""] + new_blocks
    else:
        replace_start = min(x for x in (zl_i, fb_i, ev_i) if x is not None)
        ends = [_block_end(sec, x) for x in (zl_i, fb_i, ev_i) if x is not None]
        replace_end = max(ends)
        new_sec = sec[:replace_start] + new_blocks + sec[replace_end:]

    new_lines = lines[:s] + new_sec + lines[e:]
    new_text = "\n".join(new_lines) + "\n"

    # 内存过检：对整篇内容跑 FILE_RULES（R18/R19 横跨章节需整篇），但仅把会污染
    # AI 输入的内联答案(R17)与黑话(R14)设为阻断项；其余 ERROR 仅告警，避免既有
    # 文档结构瑕疵(R03/R15/R16 等)阻断合法回写。
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    errs = _precheck(rel, new_text)
    if errs:
        raise PreCheckError(errs)

    atomic_write_text(path, new_text, entry_hash, root)
    return {"status": "written", "file": file_path_rel, "section": section_title}
